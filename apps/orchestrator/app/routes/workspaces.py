import logging

import httpx
from fastapi import APIRouter, Depends, Header

from ..auth import get_current_user
from ..config import Settings
from ..db import get_pool

logger = logging.getLogger("orchestrator.workspaces")

router = APIRouter()
_settings: Settings | None = None


def init_workspaces(settings: Settings):
    global _settings
    _settings = settings


@router.delete("/v1/workspaces/{workspace}")
async def delete_workspace(workspace: str, _user: dict = Depends(get_current_user)):
    """Delete all orchestrator documents, jobs, and LightRAG data for a workspace."""
    pool = get_pool()
    deleted_jobs = await pool.execute(
        "DELETE FROM orchestrator_ingest_jobs WHERE workspace = $1", workspace
    )
    deleted_docs = await pool.execute(
        "DELETE FROM orchestrator_documents WHERE workspace = $1", workspace
    )
    jobs_count = int(deleted_jobs.split()[-1]) if deleted_jobs else 0
    docs_count = int(deleted_docs.split()[-1]) if deleted_docs else 0

    # Clear LightRAG workspace
    lr_status = "skipped"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.delete(
                f"{_settings.lightrag_url}/documents",
                headers={"LIGHTRAG-WORKSPACE": workspace},
            )
            lr_status = "ok" if resp.status_code == 200 else f"error:{resp.status_code}"
    except Exception as e:
        lr_status = f"error:{e}"
        logger.warning(f"Failed to clear LightRAG workspace '{workspace}': {e}")

    logger.info(f"Deleted workspace '{workspace}': {docs_count} docs, {jobs_count} jobs, lightrag={lr_status}")
    return {
        "deleted_workspace": workspace,
        "documents_deleted": docs_count,
        "jobs_deleted": jobs_count,
        "lightrag": lr_status,
    }


@router.get("/v1/workspaces")
async def list_workspaces(_user: dict = Depends(get_current_user)):
    pool = get_pool()

    # Get workspace list + doc counts from orchestrator
    ws_rows = await pool.fetch("""
        SELECT workspace, COUNT(*) AS doc_count, MAX(created_at) AS last_activity
        FROM orchestrator_documents
        GROUP BY workspace
        ORDER BY last_activity DESC
    """)

    # Get job counts from orchestrator_ingest_jobs (single source of truth)
    job_rows = await pool.fetch("""
        SELECT
            workspace,
            COUNT(*) FILTER (WHERE status = 'queued') AS queued,
            COUNT(*) FILTER (WHERE status IN ('started', 'indexing', 'processing')) AS processing,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed,
            COUNT(*) FILTER (WHERE status = 'failed') AS failed
        FROM orchestrator_ingest_jobs
        GROUP BY workspace
    """)
    job_map = {r["workspace"]: r for r in job_rows}

    workspaces = []
    for r in ws_rows:
        ws = r["workspace"]
        jm = job_map.get(ws)
        workspaces.append({
            "name": ws,
            "doc_count": r["doc_count"],
            "jobs": {
                "queued": jm["queued"] if jm else 0,
                "processing": jm["processing"] if jm else 0,
                "completed": jm["completed"] if jm else 0,
                "failed": jm["failed"] if jm else 0,
            },
            "last_activity": r["last_activity"].isoformat() if r["last_activity"] else None,
        })

    return {"workspaces": workspaces}
