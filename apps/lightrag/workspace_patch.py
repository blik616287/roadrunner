"""
Patch LightRAG to support per-request workspace multitenancy and
code-optimized extraction.

Patches applied:
1. Workspace: contextvar-backed `workspace` property on all storage
   classes so each async request gets its own workspace via the
   LIGHTRAG-WORKSPACE header.
2. Extraction prompt: replaces generic examples with a concise
   code-focused example when CODE_EXTRACTION_PROMPT=1.
3. Max tokens: injects max_tokens into OpenAI LLM calls when
   LLM_MAX_TOKENS env var is set.
4. Entity types: overrides default entity types with code-relevant
   types when CODE_EXTRACTION_PROMPT=1.
5. Typed relationships: patches Neo4J storage to use the first
   extraction keyword as the relationship type instead of hardcoded
   DIRECTED, when TYPED_RELATIONSHIPS=1.

Usage: Set as the Docker entrypoint instead of `lightrag-server`.
"""

import contextvars
import os
import sys

# ── contextvar: per-request workspace ───────────────────────────────
_current_workspace: contextvars.ContextVar[str] = contextvars.ContextVar(
    "lightrag_workspace", default=os.getenv("WORKSPACE", "default")
)


class _WorkspaceDescriptor:
    """Data descriptor that delegates to the contextvar."""

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return _current_workspace.get()

    def __set__(self, obj, value):
        _current_workspace.set(value)


def _patch_classes():
    """Install the workspace descriptor on LightRAG + all storage classes."""
    from lightrag import LightRAG
    from lightrag.kg.postgres_impl import (
        PGKVStorage,
        PGDocStatusStorage,
        PGVectorStorage,
    )
    from lightrag.kg.neo4j_impl import Neo4JStorage

    descriptor = _WorkspaceDescriptor()
    for cls in (LightRAG, PGKVStorage, PGDocStatusStorage, PGVectorStorage, Neo4JStorage):
        cls.workspace = descriptor


