import logging
import math

import httpx
from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, StreamingResponse

from ..auth import get_current_user
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
    _user: dict = Depends(get_current_user),
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


def _build_sources(data: dict, max_sources: int = 10) -> list[dict]:
    """Build numbered source list from chunks (file-backed sources only)."""
    sources = []
    seen = set()

    for c in data.get("chunks", []):
        if len(sources) >= max_sources:
            break
        content = c.get("content", "")
        file_path = c.get("file_path", "")
        if not file_path or not content or file_path in seen:
            continue
        seen.add(file_path)
        snippet = content[:150].replace("\n", " ").strip()
        if len(content) > 150:
            snippet += "..."
        sources.append({"label": file_path, "snippet": snippet})

    return sources


def _format_context_numbered(data: dict, sources: list[dict]) -> str:
    """Format context with numbered source references for LLM."""
    parts = []

    entities = data.get("entities", [])
    if entities:
        lines = []
        for e in entities[:30]:
            name = e.get("entity_name", "?")
            etype = e.get("entity_type", "?")
            desc = e.get("description", "")
            if desc:
                lines.append(f"- [{etype}] {name}: {desc}")
            else:
                lines.append(f"- [{etype}] {name}")
        parts.append("Entities:\n" + "\n".join(lines))

    relations = data.get("relations", [])
    if relations:
        lines = []
        for r in relations[:20]:
            src = r.get("src_id", "?")
            tgt = r.get("tgt_id", "?")
            desc = r.get("description", "relates to")
            lines.append(f"- {src} -> {tgt}: {desc}")
        parts.append("Relations:\n" + "\n".join(lines))

    if sources:
        lines = []
        for i, s in enumerate(sources, 1):
            lines.append(f"[{i}] {s['label']}: {s['snippet']}")
        parts.append("Sources:\n" + "\n".join(lines))

    return "\n\n".join(parts)


def _format_sources_footer(sources: list[dict]) -> str:
    """Format numbered sources as markdown footer."""
    if not sources:
        return ""
    lines = ["\n\n---\n\n**Sources**\n"]
    for i, s in enumerate(sources, 1):
        lines.append(f"{i}. **{s['label']}** — {s['snippet']}")
    return "\n".join(lines)


@router.post("/v1/data/explain")
async def data_explain(
    request: DataQueryRequest,
    x_workspace: str | None = Header(default=None, alias="x-workspace"),
    _user: dict = Depends(get_current_user),
):
    """Retrieve graph data then stream an LLM explanation via vllm-query."""
    workspace = request.workspace or x_workspace or "default"
    mode = request.mode or "hybrid"

    # Retrieve graph context
    data = await archival_memory.query(
        request.query, workspace, mode=mode, client=_http_client
    )
    sources = _build_sources(data)
    context = _format_context_numbered(data, sources)
    if not context:
        async def empty():
            yield "data: No relevant data found in the knowledge graph.\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(empty(), media_type="text/event-stream")

    source_refs = ""
    if sources:
        numbered = ", ".join(f"[{i}]" for i in range(1, len(sources) + 1))
        source_refs = (
            f" Use inline citations like [1], [2], etc. to reference the numbered sources "
            f"({numbered}) provided in the context. Cite the most relevant source for each claim."
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are a knowledgeable assistant. Based on the knowledge graph data below, "
                "provide a clear, well-structured answer to the user's question. "
                "Reference specific entities, relationships, and code when relevant."
                + source_refs
            ),
        },
        {
            "role": "user",
            "content": f"Knowledge graph context:\n\n{context}\n\nQuestion: {request.query}",
        },
    ]

    footer = _format_sources_footer(sources)

    async def stream_response():
        try:
            async with _http_client.stream(
                "POST",
                f"{_settings.query_llm_url}/chat/completions",
                json={
                    "model": _settings.query_llm_model,
                    "messages": messages,
                    "max_tokens": 2048,
                    "temperature": 0.7,
                    "stream": True,
                },
                timeout=60.0,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"
        except Exception as e:
            logger.error(f"Explain LLM stream failed: {e}")
            yield f"data: [Error: {e}]\n\n"

        # Append sources footer after LLM stream completes
        if footer:
            import json as _json
            chunk = {"choices": [{"delta": {"content": footer}}]}
            yield f"data: {_json.dumps(chunk)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream_response(), media_type="text/event-stream")


@router.post("/v1/data/reconcile")
async def data_reconcile(
    workspace: str | None = None,
    x_workspace: str | None = Header(default=None, alias="x-workspace"),
    _user: dict = Depends(get_current_user),
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
    _user: dict = Depends(get_current_user),
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
