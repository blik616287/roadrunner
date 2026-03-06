"""
Patch LightRAG to support per-request workspace multitenancy and
per-file-type extraction prompts.

Patches applied:
1. Workspace: contextvar-backed `workspace` property on all storage
   classes so each async request gets its own workspace via the
   LIGHTRAG-WORKSPACE header.
2. Filetype-aware extraction: per-request contextvar selects extraction
   prompt (examples + rules + entity types) tuned for the file type
   (code, yaml, config, json, bash, text). Set via LIGHTRAG-FILETYPE header.
3. Max tokens: injects max_tokens into OpenAI LLM calls when
   LLM_MAX_TOKENS env var is set.
4. Typed relationships: patches Neo4J storage to use the first
   extraction keyword as the relationship type instead of hardcoded
   DIRECTED, when TYPED_RELATIONSHIPS=1.

Usage: Set as the Docker entrypoint instead of `lightrag-server`.
"""

import contextvars
import os
import sys

# ── contextvars: per-request workspace + filetype ────────────────────
_current_workspace: contextvars.ContextVar[str] = contextvars.ContextVar(
    "lightrag_workspace", default=os.getenv("WORKSPACE", "default")
)
_current_filetype: contextvars.ContextVar[str] = contextvars.ContextVar(
    "lightrag_filetype", default="text"
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
    """Add ASGI middleware that sets workspace and filetype from request headers."""
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

            ft = request.headers.get("LIGHTRAG-FILETYPE", "").strip().lower()
            if ft:
                _current_filetype.set(ft)
            else:
                _current_filetype.set("text")

            # Auto-initialize pipeline_status for new workspaces
            if ws not in _initialized_workspaces:
                await initialize_pipeline_status(workspace=ws)
                _initialized_workspaces.add(ws)
            return await call_next(request)

    app.add_middleware(WorkspaceMiddleware)


# ── Per-filetype prompt registry ─────────────────────────────────────

_FILETYPE_ENTITY_TYPES = {
    "code": [
        "Class", "Function", "Module", "Package", "API", "Service",
        "Configuration", "Interface", "Variable", "Event", "Concept",
        "Organization", "Data", "Artifact",
    ],
    "yaml": [
        "Service", "Configuration", "Resource", "Deployment", "Container",
        "Volume", "Port", "Environment Variable", "Namespace", "Selector",
        "Label", "Artifact", "Concept",
    ],
    "config": [
        "Configuration", "Setting", "Section", "Service", "Credential",
        "Endpoint", "Feature Flag", "Environment", "Resource", "Concept",
    ],
    "json": [
        "Schema", "Field", "Object", "Array", "Service", "API", "Endpoint",
        "Configuration", "Data", "Resource", "Concept",
    ],
    "bash": [
        "Script", "Command", "Function", "Variable", "Service", "Package",
        "File Path", "Process", "Pipeline", "Configuration", "Concept",
    ],
    "text": [
        "Person", "Organization", "Location", "Event", "Concept",
        "Technology", "Product", "Document", "Process", "Metric", "Artifact",
    ],
}

_FILETYPE_EXAMPLES = {
    "code": (
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
        'PostgreSQL via BlobStore, and forwards processed text to LightRAG '
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
        'entity{tuple_delimiter}Ingest Worker{tuple_delimiter}class{tuple_delimiter}'
        'Worker class subscribing to INGEST stream to process documents.\n'
        'entity{tuple_delimiter}Blob Store{tuple_delimiter}class{tuple_delimiter}'
        'Storage class for fetching document blobs from PostgreSQL.\n'
        'entity{tuple_delimiter}Config.Yaml{tuple_delimiter}configuration{tuple_delimiter}'
        'Configuration file setting worker_replicas=4 and ack_timeout=600.\n'
        'relation{tuple_delimiter}Orchestrator{tuple_delimiter}Ingest Router{tuple_delimiter}'
        'imports{tuple_delimiter}Orchestrator imports IngestRouter to handle ingestion endpoints.\n'
        'relation{tuple_delimiter}Ingest Router{tuple_delimiter}Nats Client{tuple_delimiter}'
        'depends_on{tuple_delimiter}IngestRouter depends on NATSClient to publish ingestion jobs.\n'
        'relation{tuple_delimiter}Ingest Worker{tuple_delimiter}Blob Store{tuple_delimiter}'
        'calls{tuple_delimiter}IngestWorker uses BlobStore to fetch document blobs.\n'
        'relation{tuple_delimiter}Config.Yaml{tuple_delimiter}Ingest Worker{tuple_delimiter}'
        'configures{tuple_delimiter}config.yaml configures IngestWorker with replicas and timeout settings.\n'
        '{completion_delimiter}\n\n'
    ),
    "yaml": (
        '<Entity_types>\n'
        '["Service","Configuration","Resource","Deployment","Container",'
        '"Volume","Port","Environment Variable","Namespace","Selector",'
        '"Label","Artifact","Concept"]\n\n'
        '<Input Text>\n'
        '```yaml\n'
        'apiVersion: apps/v1\n'
        'kind: Deployment\n'
        'metadata:\n'
        '  name: orchestrator\n'
        '  namespace: graphrag\n'
        'spec:\n'
        '  replicas: 1\n'
        '  selector:\n'
        '    matchLabels:\n'
        '      app: orchestrator\n'
        '  template:\n'
        '    spec:\n'
        '      containers:\n'
        '      - name: orchestrator\n'
        '        image: localhost/graphrag-orchestrator:latest\n'
        '        ports:\n'
        '        - containerPort: 8100\n'
        '        env:\n'
        '        - name: PG_HOST\n'
        '          value: postgresql.graphrag.svc\n'
        '        volumeMounts:\n'
        '        - name: config\n'
        '          mountPath: /app/config\n'
        '```\n\n'
        '<Output>\n'
        'entity{tuple_delimiter}Orchestrator Deployment{tuple_delimiter}deployment{tuple_delimiter}'
        'Kubernetes Deployment resource for the orchestrator service with 1 replica.\n'
        'entity{tuple_delimiter}Graphrag Namespace{tuple_delimiter}namespace{tuple_delimiter}'
        'Kubernetes namespace where the orchestrator is deployed.\n'
        'entity{tuple_delimiter}Orchestrator Container{tuple_delimiter}container{tuple_delimiter}'
        'Container running localhost/graphrag-orchestrator:latest image on port 8100.\n'
        'entity{tuple_delimiter}Pg Host{tuple_delimiter}environment variable{tuple_delimiter}'
        'Environment variable pointing to postgresql.graphrag.svc for database connectivity.\n'
        'entity{tuple_delimiter}Config Volume{tuple_delimiter}volume{tuple_delimiter}'
        'Volume mounted at /app/config providing configuration files to the container.\n'
        'relation{tuple_delimiter}Orchestrator Deployment{tuple_delimiter}Graphrag Namespace{tuple_delimiter}'
        'deployed_in{tuple_delimiter}Orchestrator Deployment is deployed in the graphrag namespace.\n'
        'relation{tuple_delimiter}Orchestrator Deployment{tuple_delimiter}Orchestrator Container{tuple_delimiter}'
        'contains{tuple_delimiter}Orchestrator Deployment runs the orchestrator container.\n'
        'relation{tuple_delimiter}Orchestrator Container{tuple_delimiter}Pg Host{tuple_delimiter}'
        'configured_by{tuple_delimiter}Container uses PG_HOST env var for database connection.\n'
        'relation{tuple_delimiter}Orchestrator Container{tuple_delimiter}Config Volume{tuple_delimiter}'
        'mounts{tuple_delimiter}Container mounts the config volume at /app/config.\n'
        '{completion_delimiter}\n\n'
    ),
    "config": (
        '<Entity_types>\n'
        '["Configuration","Setting","Section","Service","Credential",'
        '"Endpoint","Feature Flag","Environment","Resource","Concept"]\n\n'
        '<Input Text>\n'
        '```ini\n'
        '[database]\n'
        'host = postgresql.local\n'
        'port = 5432\n'
        'name = lightrag\n'
        'max_connections = 20\n'
        '\n'
        '[redis]\n'
        'url = redis://redis:6379/0\n'
        'ttl = 7200\n'
        '\n'
        '[features]\n'
        'enable_cache = true\n'
        'burst_mode = false\n'
        '```\n\n'
        '<Output>\n'
        'entity{tuple_delimiter}Database Section{tuple_delimiter}section{tuple_delimiter}'
        'Configuration section defining PostgreSQL connection parameters.\n'
        'entity{tuple_delimiter}Postgresql{tuple_delimiter}service{tuple_delimiter}'
        'PostgreSQL database service at postgresql.local:5432.\n'
        'entity{tuple_delimiter}Redis Section{tuple_delimiter}section{tuple_delimiter}'
        'Configuration section for Redis connection with 7200s TTL.\n'
        'entity{tuple_delimiter}Redis{tuple_delimiter}service{tuple_delimiter}'
        'Redis cache service at redis://redis:6379/0.\n'
        'entity{tuple_delimiter}Enable Cache{tuple_delimiter}feature flag{tuple_delimiter}'
        'Feature flag enabling cache functionality, set to true.\n'
        'entity{tuple_delimiter}Burst Mode{tuple_delimiter}feature flag{tuple_delimiter}'
        'Feature flag for burst mode, set to false.\n'
        'relation{tuple_delimiter}Database Section{tuple_delimiter}Postgresql{tuple_delimiter}'
        'connects_to{tuple_delimiter}Database section configures connection to PostgreSQL service.\n'
        'relation{tuple_delimiter}Redis Section{tuple_delimiter}Redis{tuple_delimiter}'
        'connects_to{tuple_delimiter}Redis section configures connection to Redis service.\n'
        '{completion_delimiter}\n\n'
    ),
    "json": (
        '<Entity_types>\n'
        '["Schema","Field","Object","Array","Service","API","Endpoint",'
        '"Configuration","Data","Resource","Concept"]\n\n'
        '<Input Text>\n'
        '```json\n'
        '{{\n'
        '  "openapi": "3.0.0",\n'
        '  "paths": {{\n'
        '    "/v1/documents/ingest": {{\n'
        '      "post": {{\n'
        '        "summary": "Upload document for ingestion",\n'
        '        "requestBody": {{\n'
        '          "content": {{ "multipart/form-data": {{}} }}\n'
        '        }},\n'
        '        "responses": {{ "200": {{ "description": "Job created" }} }}\n'
        '      }}\n'
        '    }}\n'
        '  }}\n'
        '}}\n'
        '```\n\n'
        '<Output>\n'
        'entity{tuple_delimiter}Document Ingest Endpoint{tuple_delimiter}endpoint{tuple_delimiter}'
        'POST /v1/documents/ingest endpoint for uploading documents for ingestion.\n'
        'entity{tuple_delimiter}Openapi Spec{tuple_delimiter}schema{tuple_delimiter}'
        'OpenAPI 3.0.0 specification defining the API contract.\n'
        'entity{tuple_delimiter}Request Body{tuple_delimiter}object{tuple_delimiter}'
        'Multipart form-data request body for document upload.\n'
        'relation{tuple_delimiter}Openapi Spec{tuple_delimiter}Document Ingest Endpoint{tuple_delimiter}'
        'defines{tuple_delimiter}OpenAPI spec defines the document ingest endpoint.\n'
        'relation{tuple_delimiter}Document Ingest Endpoint{tuple_delimiter}Request Body{tuple_delimiter}'
        'accepts{tuple_delimiter}Endpoint accepts multipart form-data request body.\n'
        '{completion_delimiter}\n\n'
    ),
    "bash": (
        '<Entity_types>\n'
        '["Script","Command","Function","Variable","Service","Package",'
        '"File Path","Process","Pipeline","Configuration","Concept"]\n\n'
        '<Input Text>\n'
        '```bash\n'
        '#!/bin/bash\n'
        'set -euo pipefail\n'
        'DB_HOST="${{DB_HOST:-localhost}}"\n'
        'DB_PORT="${{DB_PORT:-5432}}"\n'
        '\n'
        'echo "Running migrations..."\n'
        'psql -h "$DB_HOST" -p "$DB_PORT" -d lightrag -f /app/migrations/001.sql\n'
        '\n'
        'echo "Starting service..."\n'
        'exec uvicorn app.main:app --host 0.0.0.0 --port 8100\n'
        '```\n\n'
        '<Output>\n'
        'entity{tuple_delimiter}Startup Script{tuple_delimiter}script{tuple_delimiter}'
        'Bash script that runs database migrations then starts the uvicorn service.\n'
        'entity{tuple_delimiter}Db Host{tuple_delimiter}variable{tuple_delimiter}'
        'Environment variable for database host, defaults to localhost.\n'
        'entity{tuple_delimiter}Psql{tuple_delimiter}command{tuple_delimiter}'
        'PostgreSQL CLI tool used to run SQL migration files.\n'
        'entity{tuple_delimiter}Uvicorn{tuple_delimiter}process{tuple_delimiter}'
        'ASGI server process running app.main:app on port 8100.\n'
        'entity{tuple_delimiter}Migrations{tuple_delimiter}file path{tuple_delimiter}'
        'SQL migration file at /app/migrations/001.sql.\n'
        'relation{tuple_delimiter}Startup Script{tuple_delimiter}Psql{tuple_delimiter}'
        'executes{tuple_delimiter}Script runs psql to apply database migrations.\n'
        'relation{tuple_delimiter}Startup Script{tuple_delimiter}Uvicorn{tuple_delimiter}'
        'starts{tuple_delimiter}Script starts uvicorn as the main application process.\n'
        'relation{tuple_delimiter}Psql{tuple_delimiter}Db Host{tuple_delimiter}'
        'uses{tuple_delimiter}psql connects to the database host specified by DB_HOST.\n'
        'relation{tuple_delimiter}Psql{tuple_delimiter}Migrations{tuple_delimiter}'
        'applies{tuple_delimiter}psql executes the SQL migration file.\n'
        '{completion_delimiter}\n\n'
    ),
    "text": (
        '<Entity_types>\n'
        '["Person","Organization","Location","Event","Concept",'
        '"Technology","Product","Document","Process","Metric","Artifact"]\n\n'
        '<Input Text>\n'
        '```\n'
        'The GraphRAG pipeline developed by the infrastructure team processes '
        'documents through three stages: chunking, embedding via Qwen3, and '
        'entity extraction via LightRAG. The system is deployed on NVIDIA DGX '
        'Spark hardware and uses Neo4j for knowledge graph storage. Monthly '
        'ingestion volume averages 50,000 documents with a P95 latency of 2.3 seconds.\n'
        '```\n\n'
        '<Output>\n'
        'entity{tuple_delimiter}Graphrag Pipeline{tuple_delimiter}technology{tuple_delimiter}'
        'Document processing pipeline with chunking, embedding, and entity extraction stages.\n'
        'entity{tuple_delimiter}Infrastructure Team{tuple_delimiter}organization{tuple_delimiter}'
        'Team responsible for developing the GraphRAG pipeline.\n'
        'entity{tuple_delimiter}Qwen3{tuple_delimiter}technology{tuple_delimiter}'
        'Language model used for document embedding in the pipeline.\n'
        'entity{tuple_delimiter}Lightrag{tuple_delimiter}technology{tuple_delimiter}'
        'Framework used for entity extraction from document chunks.\n'
        'entity{tuple_delimiter}Nvidia Dgx Spark{tuple_delimiter}product{tuple_delimiter}'
        'Hardware platform where the system is deployed.\n'
        'entity{tuple_delimiter}Neo4J{tuple_delimiter}technology{tuple_delimiter}'
        'Graph database used for knowledge graph storage.\n'
        'relation{tuple_delimiter}Infrastructure Team{tuple_delimiter}Graphrag Pipeline{tuple_delimiter}'
        'developed{tuple_delimiter}Infrastructure team developed the GraphRAG pipeline.\n'
        'relation{tuple_delimiter}Graphrag Pipeline{tuple_delimiter}Qwen3{tuple_delimiter}'
        'uses{tuple_delimiter}Pipeline uses Qwen3 for document embedding.\n'
        'relation{tuple_delimiter}Graphrag Pipeline{tuple_delimiter}Lightrag{tuple_delimiter}'
        'uses{tuple_delimiter}Pipeline uses LightRAG for entity extraction.\n'
        'relation{tuple_delimiter}Graphrag Pipeline{tuple_delimiter}Nvidia Dgx Spark{tuple_delimiter}'
        'deployed_on{tuple_delimiter}Pipeline is deployed on NVIDIA DGX Spark hardware.\n'
        'relation{tuple_delimiter}Graphrag Pipeline{tuple_delimiter}Neo4J{tuple_delimiter}'
        'stores_in{tuple_delimiter}Pipeline stores knowledge graph data in Neo4j.\n'
        '{completion_delimiter}\n\n'
    ),
}

_FILETYPE_RULES = {
    "code": (
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
    ),
    "yaml": (
        "\n\n---YAML/Infrastructure Rules---\n"
        "9.  **Hierarchy:** Extract the top-level resource (Deployment, Service, ConfigMap) "
        "as the primary entity. Extract nested objects (containers, volumes, ports) only "
        "when they carry meaningful configuration or connect to other resources.\n"
        "10. **Relationship Keywords:** Use infrastructure verbs: `deployed_in`, `contains`, "
        "`mounts`, `exposes`, `configured_by`, `selects`, `depends_on`, `references`.\n"
        "11. **Environment Variables:** Extract env vars only when they reference external "
        "services (database hosts, API URLs). Skip generic vars like LOG_LEVEL.\n"
        "12. **Labels/Selectors:** Do not extract individual labels as entities. Mention them "
        "in relationship descriptions when they link resources together.\n"
    ),
    "config": (
        "\n\n---Configuration File Rules---\n"
        "9.  **Sections as Entities:** Extract configuration sections or groups as entities. "
        "Individual key-value pairs should only be entities when they represent services, "
        "endpoints, or feature flags.\n"
        "10. **Connection Strings:** Extract the target service (database, cache, queue) as "
        "an entity, not the raw connection string itself.\n"
        "11. **Feature Flags:** Extract boolean or enum settings that control behavior as "
        "Feature Flag entities.\n"
        "12. **Defaults:** Mention default values in entity descriptions when they are "
        "meaningful to understanding the configuration.\n"
    ),
    "json": (
        "\n\n---JSON/Schema Rules---\n"
        "9.  **Structure over Values:** Focus on the schema structure (objects, arrays, "
        "fields with special meaning) rather than individual data values.\n"
        "10. **API Definitions:** For OpenAPI/Swagger specs, extract endpoints as entities "
        "and their HTTP methods, request/response schemas as relationships.\n"
        "11. **Nested Objects:** Only extract nested objects as separate entities when they "
        "represent distinct concepts or are referenced from multiple places.\n"
        "12. **Arrays:** Do not extract individual array elements unless they represent "
        "named resources or services.\n"
    ),
    "bash": (
        "\n\n---Shell Script Rules---\n"
        "9.  **Commands as Entities:** Extract significant commands (psql, kubectl, docker, "
        "curl) as entities when they perform meaningful operations. Skip trivial commands "
        "(echo, cd, mkdir).\n"
        "10. **Variables:** Extract environment variables that configure behavior or connect "
        "to services. Skip loop counters and temporary variables.\n"
        "11. **Pipelines:** When commands are piped together, extract the pipeline as a "
        "single entity describing the data transformation.\n"
        "12. **File Paths:** Extract file paths as entities only when they represent "
        "configuration files, scripts, or data that other entities depend on.\n"
    ),
    "text": (
        "\n\n---General Text Rules---\n"
        "9.  **Concrete over Abstract:** Prefer extracting concrete, named entities over "
        "abstract concepts. Only extract a concept if it is central to the text.\n"
        "10. **Quantitative Data:** When the text includes metrics, statistics, or "
        "measurements, extract the metric as an entity with the value in the description.\n"
        "11. **Temporal References:** Extract events with dates or timeframes as Event "
        "entities with the temporal context in the description.\n"
        "12. **No Orphan Entities:** Every entity you extract MUST participate in "
        "at least one relationship.\n"
    ),
}


def _detect_filetype_from_chunks(chunks: dict) -> str:
    """Detect filetype from <!-- filetype:xxx --> marker in chunk content."""
    import re
    pattern = re.compile(r'<!--\s*filetype:(\w+)\s*-->')
    for chunk_data in chunks.values():
        content = chunk_data.get("content", "") if isinstance(chunk_data, dict) else ""
        m = pattern.search(content[:200])
        if m:
            return m.group(1)
    return "text"


def _patch_filetype_prompts():
    """Install per-file-type prompt swapping based on in-document markers.

    The code-preprocessor prepends <!-- filetype:xxx --> to each document.
    This patch reads the marker from chunk content at extraction time and
    swaps the extraction prompt, examples, and entity types accordingly.
    """
    if os.getenv("FILETYPE_PROMPTS", "0") != "1":
        return

    import logging
    from lightrag import LightRAG
    from lightrag.prompt import PROMPTS

    logger = logging.getLogger("lightrag.filetype")

    # Save the base prompts before any modification
    _base_system_prompt = PROMPTS["entity_extraction_system_prompt"]
    _base_examples = list(PROMPTS["entity_extraction_examples"])

    _orig_process = LightRAG._process_extract_entities

    async def _filetype_process(self, chunks, *args, **kwargs):
        ft = _detect_filetype_from_chunks(chunks)
        if ft not in _FILETYPE_EXAMPLES:
            ft = "text"

        # Swap prompts before extraction reads them
        old_examples = PROMPTS["entity_extraction_examples"]
        old_system = PROMPTS["entity_extraction_system_prompt"]

        PROMPTS["entity_extraction_examples"] = [_FILETYPE_EXAMPLES[ft]]
        PROMPTS["entity_extraction_system_prompt"] = (
            _base_system_prompt + _FILETYPE_RULES.get(ft, "")
        )

        # Swap entity types in the config that gets passed to extract_entities
        old_entity_types = None
        if hasattr(self, 'addon_params') and isinstance(self.addon_params, dict):
            old_entity_types = self.addon_params.get("entity_types")
            self.addon_params["entity_types"] = _FILETYPE_ENTITY_TYPES[ft]

        logger.info(f"[filetype] Using '{ft}' extraction prompt")
        try:
            return await _orig_process(self, chunks, *args, **kwargs)
        finally:
            PROMPTS["entity_extraction_examples"] = old_examples
            PROMPTS["entity_extraction_system_prompt"] = old_system
            if old_entity_types is not None and hasattr(self, 'addon_params'):
                self.addon_params["entity_types"] = old_entity_types

    LightRAG._process_extract_entities = _filetype_process
    logger.info("[filetype] Per-file-type prompt swapping installed")


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
        first_kw = keywords.split(",")[0].strip() if keywords else ""
        if first_kw:
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

    _orig_get_edges = Neo4JStorage.get_edges_batch

    async def _typed_get_edges(self, pairs):
        workspace_label = self._get_workspace_label()
        async with self._driver.session(
            database=self._DATABASE, default_access_mode="READ"
        ) as session:
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

    # Apply extraction optimizations — order matters:
    # filetype prompts wraps extract_entities, max_tokens wraps openai fn
    _patch_filetype_prompts()
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
