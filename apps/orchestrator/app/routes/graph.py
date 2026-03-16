import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from neo4j import AsyncGraphDatabase

from ..auth import get_current_user
from ..config import Settings

logger = logging.getLogger("orchestrator.graph")
router = APIRouter()

_driver = None


def init_graph(settings: Settings):
    global _driver
    _driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )


async def close_graph():
    global _driver
    if _driver:
        await _driver.close()
        _driver = None


@router.get("/v1/graph/top")
async def get_top_graph(
    workspace: str = Query(...),
    limit: int = Query(default=2000, le=5000),
    _user: dict = Depends(get_current_user),
):
    """Return the top N nodes by relationship count with their edges.

    Single Cypher query — no per-label iteration.
    LightRAG stores workspace as a Neo4j label on each node.
    """
    # Sanitize workspace name for safe label interpolation (labels can't be parameterized)
    if not re.match(r'^[a-zA-Z0-9_-]+$', workspace):
        raise HTTPException(400, "Invalid workspace name")
    safe_label = f"`{workspace}`"

    async with _driver.session() as session:
        result = await session.run(
            f"""
            MATCH (n:{safe_label})
            WITH n, size([(n)-[]-() | 1]) AS degree
            ORDER BY degree DESC
            LIMIT $limit
            WITH collect(n) AS topNodes, collect(id(n)) AS topIds
            UNWIND topNodes AS n
            OPTIONAL MATCH (n)-[r]-(m)
            WHERE id(m) IN topIds
            RETURN
              collect(DISTINCT {{
                id: toString(id(n)),
                label: coalesce(n.entity_id, n.name, toString(id(n))),
                type: coalesce(n.entity_type, 'unknown'),
                description: n.description
              }}) AS nodes,
              collect(DISTINCT {{
                source: toString(id(startNode(r))),
                target: toString(id(endNode(r))),
                label: coalesce(type(r), ''),
                description: r.description
              }}) AS edges
            """,
            limit=limit,
        )
        record = await result.single()

    nodes = record["nodes"] if record else []
    edges = record["edges"] if record else []
    # Filter out null edges from nodes with no relationships
    edges = [e for e in edges if e.get("source") and e.get("target")]

    # Get total counts for the workspace
    async with _driver.session() as session:
        totals = await session.run(
            f"""
            MATCH (n:{safe_label})
            WITH count(n) AS total_nodes
            OPTIONAL MATCH (:{safe_label})-[r]->(:{safe_label})
            RETURN total_nodes, count(r) AS total_edges
            """,
        )
        totals_record = await totals.single()

    total_nodes = totals_record["total_nodes"] if totals_record else 0
    total_edges = totals_record["total_edges"] if totals_record else 0

    return {
        "nodes": nodes,
        "edges": edges,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "truncated": len(nodes) >= limit,
    }
