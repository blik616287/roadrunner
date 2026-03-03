import asyncio
import gzip
import io
import logging
import tarfile
import zipfile
from pathlib import PurePosixPath

import httpx

from . import db

logger = logging.getLogger("ingest-worker.processor")

_SKIP_DIRS = {
    "__pycache__", ".git", ".svn", ".hg", "node_modules",
    ".tox", ".venv", "venv", ".mypy_cache", ".pytest_cache",
    "dist", "build", ".next", "target",
}
_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".o", ".a",
    ".class", ".jar", ".war", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
    ".lock", ".map",
}
_MAX_FILE_SIZE = 1024 * 1024  # 1MB per file
_MAX_FILES = 2000


async def process_document(job_id: str, doc_id: str, preprocessor_url: str) -> dict:
    """Process a single document ingestion job."""
    doc = await db.get_document_blob(doc_id)
    if not doc:
        raise ValueError(f"Document {doc_id} not found in database")

    file_name, workspace, compressed_blob, metadata = doc
    content = gzip.decompress(compressed_blob)

    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{preprocessor_url}/ingest",
            files={"files": (file_name, content, "application/octet-stream")},
            headers={"X-Workspace": workspace},
        )
        resp.raise_for_status()
        result = resp.json()

    tracks = result.get("track_ids", [])
    track_ids = [t["track_id"] for t in tracks]
    files = [t["file_source"] for t in tracks]
    return {
        "documents_sent": result.get("documents_sent", 0),
        "errors": result.get("errors", []),
        "track_ids": track_ids,
        "files": files,
    }


async def process_codebase(
    job_id: str, doc_id: str, preprocessor_url: str, batch_size: int = 20
) -> dict:
    """Process a codebase archive ingestion job."""
    doc = await db.get_document_blob(doc_id)
    if not doc:
        raise ValueError(f"Document {doc_id} not found in database")

    file_name, workspace, compressed_blob, metadata = doc
    archive_bytes = gzip.decompress(compressed_blob)

    extracted = _extract_archive(archive_bytes, file_name)
    if not extracted:
        raise ValueError(f"Could not extract files from {file_name}")

    errors = []
    total_docs = 0
    all_track_ids = []
    all_files = []
    async with httpx.AsyncClient(timeout=300.0) as client:
        for batch_start in range(0, len(extracted), batch_size):
            batch = extracted[batch_start:batch_start + batch_size]
            files_payload = [
                ("files", (fpath, fcontent, "application/octet-stream"))
                for fpath, fcontent in batch
            ]
            try:
                resp = await client.post(
                    f"{preprocessor_url}/ingest",
                    files=files_payload,
                    headers={"X-Workspace": workspace},
                )
                resp.raise_for_status()
                result = resp.json()
                total_docs += result.get("documents_sent", 0)
                if result.get("errors"):
                    errors.extend(result["errors"])
                for t in result.get("track_ids", []):
                    all_track_ids.append(t["track_id"])
                    all_files.append(t["file_source"])
            except Exception as e:
                errors.append(f"batch {batch_start // batch_size}: {e}")

    return {
        "files_found": len(extracted),
        "documents_sent": total_docs,
        "errors": errors,
        "track_ids": all_track_ids,
        "files": all_files,
    }


async def poll_track_status(
    track_ids: list[str],
    workspace: str,
    lightrag_url: str,
    timeout: int = 300,
    interval: int = 5,
) -> bool:
    """Poll LightRAG track_status for each track_id until all are processed.

    Returns True if timed out (some docs still not processed), False if all done.
    """
    pending = set(track_ids)
    elapsed = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        while elapsed < timeout and pending:
            done = set()
            for tid in pending:
                try:
                    resp = await client.get(
                        f"{lightrag_url}/documents/track_status/{tid}",
                        headers={"LIGHTRAG-WORKSPACE": workspace},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        summary = data.get("status_summary", {})
                        total = sum(summary.values())
                        processed = summary.get("processed", 0) + summary.get("failed", 0)
                        if total > 0 and processed >= total:
                            done.add(tid)
                except Exception as e:
                    logger.warning(f"track_status poll error for {tid}: {e}")
            pending -= done
            if not pending:
                return False
            await asyncio.sleep(interval)
            elapsed += interval
    return len(pending) > 0


def _extract_archive(data: bytes, filename: str) -> list[tuple[str, bytes]]:
    """Extract files from tar.gz or zip archive."""
    files = []
    if filename.endswith((".tar.gz", ".tgz", ".tar.bz2", ".tar.xz", ".tar")):
        try:
            with tarfile.open(fileobj=io.BytesIO(data)) as tar:
                for member in tar.getmembers():
                    if not member.isfile():
                        continue
                    if _should_skip(member.name, member.size):
                        continue
                    f = tar.extractfile(member)
                    if f:
                        files.append((member.name, f.read()))
                    if len(files) >= _MAX_FILES:
                        break
        except tarfile.TarError:
            return []
    elif filename.endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    if _should_skip(info.filename, info.file_size):
                        continue
                    files.append((info.filename, zf.read(info)))
                    if len(files) >= _MAX_FILES:
                        break
        except zipfile.BadZipFile:
            return []
    return files


def _should_skip(path: str, size: int) -> bool:
    """Check if a file should be skipped during extraction."""
    parts = PurePosixPath(path).parts
    if any(p.startswith(".") for p in parts):
        return True
    if any(p in _SKIP_DIRS for p in parts):
        return True
    ext = PurePosixPath(path).suffix.lower()
    if ext in _SKIP_EXTENSIONS:
        return True
    if size > _MAX_FILE_SIZE:
        return True
    if size == 0:
        return True
    return False
