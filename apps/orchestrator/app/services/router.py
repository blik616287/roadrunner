from ..config import Settings


def init_routes(settings: Settings):
    pass


def resolve(model_name: str) -> tuple[str, str]:
    raise ValueError(
        "Chat completions removed. Use POST /v1/data/query for graph queries."
    )


def list_models() -> list[str]:
    return []
