from fastapi import APIRouter

from ..services import query_tracker

router = APIRouter()


@router.get("/internal/query-activity")
async def get_query_activity():
    return await query_tracker.get_activity()
