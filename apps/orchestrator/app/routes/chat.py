from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions():
    return JSONResponse(
        status_code=410,
        content={
            "error": {
                "message": "Chat completions removed. Use POST /v1/data/query for graph queries.",
                "type": "gone",
                "code": 410,
            }
        },
    )
