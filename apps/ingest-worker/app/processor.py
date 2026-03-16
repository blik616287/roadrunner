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
# Allowlist: only these extensions are ingested
_SUPPORTED_EXTENSIONS = {
    # Code (tree-sitter)
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx",
    ".go", ".rs", ".java", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx",
    # Documents
    ".pdf", ".md", ".txt", ".rst", ".html", ".htm",
    # YAML
    ".yaml", ".yml",
    # Config
    ".ini", ".toml", ".cfg", ".conf", ".env", ".properties",
    # JSON
    ".json", ".jsonl", ".jsonc",
    # Shell
    ".sh", ".bash", ".zsh", ".fish",
}
_MAX_FILE_SIZE = 1024 * 1024  # 1MB per file
_MAX_FILES = 2000


async def process_documents_batch(
    doc_ids: list[str], preprocessor_url: str, batch_size: int = 20
) -> dict:
    """Process multiple document jobs in a single batched preprocessor call."""
    files_to_send = []
    workspace = None
    for doc_id in doc_ids:
        doc = await db.get_document_blob(doc_id)
        if not doc:
            logger.warning(f"Document {doc_id} not found, skipping")
            continue
        file_name, ws, compressed_blob, metadata = doc
        if workspace is None:
            workspace = ws
        content = gzip.decompress(compressed_blob)
        files_to_send.append((file_name, content))

    if not files_to_send:
        return {"documents_sent": 0, "errors": [], "track_ids": [], "files": []}

    return await _send_batched(files_to_send, workspace, preprocessor_url, batch_size)


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

    result = await _send_batched(extracted, workspace, preprocessor_url, batch_size)
    result["files_found"] = len(extracted)
    return result


async def _send_batched(
    files: list[tuple[str, bytes]], workspace: str, preprocessor_url: str, batch_size: int
) -> dict:
    """Send files to the preprocessor in batches."""
    errors = []
    total_docs = 0
    all_track_ids = []
    all_files = []
    async with httpx.AsyncClient(timeout=300.0) as client:
        for batch_start in range(0, len(files), batch_size):
            batch = files[batch_start:batch_start + batch_size]
            files_payload = [
                ("files", (fname, fcontent, "application/octet-stream"))
                for fname, fcontent in batch
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
        "documents_sent": total_docs,
        "errors": errors,
        "track_ids": all_track_ids,
        "files": all_files,
    }


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
    if ext not in _SUPPORTED_EXTENSIONS:
        return True
    if size > _MAX_FILE_SIZE:
        return True
    if size == 0:
        return True
    return False
