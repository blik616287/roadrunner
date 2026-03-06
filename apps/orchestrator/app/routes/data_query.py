import logging
import math

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from ..config import Settings
from ..models import DataQueryRequest, DataQueryResponse, GraphSubgraph, Choice, ChatMessage
from ..services import archival_memory, query_tracker, reconcile
from ..db import get_pool

logger = logging.getLogger("orchestrator.data_query")
router = APIRouter()

_settings: Settings | None = None
_http_client: httpx.AsyncClient | None = None


def init_data_query(settings: Settings, client: httpx.AsyncClient):
    global _settings, _http_client
    _settings = settings
    _http_client = client


@router.post("/v1/data/query")
async def data_query(
    request: DataQueryRequest,
    x_workspace: str | None = Header(default=None, alias="x-workspace"),
):
    workspace = request.workspace or x_workspace or "default"
    mode = request.mode or "hybrid"

    # Check reranker health — 503 if unavailable (burst mode)
    try:
        resp = await _http_client.get(
            f"{_settings.reranker_url}/health", timeout=3.0
        )
        if resp.status_code != 200:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "message": "Reranker unavailable (system in burst ingestion mode). Try again later.",
                        "type": "service_unavailable",
                        "code": 503,
                    }
                },
            )
    except httpx.HTTPError:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": "Reranker unavailable (system in burst ingestion mode). Try again later.",
                    "type": "service_unavailable",
                    "code": 503,
                }
            },
        )

    # Mark query as active (Redis TTL for burst mode coordination)
    await query_tracker.mark_active()

    # Query the knowledge graph
    data = await archival_memory.query(
        request.query, workspace, mode=mode, client=_http_client
    )

    graph = GraphSubgraph(
        entities=data.get("entities", []),
        relations=data.get("relations", []),
        chunks=data.get("chunks", []),
    )

    # Format as human-readable summary
    context = archival_memory.format_context(data)

    return DataQueryResponse(
        model="graphrag",
        choices=[
            Choice(
                message=ChatMessage(role="assistant", content=context or "No results found."),
            )
        ],
        graph=graph,
    )


@router.post("/v1/data/explain")
async def data_explain(
    request: DataQueryRequest,
    x_workspace: str | None = Header(default=None, alias="x-workspace"),
):
    """Retrieve graph data then synthesize an LLM explanation via vllm-query."""
    workspace = request.workspace or x_workspace or "default"
    mode = request.mode or "hybrid"

    # Retrieve graph context
    data = await archival_memory.query(
        request.query, workspace, mode=mode, client=_http_client
    )
    context = archival_memory.format_context(data)
    if not context:
        return {"response": "No relevant data found in the knowledge graph."}

    # Call vllm-query for LLM synthesis
    messages = [
        {
            "role": "system",
            "content": (
                "You are a knowledgeable assistant. Based on the knowledge graph data below, "
                "provide a clear, well-structured answer to the user's question. "
                "Reference specific entities, relationships, and code when relevant."
            ),
        },
        {
            "role": "user",
            "content": f"Knowledge graph context:\n\n{context}\n\nQuestion: {request.query}",
        },
    ]

    try:
        resp = await _http_client.post(
            f"{_settings.query_llm_url}/chat/completions",
            json={
                "model": _settings.query_llm_model,
                "messages": messages,
                "max_tokens": 2048,
                "temperature": 0.7,
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        result = resp.json()
        answer = result["choices"][0]["message"]["content"]
        return {"response": answer}
    except Exception as e:
        logger.error(f"Explain LLM call failed: {e}")
        # Fall back to raw context
        return {"response": context}


@router.post("/v1/data/reconcile")
async def data_reconcile(
    workspace: str | None = None,
    x_workspace: str | None = Header(default=None, alias="x-workspace"),
):
    """Find disconnected graph clusters and create bridge edges."""
    ws = workspace or x_workspace or "default"
    result = await reconcile.reconcile(ws)
    return result


ENTITY_VDB_TABLE = "lightrag_vdb_entity_qwen_qwen3_embedding_0_6b_1024d"
RELATION_VDB_TABLE = "lightrag_vdb_relation_qwen_qwen3_embedding_0_6b_1024d"


@router.get("/v1/data/weights")
async def data_weights(
    workspace: str | None = None,
    x_workspace: str | None = Header(default=None, alias="x-workspace"),
):
    """Return blended weights (chunks + degree) for entities and chunk counts for relations."""
    ws = workspace or x_workspace or "default"
    pool = get_pool()

    async with pool.acquire() as conn:
        # Chunk counts per entity
        entity_rows = await conn.fetch(
            f"SELECT entity_name, cardinality(chunk_ids) AS chunks "
            f"FROM {ENTITY_VDB_TABLE} WHERE workspace = $1",
            ws,
        )
        # Relation chunk counts + compute degree per entity
        relation_rows = await conn.fetch(
            f"SELECT source_id, target_id, cardinality(chunk_ids) AS chunks "
            f"FROM {RELATION_VDB_TABLE} WHERE workspace = $1",
            ws,
        )

    # Build degree map from relations
    degree: dict[str, int] = {}
    relations = {}
    for r in relation_rows:
        src, tgt = r["source_id"], r["target_id"]
        degree[src] = degree.get(src, 0) + 1
        degree[tgt] = degree.get(tgt, 0) + 1
        key = f"{src}||{tgt}"
        relations[key] = int(r["chunks"] or 0)

    # Blended entity weight: chunks + degree
    entities = {}
    for r in entity_rows:
        name = r["entity_name"]
        chunks = int(r["chunks"] or 0)
        deg = degree.get(name, 0)
        entities[name] = chunks + deg

    # Edge weight: geometric mean of endpoint entity weights
    for key in relations:
        src, tgt = key.split("||", 1)
        sw = entities.get(src, 1)
        tw = entities.get(tgt, 1)
        relations[key] = round(math.sqrt(sw * tw), 1)

    return {"entities": entities, "relations": relations}
