import logging
from collections import defaultdict

import httpx
import neo4j as neo4j_driver

from ..config import Settings
from ..db import get_pool

logger = logging.getLogger("orchestrator.reconcile")

_driver = None
_settings: Settings | None = None
_http_client: httpx.AsyncClient | None = None

# LightRAG entity vector table (derived from model name + dim)
ENTITY_VDB_TABLE = "lightrag_vdb_entity_qwen_qwen3_embedding_0_6b_1024d"


def init_reconcile(settings: Settings, client: httpx.AsyncClient):
    global _driver, _settings, _http_client
    _settings = settings
    _http_client = client
    _driver = neo4j_driver.GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


def close_reconcile():
    global _driver
    if _driver:
        _driver.close()
        _driver = None


def _find_components(nodes: list[str], edges: list[tuple[str, str]]) -> list[set[str]]:
    """Union-find to identify connected components."""
    parent = {n: n for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for src, tgt in edges:
        if src in parent and tgt in parent:
            union(src, tgt)

    groups = defaultdict(set)
    for n in nodes:
        groups[find(n)].add(n)

    return list(groups.values())


def _get_graph(workspace: str) -> tuple[dict, list]:
    """Fetch all entities and edges from Neo4j for a workspace."""
    entities = {}
    edges = []

    with _driver.session() as session:
        result = session.run(
            f"MATCH (n:`{workspace}`) "
            f"RETURN n.entity_id AS id, n.entity_type AS type, n.description AS desc"
        )
        for record in result:
            eid = record["id"]
            if eid:
                entities[eid] = {
                    "id": eid,
                    "type": record["type"] or "unknown",
                    "description": record["desc"] or "",
                }

        result = session.run(
            f"MATCH (a:`{workspace}`)-[r]-(b:`{workspace}`) "
            f"RETURN DISTINCT a.entity_id AS src, b.entity_id AS tgt"
        )
        for record in result:
            if record["src"] and record["tgt"]:
                edges.append((record["src"], record["tgt"]))

    return entities, edges


async def _find_nearest_in_main(
    workspace: str,
    cluster_entity_ids: list[str],
    main_entity_ids: set[str],
) -> list[dict]:
    """Use pgvector HNSW index to find nearest main-component entity for each cluster entity."""
    pool = get_pool()
    bridges = []

    # Query enough neighbors to find one that's in the main component
    k = min(len(main_entity_ids), 20)

    async with pool.acquire() as conn:
        for eid in cluster_entity_ids:
            row = await conn.fetchrow(
                f"SELECT content_vector FROM {ENTITY_VDB_TABLE} "
                f"WHERE workspace = $1 AND entity_name = $2 "
                f"LIMIT 1",
                workspace, eid,
            )
            if not row or not row["content_vector"]:
                continue

            vec = row["content_vector"]
            # HNSW cosine nearest neighbor search, excluding same cluster
            neighbors = await conn.fetch(
                f"SELECT entity_name, 1 - (content_vector <=> $1::vector) AS similarity "
                f"FROM {ENTITY_VDB_TABLE} "
                f"WHERE workspace = $2 AND entity_name != $3 "
                f"ORDER BY content_vector <=> $1::vector "
                f"LIMIT $4",
                vec, workspace, eid, k,
            )

            for nb in neighbors:
                if nb["entity_name"] in main_entity_ids:
                    bridges.append({
                        "src": eid,
                        "tgt": nb["entity_name"],
                        "reason": f"vector similarity {nb['similarity']:.3f}",
                        "similarity": float(nb["similarity"]),
                    })
                    break  # one bridge per cluster entity

            if bridges and bridges[-1]["src"] == eid:
                break  # found a bridge for this cluster, move on

    return bridges


def _write_bridge_edges(workspace: str, bridges: list[dict]):
    """Write bridge edges to Neo4j."""
    with _driver.session() as session:
        for bridge in bridges:
            session.run(
                f"MATCH (a:`{workspace}` {{entity_id: $src}}) "
                f"MATCH (b:`{workspace}` {{entity_id: $tgt}}) "
                f"MERGE (a)-[r:BRIDGE_TO]-(b) "
                f"SET r.description = $reason, r.bridge = true, r.weight = 1.0",
                src=bridge["src"],
                tgt=bridge["tgt"],
                reason=bridge.get("reason", "bridge edge"),
            )


async def reconcile(workspace: str) -> dict:
    """Find disconnected clusters and create bridge edges to the main graph."""
    entities, edges = _get_graph(workspace)

    if len(entities) < 2:
        return {"bridges_created": 0, "clusters_found": 0, "message": "Not enough entities"}

    components = _find_components(list(entities.keys()), edges)
    components.sort(key=len, reverse=True)

    if len(components) <= 1:
        return {"bridges_created": 0, "clusters_found": 1, "message": "Graph is already fully connected"}

    main_component = components[0]
    main_ids = set(main_component)
    isolated = components[1:]

    all_bridges = []
    for cluster in isolated:
        cluster_ids = [eid for eid in cluster if eid in entities]
        bridges = await _find_nearest_in_main(workspace, cluster_ids, main_ids)
        all_bridges.extend(bridges)

    if all_bridges:
        _write_bridge_edges(workspace, all_bridges)

    return {
        "bridges_created": len(all_bridges),
        "clusters_found": len(components),
        "isolated_clusters": len(isolated),
        "bridges": [
            {"src": b["src"], "tgt": b["tgt"], "reason": b["reason"]}
            for b in all_bridges
        ],
    }
