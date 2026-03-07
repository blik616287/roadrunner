import asyncpg

from .config import Settings

_pool: asyncpg.Pool | None = None

_SCHEMA_TEMPLATE = """
CREATE TABLE IF NOT EXISTS orchestrator_sessions (
    id TEXT PRIMARY KEY,
    workspace TEXT NOT NULL DEFAULT 'default',
    model TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    summary TEXT,
    summary_vector vector({embed_dim})
);

CREATE TABLE IF NOT EXISTS orchestrator_messages (
    id BIGSERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES orchestrator_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS orchestrator_documents (
    id TEXT PRIMARY KEY,
    workspace TEXT NOT NULL DEFAULT 'default',
    file_name TEXT NOT NULL,
    content_type TEXT,
    compressed_blob BYTEA NOT NULL,
    original_size BIGINT NOT NULL,
    content_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB DEFAULT '{{}}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_orchestrator_sessions_workspace
    ON orchestrator_sessions(workspace);
CREATE INDEX IF NOT EXISTS idx_orchestrator_messages_session
    ON orchestrator_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_orchestrator_documents_workspace
    ON orchestrator_documents(workspace);
CREATE INDEX IF NOT EXISTS idx_orchestrator_sessions_summary_vector
    ON orchestrator_sessions
    USING hnsw (summary_vector vector_cosine_ops);

CREATE TABLE IF NOT EXISTS orchestrator_ingest_jobs (
    id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES orchestrator_documents(id),
    workspace TEXT NOT NULL DEFAULT 'default',
    job_type TEXT NOT NULL DEFAULT 'document',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error TEXT,
    result JSONB DEFAULT '{{}}'::jsonb,
    attempts INT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status
    ON orchestrator_ingest_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_workspace
    ON orchestrator_ingest_jobs(workspace);
CREATE INDEX IF NOT EXISTS idx_ingest_jobs_doc_id
    ON orchestrator_ingest_jobs(doc_id);

CREATE TABLE IF NOT EXISTS auth_users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT,
    picture TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS auth_api_keys (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    rotation_days INT,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_auth_api_keys_user
    ON auth_api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_api_keys_hash
    ON auth_api_keys(key_hash);
"""


def _encode_vector(v: list[float]) -> str:
    return "[" + ",".join(str(x) for x in v) + "]"


def _decode_vector(v: str) -> list[float]:
    return [float(x) for x in v.strip("[]").split(",")]


async def _init_connection(conn: asyncpg.Connection):
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    await conn.set_type_codec(
        "vector",
        encoder=_encode_vector,
        decoder=_decode_vector,
        schema="public",
        format="text",
    )


async def _migrate_vector_dim(conn: asyncpg.Connection, embed_dim: int):
    """Detect vector dimension mismatch and recreate column if needed."""
    row = await conn.fetchrow("""
        SELECT atttypmod FROM pg_attribute
        WHERE attrelid = 'orchestrator_sessions'::regclass
          AND attname = 'summary_vector'
    """)
    if row is None:
        return  # column doesn't exist yet, CREATE TABLE will handle it
    current_dim = row["atttypmod"]
    if current_dim != embed_dim and current_dim > 0:
        await conn.execute("ALTER TABLE orchestrator_sessions DROP COLUMN summary_vector")
        await conn.execute(
            f"ALTER TABLE orchestrator_sessions ADD COLUMN summary_vector vector({embed_dim})"
        )
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_orchestrator_sessions_summary_vector
                ON orchestrator_sessions
                USING hnsw (summary_vector vector_cosine_ops)
        """)


async def _migrate_documents_hash(conn: asyncpg.Connection):
    """Add content_hash column and unique index for content-based dedup."""
    # Add column if missing
    col = await conn.fetchval("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'orchestrator_documents' AND column_name = 'content_hash'
    """)
    if not col:
        await conn.execute(
            "ALTER TABLE orchestrator_documents ADD COLUMN content_hash TEXT"
        )
    # Drop old file_name unique index if it exists
    old_idx = await conn.fetchval("""
        SELECT 1 FROM pg_indexes
        WHERE indexname = 'idx_orchestrator_documents_workspace_file'
    """)
    if old_idx:
        await conn.execute("DROP INDEX idx_orchestrator_documents_workspace_file")
    # Create hash index
    await conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_orchestrator_documents_workspace_hash
            ON orchestrator_documents(workspace, content_hash)
    """)


async def init_pool(settings: Settings) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(
        host=settings.pg_host,
        port=settings.pg_port,
        user=settings.pg_user,
        password=settings.pg_password,
        database=settings.pg_database,
        min_size=2,
        max_size=10,
        init=_init_connection,
    )
    schema_sql = _SCHEMA_TEMPLATE.format(embed_dim=settings.embed_dim)
    async with _pool.acquire() as conn:
        await conn.execute(schema_sql)
        await _migrate_vector_dim(conn, settings.embed_dim)
        await _migrate_documents_hash(conn)
    return _pool


def get_pool() -> asyncpg.Pool:
    assert _pool is not None, "Database pool not initialized"
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
