from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # NATS
    nats_url: str = "nats://nats:4222"

    # PostgreSQL
    pg_host: str = "postgresql"
    pg_port: int = 5432
    pg_user: str = "lightrag"
    pg_password: str = "graphrag-local-2024"
    pg_database: str = "lightrag"

    # Code Preprocessor
    preprocessor_url: str = "http://code-preprocessor:8090"

    # LightRAG (for polling track_status)
    lightrag_url: str = "http://lightrag:9621"

    # Worker config
    max_redeliveries: int = 3
    ack_wait_seconds: int = 600
    batch_size: int = 20
    fetch_batch: int = 1  # NATS messages per worker (1 = max 4 in-flight with 4 replicas)
    indexing_poll_interval: int = 3  # seconds between track_status polls
    indexing_poll_timeout: int = 300  # max seconds to wait for LightRAG processing
