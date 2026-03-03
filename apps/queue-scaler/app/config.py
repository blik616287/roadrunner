from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # NATS monitoring endpoint
    nats_monitor_url: str = "http://nats:8222"

    # Orchestrator (for query activity check)
    orchestrator_url: str = "http://orchestrator:8100"

    # Kubernetes
    k8s_namespace: str = "graphrag"

    # Reranker deployment to scale
    reranker_deployment: str = "vllm-rerank"
    reranker_normal_replicas: int = 1
    reranker_burst_replicas: int = 0

    # Polling and hysteresis
    poll_interval: int = 15
    burst_threshold: int = 10
    hysteresis_up: int = 3
    hysteresis_down: int = 5
