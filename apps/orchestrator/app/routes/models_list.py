from fastapi import APIRouter, Depends

from ..auth import get_current_user
from ..models import ModelInfo, ModelListResponse
from ..services.router import list_models

router = APIRouter()


@router.get("/v1/models")
async def get_models(_user: dict = Depends(get_current_user)):
    names = list_models()
    return ModelListResponse(
        data=[ModelInfo(id=name) for name in names],
    )
