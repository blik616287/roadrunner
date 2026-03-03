#!/usr/bin/env python3
"""
Benchmark the GraphRAG ingestion pipeline.

Submits files concurrently to the orchestrator's /v1/documents/ingest endpoint,
then polls jobs until all complete. Reports throughput metrics.

Usage:
  python3 scripts/benchmark-ingest.py [--concurrency 8] [--workspace bench-test]
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

ORCHESTRATOR = "http://localhost:31800"
EXTENSIONS = {".py", ".yaml", ".yml", ".md", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs"}
SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "dist", "build"}
MIN_SIZE = 500  # bytes


def collect_files(root: str) -> list[Path]:
    """Collect source files suitable for ingestion."""
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = Path(dirpath) / f
            if p.suffix in EXTENSIONS and p.stat().st_size >= MIN_SIZE:
                files.append(p)
    return sorted(files)


async def submit_file(
    client: httpx.AsyncClient,
    path: Path,
    workspace: str,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Submit a single file for ingestion, return job metadata."""
    async with semaphore:
        with open(path, "rb") as f:
            t0 = time.monotonic()
            resp = await client.post(
                f"{ORCHESTRATOR}/v1/documents/ingest",
                files={"file": (path.name, f)},
                headers={"X-Workspace": workspace},
                timeout=30,
            )
            elapsed = time.monotonic() - t0

        if resp.status_code != 200:
            return {"file": path.name, "error": resp.text, "submit_time": elapsed}

        data = resp.json()
        return {
            "file": path.name,
            "job_id": data["job_id"],
            "doc_id": data["doc_id"],
            "size": path.stat().st_size,
            "compressed": data.get("compressed_size", 0),
            "submit_time": elapsed,
        }


async def poll_job(
    client: httpx.AsyncClient,
    job_id: str,
    timeout: float = 600,
) -> dict:
    """Poll a job until it reaches a terminal state."""
    t0 = time.monotonic()
    while True:
        resp = await client.get(f"{ORCHESTRATOR}/v1/jobs/{job_id}", timeout=10)
        data = resp.json()
        status = data["status"]
        if status in ("completed", "failed"):
            return {
                "job_id": job_id,
                "status": status,
                "wall_time": time.monotonic() - t0,
                "error": data.get("error"),
                "result": data.get("result"),
                "created_at": data.get("created_at"),
                "started_at": data.get("started_at"),
                "completed_at": data.get("completed_at"),
            }
        if time.monotonic() - t0 > timeout:
            return {
                "job_id": job_id,
                "status": "timeout",
                "wall_time": time.monotonic() - t0,
            }
        await asyncio.sleep(2)


async def run_benchmark(root: str, concurrency: int, workspace: str):
    files = collect_files(root)
    if not files:
        print("No files found to ingest.")
        sys.exit(1)

    total_bytes = sum(f.stat().st_size for f in files)
    print(f"=== GraphRAG Ingestion Benchmark ===")
    print(f"Files: {len(files)}")
    print(f"Total size: {total_bytes / 1024:.1f} KB")
    print(f"Concurrency: {concurrency}")
    print(f"Workspace: {workspace}")
    print(f"Orchestrator: {ORCHESTRATOR}")
    print()

    # Phase 1: Submit all files
    print(f"--- Phase 1: Submitting {len(files)} files ---")
    semaphore = asyncio.Semaphore(concurrency)
    t_submit_start = time.monotonic()

    async with httpx.AsyncClient() as client:
        tasks = [submit_file(client, f, workspace, semaphore) for f in files]
        results = await asyncio.gather(*tasks)

    t_submit_end = time.monotonic()
    submit_elapsed = t_submit_end - t_submit_start

    errors = [r for r in results if "error" in r]
    submitted = [r for r in results if "job_id" in r]

    if errors:
        print(f"  Submit errors: {len(errors)}")
        for e in errors[:3]:
            print(f"    {e['file']}: {e['error'][:100]}")

    print(f"  Submitted: {len(submitted)} files in {submit_elapsed:.1f}s")
    print(f"  Submit rate: {len(submitted) / submit_elapsed:.1f} files/s")
    print()

    if not submitted:
        print("No files submitted successfully.")
        return

    # Phase 2: Wait for all jobs to complete
    print(f"--- Phase 2: Waiting for {len(submitted)} jobs to complete ---")
    t_process_start = time.monotonic()

    async with httpx.AsyncClient() as client:
        poll_tasks = [poll_job(client, r["job_id"]) for r in submitted]
        job_results = await asyncio.gather(*poll_tasks)

    t_process_end = time.monotonic()
    total_elapsed = t_process_end - t_submit_start
    process_elapsed = t_process_end - t_process_start

    completed = [j for j in job_results if j["status"] == "completed"]
    failed = [j for j in job_results if j["status"] == "failed"]
    timed_out = [j for j in job_results if j["status"] == "timeout"]

    print(f"  Completed: {len(completed)}")
    if failed:
        print(f"  Failed: {len(failed)}")
        for f in failed[:3]:
            print(f"    {f['job_id'][:8]}: {f.get('error', 'unknown')[:100]}")
    if timed_out:
        print(f"  Timed out: {len(timed_out)}")
    print()

    # Phase 3: Summary
    submitted_bytes = sum(r["size"] for r in submitted)
    wall_times = [j["wall_time"] for j in completed]

    print(f"=== Results ===")
    print(f"  Total files:      {len(submitted)}")
    print(f"  Total size:       {submitted_bytes / 1024:.1f} KB")
    print(f"  Submit phase:     {submit_elapsed:.1f}s")
    print(f"  Processing phase: {process_elapsed:.1f}s")
    print(f"  Total wall time:  {total_elapsed:.1f}s")
    print()
    print(f"  End-to-end throughput:")
    print(f"    {len(completed) / total_elapsed:.2f} docs/s")
    print(f"    {submitted_bytes / total_elapsed / 1024:.2f} KB/s")
    print()
    if wall_times:
        print(f"  Per-job wall time (submit → complete):")
        print(f"    Min:    {min(wall_times):.1f}s")
        print(f"    Median: {sorted(wall_times)[len(wall_times)//2]:.1f}s")
        print(f"    Max:    {max(wall_times):.1f}s")
        print(f"    Mean:   {sum(wall_times)/len(wall_times):.1f}s")
    print()
    print(f"  Success rate: {len(completed)}/{len(submitted)} ({100*len(completed)/len(submitted):.0f}%)")


def main():
    parser = argparse.ArgumentParser(description="Benchmark GraphRAG ingestion")
    parser.add_argument(
        "--root",
        default="/home/b/Desktop/k8s_rag",
        help="Root directory to collect files from",
    )
    parser.add_argument("--concurrency", type=int, default=8, help="Max concurrent submissions")
    parser.add_argument("--workspace", default="benchmark", help="Workspace name")
    args = parser.parse_args()

    asyncio.run(run_benchmark(args.root, args.concurrency, args.workspace))


if __name__ == "__main__":
    main()
