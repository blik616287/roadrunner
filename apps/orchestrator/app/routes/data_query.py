import logging

import httpx
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from ..config import Settings
from ..models import DataQueryRequest, DataQueryResponse, GraphSubgraph, Choice, ChatMessage
from ..services import archival_memory, query_tracker

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