def _add_middleware(app):
    """Add ASGI middleware that sets workspace from request header."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from lightrag.kg.shared_storage import initialize_pipeline_status

    _initialized_workspaces: set[str] = set()

    class WorkspaceMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            ws = request.headers.get("LIGHTRAG-WORKSPACE", "").strip()
            if not ws:
                ws = os.getenv("WORKSPACE", "default")
            _current_workspace.set(ws)
            # Auto-initialize pipeline_status for new workspaces
            if ws not in _initialized_workspaces:
                await initialize_pipeline_status(workspace=ws)
                _initialized_workspaces.add(ws)
            return await call_next(request)

    app.add_middleware(WorkspaceMiddleware)


def _patch_extraction_prompt():
    """Replace the default extraction prompt with a concise, code-focused version.

    Activated when CODE_EXTRACTION_PROMPT=1 env var is set.
    Replaces:
    - entity_extraction_examples: 3 generic examples → 1 code example
    - ENTITY_TYPES env var: generic types → code-relevant types
    """
    if os.getenv("CODE_EXTRACTION_PROMPT", "0") != "1":
        return

    from lightrag.prompt import PROMPTS

    code_example = (
        '<Entity_types>\n'
        '["Class","Function","Module","Package","API","Service","Configuration",'
        '"Interface","Variable","Event","Concept","Organization","Data","Artifact"]\n\n'
        '<Input Text>\n'
        '```\n'
        'The FastAPI application in orchestrator/main.py imports IngestRouter from '
        'orchestrator.routers.ingest to handle document ingestion via POST '
        '/v1/documents/ingest. IngestRouter depends on NATSClient to publish '
        'messages to the INGEST JetStream stream. The IngestWorker class in '
        'ingest_worker/worker.py subscribes to this stream, fetches blobs from '
        'PostgreSQL via BlobStore, sends code files to the CodePreprocessor service '
        'at code-preprocessor:8090/ingest, and forwards processed text to LightRAG '
        'for entity extraction. Configuration is loaded from config.yaml which sets '
        'worker_replicas=4 and ack_timeout=600.\n'
        '```\n\n'
        '<Output>\n'
        'entity{tuple_delimiter}Orchestrator{tuple_delimiter}service{tuple_delimiter}'
        'FastAPI application serving as the API gateway for document ingestion.\n'
        'entity{tuple_delimiter}Ingest Router{tuple_delimiter}module{tuple_delimiter}'
        'Router module handling POST /v1/documents/ingest endpoint.\n'
        'entity{tuple_delimiter}Nats Client{tuple_delimiter}class{tuple_delimiter}'
        'Client class for publishing messages to NATS JetStream.\n'
        'entity{tuple_delimiter}Ingest Stream{tuple_delimiter}data{tuple_delimiter}'
        'NATS JetStream stream for ingestion job messages.\n'
        'entity{tuple_delimiter}Ingest Worker{tuple_delimiter}class{tuple_delimiter}'
        'Worker class subscribing to INGEST stream to process documents.\n'
        'entity{tuple_delimiter}Blob Store{tuple_delimiter}class{tuple_delimiter}'
        'Storage class for fetching document blobs from PostgreSQL.\n'
        'entity{tuple_delimiter}Code Preprocessor{tuple_delimiter}service{tuple_delimiter}'
        'Service at code-preprocessor:8090 that parses code files via tree-sitter.\n'
        'entity{tuple_delimiter}Lightrag{tuple_delimiter}service{tuple_delimiter}'
        'GraphRAG service performing entity extraction and knowledge graph construction.\n'
        'entity{tuple_delimiter}Config.Yaml{tuple_delimiter}configuration{tuple_delimiter}'
        'Configuration file setting worker_replicas=4 and ack_timeout=600.\n'
        'relation{tuple_delimiter}Orchestrator{tuple_delimiter}Ingest Router{tuple_delimiter}'
        'imports{tuple_delimiter}Orchestrator imports IngestRouter to handle ingestion endpoints.\n'
        'relation{tuple_delimiter}Ingest Router{tuple_delimiter}Nats Client{tuple_delimiter}'
        'depends_on{tuple_delimiter}IngestRouter depends on NATSClient to publish ingestion jobs.\n'
        'relation{tuple_delimiter}Nats Client{tuple_delimiter}Ingest Stream{tuple_delimiter}'
        'publishes_to{tuple_delimiter}NATSClient publishes messages to the INGEST JetStream stream.\n'
        'relation{tuple_delimiter}Ingest Worker{tuple_delimiter}Ingest Stream{tuple_delimiter}'
        'subscribes_to{tuple_delimiter}IngestWorker subscribes to INGEST stream to receive jobs.\n'
        'relation{tuple_delimiter}Ingest Worker{tuple_delimiter}Blob Store{tuple_delimiter}'
        'calls{tuple_delimiter}IngestWorker uses BlobStore to fetch document blobs.\n'
        'relation{tuple_delimiter}Ingest Worker{tuple_delimiter}Code Preprocessor{tuple_delimiter}'
        'calls{tuple_delimiter}IngestWorker sends code files to CodePreprocessor for parsing.\n'
        'relation{tuple_delimiter}Ingest Worker{tuple_delimiter}Lightrag{tuple_delimiter}'
        'calls{tuple_delimiter}IngestWorker forwards processed text to LightRAG for entity extraction.\n'
        'relation{tuple_delimiter}Config.Yaml{tuple_delimiter}Ingest Worker{tuple_delimiter}'
        'configures{tuple_delimiter}config.yaml configures IngestWorker with replicas and timeout settings.\n'
        '{completion_delimiter}\n\n'
    )

    PROMPTS["entity_extraction_examples"] = [code_example]

    # Append code-specific rules to the system prompt
    code_rules = (
        "\n\n---Code-Specific Rules---\n"
        "9.  **Relationship Keywords:** Use a SINGLE precise verb as the keyword "
        "(e.g. `imports`, `calls`, `extends`, `implements`, `depends_on`, "
        "`configures`, `contains`, `publishes_to`, `subscribes_to`, `returns`, "
        "`instantiates`, `inherits`). Do NOT combine multiple verbs.\n"
        "10. **No Orphan Entities:** Every entity you extract MUST participate in "
        "at least one relationship. If you cannot identify a relationship for an "
        "entity, do not extract that entity.\n"
        "11. **Dependency Lists:** For dependency/requirements files, extract only "
        "the project or module that declares the dependencies, not each individual "
        "package version line. For example, from a requirements.txt, extract the "
        "parent module and a single `depends_on` relationship to key libraries.\n"
        "12. **Standard Library:** Do not extract Python/JS standard library modules "
        "(os, sys, io, pathlib, json, etc.) as standalone entities. Only mention them "
        "in relationship descriptions if relevant.\n"
    )
    PROMPTS["entity_extraction_system_prompt"] += code_rules

    # Override entity types via env var so LightRAG picks them up
    os.environ["ENTITY_TYPES"] = (
        '["Class","Function","Module","Package","API","Service",'
        '"Configuration","Interface","Variable","Event","Concept",'
        '"Organization","Data","Artifact"]'
    )


def _patch_llm_max_tokens():
    """Inject max_tokens into OpenAI LLM calls to cap generation length.

    Activated when LLM_MAX_TOKENS env var is set to a positive integer.
    Wraps openai_complete_if_cache to inject max_tokens into kwargs
    before forwarding to the OpenAI API.
    """
    max_tokens = int(os.getenv("LLM_MAX_TOKENS", "0"))
    if max_tokens <= 0:
        return

    import lightrag.llm.openai as oai
    _orig_fn = oai.openai_complete_if_cache

    async def _wrapped(*args, **kwargs):
        kwargs.setdefault("max_tokens", max_tokens)
        return await _orig_fn(*args, **kwargs)

    oai.openai_complete_if_cache = _wrapped


def _patch_neo4j_typed_relationships():
    """Patch Neo4J storage to use extraction keywords as relationship types.

    Activated when TYPED_RELATIONSHIPS=1 env var is set.
    Instead of hardcoded DIRECTED, uses the first keyword from edge_data
    as the Neo4j relationship type (sanitized to uppercase with underscores).
    """
    if os.getenv("TYPED_RELATIONSHIPS", "0") != "1":
        return

    import re
    from lightrag.kg.neo4j_impl import Neo4JStorage

    _orig_upsert_edge = Neo4JStorage.upsert_edge

    async def _typed_upsert_edge(self, source_node_id, target_node_id, edge_data):
        keywords = edge_data.get("keywords", "")
        # Extract first keyword and sanitize for Neo4j rel type
        first_kw = keywords.split(",")[0].strip() if keywords else ""
        if first_kw:
            # Sanitize: uppercase, underscores, letters/digits only
            rel_type = re.sub(r'[^A-Z0-9_]', '_', first_kw.upper())
            rel_type = re.sub(r'_+', '_', rel_type).strip('_')
            if not rel_type or not rel_type[0].isalpha():
                rel_type = "RELATED"
        else:
            rel_type = "RELATED"

        try:
            edge_properties = edge_data
            async with self._driver.session(database=self._DATABASE) as session:

                async def execute_upsert(tx):
                    workspace_label = self._get_workspace_label()
                    query = f"""
                    MATCH (source:`{workspace_label}` {{entity_id: $source_entity_id}})
                    WITH source
                    MATCH (target:`{workspace_label}` {{entity_id: $target_entity_id}})
                    MERGE (source)-[r:`{rel_type}`]-(target)
                    SET r += $properties
                    RETURN r
                    """
                    result = await tx.run(
                        query,
                        source_entity_id=source_node_id,
                        target_entity_id=target_node_id,
                        properties=edge_properties,
                    )
                    try:
                        await result.fetch(2)
                    finally:
                        await result.consume()

                await session.execute_write(execute_upsert)
        except Exception as e:
            import logging
            logging.getLogger("lightrag").error(
                f"[{self.workspace}] Error during typed edge upsert: {e}"
            )
            raise

    Neo4JStorage.upsert_edge = _typed_upsert_edge

    # Also patch the edge read query to match any relationship type
    _orig_get_edges = Neo4JStorage.get_edges_batch

    async def _typed_get_edges(self, pairs):
        workspace_label = self._get_workspace_label()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
            # Match any relationship type instead of just DIRECTED
            query = f"""
            UNWIND $pairs AS pair
            MATCH (start:`{workspace_label}` {{entity_id: pair.src}})-[r]-(end:`{workspace_label}` {{entity_id: pair.tgt}})
            RETURN pair.src AS src_id, pair.tgt AS tgt_id, collect(properties(r)) AS edges
            """
            result = await session.run(query, pairs=pairs)
            edges_dict = {}
            async for record in result:
                src = record["src_id"]
                tgt = record["tgt_id"]
                edges = record["edges"]
                if edges and len(edges) > 0:
                    edge_props = edges[0]
                    for key, default in {
                        "weight": 1.0,
                        "source_id": None,
                        "description": None,
                        "keywords": None,
                    }.items():
                        if key not in edge_props:
                            edge_props[key] = default
                    edges_dict[(src, tgt)] = edge_props
                else:
                    edges_dict[(src, tgt)] = {
                        "weight": 1.0,
                        "source_id": None,
                        "description": None,
                        "keywords": None,
                    }
            await result.consume()
            return edges_dict

    Neo4JStorage.get_edges_batch = _typed_get_edges


def _patch_pipelined_embedding():
    """Overlap chunk embedding with entity extraction for faster ingestion.

    Activated when PIPELINED_EMBEDDING=1 env var is set.

    Problem: LightRAG's process_document runs embedding ALL chunks to completion
    (Stage 1) before starting entity extraction (Stage 2). But extraction only
    needs chunk text, not embeddings — they are independent operations.

    Solution: Make PGVectorStorage.upsert (chunks namespace) return immediately,
    deferring the actual embed+store work to a background task. Then make
    _process_extract_entities await that deferred task concurrently with extraction.

    Result: Embedding and extraction run in parallel. Total time is
    max(embed_time, extract_time) instead of embed_time + extract_time.
    """
    if os.getenv("PIPELINED_EMBEDDING", "0") != "1":
        return

    import asyncio
    import logging
    from lightrag import LightRAG
    from lightrag.kg.postgres_impl import PGVectorStorage
    from lightrag.namespace import NameSpace, is_namespace

    logger = logging.getLogger("lightrag.pipeline")

    _orig_upsert = PGVectorStorage.upsert
    _orig_extract = LightRAG._process_extract_entities

    async def _deferred_upsert(self, data):
        """For chunks namespace: start embed+store as background task, return immediately."""
        if not is_namespace(self.namespace, NameSpace.VECTOR_STORE_CHUNKS):
            return await _orig_upsert(self, data)

        if not data:
            return

        chunk_key = frozenset(data.keys())

        async def _do_embed_and_store():
            try:
                await _orig_upsert(self, data)
                logger.info(f"[pipeline] Deferred embedding completed for {len(data)} chunks")
            except Exception as e:
                logger.error(f"[pipeline] Deferred embedding failed: {e}")
                raise

        if not hasattr(self, '_embedding_futures'):
            self._embedding_futures = {}

        self._embedding_futures[chunk_key] = asyncio.create_task(_do_embed_and_store())
        logger.info(f"[pipeline] Deferred {len(data)} chunks, extraction can begin")

    async def _pipelined_extract(self, chunks, pipeline_status=None, pipeline_status_lock=None):
        """Run extraction concurrently with deferred embedding."""
        chunk_key = frozenset(chunks.keys())

        embedding_future = None
        futures_dict = getattr(self.chunks_vdb, '_embedding_futures', None)
        if futures_dict and chunk_key in futures_dict:
            embedding_future = futures_dict.pop(chunk_key)

        if embedding_future is not None:
            logger.info(f"[pipeline] Pipelined: {len(chunks)} chunks extracting alongside embedding")
            extract_task = asyncio.create_task(
                _orig_extract(self, chunks, pipeline_status, pipeline_status_lock)
            )
            try:
                results = await asyncio.gather(extract_task, embedding_future)
                return results[0]
            except Exception:
                for t in [extract_task, embedding_future]:
                    if t and not t.done():
                        t.cancel()
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass
                raise
        else:
            return await _orig_extract(self, chunks, pipeline_status, pipeline_status_lock)

    PGVectorStorage.upsert = _deferred_upsert
    LightRAG._process_extract_entities = _pipelined_extract
    logger.info("[pipeline] Pipelined embedding+extraction patch installed")


def main():
    # Patch classes BEFORE the app creates any instances
    _patch_classes()

    # Apply extraction optimizations
    _patch_extraction_prompt()
    _patch_llm_max_tokens()
    _patch_neo4j_typed_relationships()
    _patch_pipelined_embedding()

    from lightrag.api.lightrag_server import create_app
    from lightrag.api.config import parse_args
    import uvicorn

    args = parse_args()
    app = create_app(args)

    # Add workspace middleware
    _add_middleware(app)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
