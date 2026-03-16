import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user
from ..db import get_pool
from ..models import JobStatusResponse
from ..services.nats_client import publish_ingest_job

_settings = None


def init_jobs(settings):
    global _settings
    _settings = settings


def _parse_result(raw) -> dict | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        return json.loads(raw)
    return None

logger = logging.getLogger("orchestrator.jobs")

router = APIRouter()


async def _reconcile_indexing_jobs(workspace: str | None = None):
    """Check LightRAG for jobs stuck at 'indexing' and auto-complete them.

    The ingest worker marks jobs 'indexing' after sending to the preprocessor.
    LightRAG's streaming pipeline processes them independently. This function
    queries LightRAG track_status to reconcile the orchestrator's job status.
    """
    pool = get_pool()
    if workspace:
        rows = await pool.fetch(
            """SELECT id, workspace, result FROM orchestrator_ingest_jobs
               WHERE status = 'indexing' AND workspace = $1""",
            workspace,
        )
    else:
        rows = await pool.fetch(
            "SELECT id, workspace, result FROM orchestrator_ingest_jobs WHERE status = 'indexing'"
        )

    if not rows:
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        for row in rows:
            result = _parse_result(row["result"]) or {}
            track_ids = result.get("track_ids", [])
            if not track_ids:
                # No track_ids means nothing was sent — mark completed
                await pool.execute(
                    """UPDATE orchestrator_ingest_jobs
                       SET status = 'completed', completed_at = now()
                       WHERE id = $1""",
                    row["id"],
                )
                continue

            # Check each track_id against LightRAG
            all_done = True
            any_failed = False
            for tid in track_ids:
                try:
                    resp = await client.get(
                        f"{_settings.lightrag_url}/documents/track_status/{tid}",
                        headers={"LIGHTRAG-WORKSPACE": row["workspace"]},
                    )
                    if resp.status_code != 200:
                        all_done = False
                        continue
                    summary = resp.json().get("status_summary", {})
                    total = sum(summary.values())
                    processed = summary.get("processed", 0)
                    failed = summary.get("failed", 0)
                    if total == 0 or (processed + failed) < total:
                        all_done = False
                    if failed > 0:
                        any_failed = True
                except Exception:
                    all_done = False

            if all_done:
                new_status = "failed" if any_failed else "completed"
                await pool.execute(
                    """UPDATE orchestrator_ingest_jobs
                       SET status = $2, completed_at = now(), result = $3::jsonb,
                           error = CASE WHEN $4 THEN 'LightRAG extraction failed' ELSE NULL END
                       WHERE id = $1""",
                    row["id"], new_status, json.dumps(result), any_failed,
                )
                logger.info(f"Reconciled job {row['id']} → {new_status}")


@router.get("/v1/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, _user: dict = Depends(get_current_user)):
    pool = get_pool()
    row = await pool.fetchrow(
        """SELECT j.*, d.file_name FROM orchestrator_ingest_jobs j
           LEFT JOIN orchestrator_documents d ON j.doc_id = d.id
           WHERE j.id = $1""", job_id
    )
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")

    return JobStatusResponse(
        job_id=row["id"],
        doc_id=row["doc_id"],
        file_name=row["file_name"],
        workspace=row["workspace"],
        job_type=row["job_type"],
        status=row["status"],
        created_at=row["created_at"].isoformat(),
        started_at=row["started_at"].isoformat() if row["started_at"] else None,
        completed_at=row["completed_at"].isoformat() if row["completed_at"] else None,
        error=row["error"],
        result=_parse_result(row["result"]),
        attempts=row["attempts"],
    )


@router.get("/v1/jobs")
async def list_jobs(
    workspace: str = Query(default=None),
    status: str = Query(default=None),
    limit: int = Query(default=10000, le=10000),
    _user: dict = Depends(get_current_user),
):
    # Reconcile indexing jobs before listing
    if _settings:
        try:
            await _reconcile_indexing_jobs(workspace)
        except Exception as e:
            logger.warning(f"Job reconciliation failed: {e}")

    pool = get_pool()
    conditions = []
    params = []
    idx = 1

    if workspace:
        conditions.append(f"j.workspace = ${idx}")
        params.append(workspace)
        idx += 1
    if status:
        conditions.append(f"j.status = ${idx}")
        params.append(status)
        idx += 1

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""SELECT j.*, d.file_name FROM orchestrator_ingest_jobs j
                LEFT JOIN orchestrator_documents d ON j.doc_id = d.id
                {where}
                ORDER BY j.created_at DESC
                LIMIT ${idx}"""
    params.append(limit)

    rows = await pool.fetch(query, *params)
    return {
        "jobs": [
            JobStatusResponse(
                job_id=r["id"],
                doc_id=r["doc_id"],
                file_name=r["file_name"],
                workspace=r["workspace"],
                job_type=r["job_type"],
                status=r["status"],
                created_at=r["created_at"].isoformat(),
                started_at=r["started_at"].isoformat() if r["started_at"] else None,
                completed_at=r["completed_at"].isoformat() if r["completed_at"] else None,
                error=r["error"],
                result=_parse_result(r["result"]),
                attempts=r["attempts"],
            )
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/v1/jobs/{job_id}/prioritize")
async def prioritize_job(job_id: str, _user: dict = Depends(get_current_user)):
    """Move a queued job to the priority queue so it gets processed next."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, job_type, status FROM orchestrator_ingest_jobs WHERE id = $1", job_id
    )
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    if row["status"] != "queued":
        raise HTTPException(400, f"Job {job_id} is {row['status']}, only queued jobs can be prioritized")

    await publish_ingest_job(job_id, row["job_type"], priority=True)
    return {"prioritized": job_id}


@router.post("/v1/jobs/{job_id}/retry")
async def retry_job(job_id: str, _user: dict = Depends(get_current_user)):
    """Retry a failed job by resetting it to queued and re-publishing to NATS."""
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT id, job_type, status FROM orchestrator_ingest_jobs WHERE id = $1", job_id
    )
    if not row:
        raise HTTPException(404, f"Job {job_id} not found")
    if row["status"] != "failed":
        raise HTTPException(400, f"Job {job_id} is {row['status']}, not failed")

    await pool.execute(
        """UPDATE orchestrator_ingest_jobs
           SET status = 'queued', error = NULL, result = '{}',
               attempts = 0, started_at = NULL, completed_at = NULL
           WHERE id = $1""",
        job_id,
    )
    await publish_ingest_job(job_id, row["job_type"])
    return {"retried": job_id}


@router.post("/v1/jobs/retry-failed")
async def retry_all_failed(workspace: str = Query(...), _user: dict = Depends(get_current_user)):
    """Retry all failed jobs in a workspace."""
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT id, job_type FROM orchestrator_ingest_jobs WHERE workspace = $1 AND status = 'failed'",
        workspace,
    )
    if not rows:
        return {"retried": 0}

    for r in rows:
        await pool.execute(
            """UPDATE orchestrator_ingest_jobs
               SET status = 'queued', error = NULL, result = '{}',
                   attempts = 0, started_at = NULL, completed_at = NULL
               WHERE id = $1""",
            r["id"],
        )
        await publish_ingest_job(r["id"], r["job_type"])

    return {"retried": len(rows), "workspace": workspace}
