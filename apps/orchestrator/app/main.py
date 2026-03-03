import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from .config import Settings
from .db import init_pool, close_pool
from .services import (
    working_memory,
    embedding,
    archival_memory,
    query_tracker,
    nats_client,
)
from .routes import chat, models_list, documents, sessions, jobs, workspaces, data_query, internal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("orchestrator")

settings = Settings()

_http_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _http_client
    logger.info("Starting GraphRAG Orchestrator...")

    # Initialize services
    embedding.init_embedding(settings.embed_url, settings.embed_model)
    archival_memory.init_archival(settings.lightrag_url)

    # Initialize data stores
    await init_pool(settings)
    await working_memory.init_redis(settings.redis_url)
    await nats_client.init_nats(settings.nats_url)

    # Initialize query tracker (shares Redis client with working memory)
    query_tracker.init_tracker(
        working_memory.get_client(),
        settings.query_activity_key,
        settings.query_activity_ttl,
    )

    # Shared HTTP client
    _http_client = httpx.AsyncClient(timeout=300.0)

    # Initialize route modules
    data_query.init_data_query(settings, _http_client)
    documents.init_documents(settings)
    workspaces.init_workspaces(settings)

    logger.info("GraphRAG Orchestrator ready")
    yield

    # Shutdown
    logger.info("Shutting down GraphRAG Orchestrator...")
    await nats_client.close_nats()
    await _http_client.aclose()
    await working_memory.close_redis()
    await close_pool()


app = FastAPI(
    title="GraphRAG Orchestrator",
    version="0.2.0",
    description="GraphRAG ingestion pipeline with data query API",
    lifespan=lifespan,
)

app.include_router(chat.router)
app.include_router(models_list.router)
app.include_router(documents.router)
app.include_router(sessions.router)
app.include_router(jobs.router)
app.include_router(workspaces.router)
app.include_router(data_query.router)
app.include_router(internal.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
