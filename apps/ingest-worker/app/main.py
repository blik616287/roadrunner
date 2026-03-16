import asyncio
import json
import logging
import signal

import httpx
import nats
from nats.js.api import ConsumerConfig, StreamConfig

from .config import Settings
from .db import init_pool, close_pool, get_job, mark_job_started, mark_job_indexing, mark_job_completed, mark_job_failed, reset_job_queued
from .processor import process_documents_batch, process_codebase

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest-worker")

STREAM_NAME = "INGEST"
SUBJECTS = ["ingest.document", "ingest.codebase", "ingest.priority.document", "ingest.priority.codebase"]
CONSUMER_NAME = "ingest-worker"
PRIORITY_CONSUMER_NAME = "ingest-worker-priority"

settings = Settings()
_shutdown = asyncio.Event()


async def setup_stream(js):
    """Create or update the INGEST JetStream stream."""
    try:
        await js.find_stream_name_by_subject("ingest.>")
        # Update stream to ensure priority subjects are included
        await js.update_stream(
            StreamConfig(
                name=STREAM_NAME,
                subjects=SUBJECTS,
                retention="workqueue",
                max_msgs=10000,
                storage="file",
            )
        )
        logger.info(f"Stream {STREAM_NAME} updated")
    except Exception:
        await js.add_stream(
            StreamConfig(
                name=STREAM_NAME,
                subjects=SUBJECTS,
                retention="workqueue",
                max_msgs=10000,
                storage="file",
            )
        )
        logger.info(f"Created stream {STREAM_NAME}")


async def _poll_track_status(track_ids: list[str], workspace: str, msg=None) -> tuple[bool, bool]:
    """Poll LightRAG track_status until all tracks complete or timeout.

    Returns (all_done, any_failed).
    """
    deadline = asyncio.get_event_loop().time() + settings.indexing_poll_timeout
    async with httpx.AsyncClient(timeout=10.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            # Extend NATS ack deadline while we're still polling
            if msg:
                await msg.in_progress()
            all_done = True
            any_failed = False
            for tid in track_ids:
                try:
                    resp = await client.get(
                        f"{settings.lightrag_url}/documents/track_status/{tid}",
                        headers={"LIGHTRAG-WORKSPACE": workspace},
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
                return True, any_failed
            await asyncio.sleep(settings.indexing_poll_interval)
    return False, False  # timed out


async def _process_and_ack(msg, job_id: str, job_type: str, job: dict):
    """Process a single job: decompress → preprocess → poll until done → ack."""
    try:
        if job_type == "codebase":
            result = await process_codebase(
                job_id, job["doc_id"], settings.preprocessor_url, settings.batch_size
            )
        else:
            result = await process_documents_batch(
                [job["doc_id"]], settings.preprocessor_url, settings.batch_size
            )

        track_ids = result.get("track_ids", [])
        if track_ids:
            await mark_job_indexing(job_id, result)
            logger.info(f"Job {job_id} sent to LightRAG: {len(track_ids)} tracks, polling...")
            done, failed = await _poll_track_status(track_ids, job["workspace"], msg=msg)
            if done and not failed:
                await mark_job_completed(job_id, result)
                logger.info(f"Job {job_id} completed")
            elif done and failed:
                await mark_job_failed(job_id, "LightRAG extraction failed")
                logger.warning(f"Job {job_id} failed in LightRAG")
            else:
                await mark_job_failed(job_id, "LightRAG indexing timed out")
                logger.warning(f"Job {job_id} poll timed out, marked failed")
        else:
            await mark_job_completed(job_id, result)
            logger.info(f"Job {job_id} completed (no new docs)")

        await msg.ack()

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        attempts = job["attempts"] + 1
        if attempts >= settings.max_redeliveries:
            await mark_job_failed(job_id, str(e))
            await msg.term()
        else:
            await mark_job_failed(job_id, str(e))
            await reset_job_queued(job_id)
            await msg.nak()


async def handle_messages(messages):
    """Process a batch of NATS messages. Document jobs in the same workspace are batched together."""
    parsed = []
    for msg in messages:
        try:
            payload = json.loads(msg.data.decode())
            job_id = payload["job_id"]
            job_type = payload.get("type", "document")
        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"Invalid message payload: {e}")
            await msg.term()
            continue

        job = await get_job(job_id)
        if not job:
            logger.error(f"Job {job_id} not found in database")
            await msg.term()
            continue
        if job["status"] == "completed":
            logger.info(f"Job {job_id} already completed, skipping")
            await msg.ack()
            continue

        parsed.append((msg, job_id, job_type, job))

    # Handle codebase jobs individually (already internally batched)
    doc_jobs_by_workspace = {}
    for msg, job_id, job_type, job in parsed:
        if job_type == "codebase":
            await mark_job_started(job_id)
            await _process_and_ack(msg, job_id, job_type, job)
        else:
            ws = job["workspace"]
            doc_jobs_by_workspace.setdefault(ws, []).append((msg, job_id, job))

    # Batch document jobs per workspace
    for workspace, jobs in doc_jobs_by_workspace.items():
        job_ids = [j[1] for j in jobs]
        doc_ids = [j[2]["doc_id"] for j in jobs]
        msgs = [j[0] for j in jobs]
        job_records = [j[2] for j in jobs]

        for jid in job_ids:
            await mark_job_started(jid)

        logger.info(f"Batching {len(job_ids)} document jobs for workspace '{workspace}'")

        try:
            result = await process_documents_batch(
                doc_ids, settings.preprocessor_url, settings.batch_size
            )
            track_ids = result.get("track_ids", [])

            if track_ids:
                for jid in job_ids:
                    await mark_job_indexing(jid, result)
                logger.info(f"Workspace '{workspace}' batch sent to LightRAG: {len(track_ids)} tracks, polling...")

                done, failed = await _poll_track_status(track_ids, workspace)
                if done and not failed:
                    for jid in job_ids:
                        await mark_job_completed(jid, result)
                    logger.info(f"Workspace '{workspace}' batch completed ({len(job_ids)} jobs)")
                elif done and failed:
                    for jid in job_ids:
                        await mark_job_failed(jid, "LightRAG extraction failed")
                    logger.warning(f"Workspace '{workspace}' batch failed in LightRAG")
                else:
                    for jid in job_ids:
                        await mark_job_failed(jid, "LightRAG indexing timed out")
                    logger.warning(f"Workspace '{workspace}' batch poll timed out, marked failed")
            else:
                for jid in job_ids:
                    await mark_job_completed(jid, result)
                logger.info(f"Workspace '{workspace}' batch completed (no new docs)")

            for m in msgs:
                await m.ack()

        except Exception as e:
            logger.error(f"Batch failed for workspace '{workspace}': {e}")
            for m, jid, job in zip(msgs, job_ids, job_records):
                attempts = job["attempts"] + 1
                if attempts >= settings.max_redeliveries:
                    await mark_job_failed(jid, str(e))
                    await m.term()
                else:
                    await mark_job_failed(jid, str(e))
                    await reset_job_queued(jid)
                    await m.nak()


async def run():
    logger.info("Starting ingest worker...")

    await init_pool(settings)

    nc = await nats.connect(settings.nats_url)
    js = nc.jetstream()
    await setup_stream(js)
    logger.info(f"Connected to NATS at {settings.nats_url}")

    # Ensure consumers have correct filter and ack_wait (recreate if needed)
    ack_wait_secs = 600  # 10 minutes (nats-py converts to nanoseconds internally)
    consumer_defs = [
        (CONSUMER_NAME, "ingest.*"),
        (PRIORITY_CONSUMER_NAME, "ingest.priority.>"),
    ]
    for name, expected_filter in consumer_defs:
        try:
            info = await js.consumer_info(STREAM_NAME, name)
            needs_recreate = (
                info.config.filter_subject != expected_filter
                or info.config.ack_wait != ack_wait_secs
            )
            if needs_recreate:
                await js.delete_consumer(STREAM_NAME, name)
                logger.info(f"Deleted consumer {name} (filter={info.config.filter_subject}, ack_wait={info.config.ack_wait})")
        except Exception:
            pass  # consumer doesn't exist yet

    priority_sub = await js.pull_subscribe(
        "ingest.priority.>",
        durable=PRIORITY_CONSUMER_NAME,
        stream=STREAM_NAME,
        config=ConsumerConfig(ack_wait=ack_wait_secs),
    )

    sub = await js.pull_subscribe(
        "ingest.*",
        durable=CONSUMER_NAME,
        stream=STREAM_NAME,
        config=ConsumerConfig(ack_wait=ack_wait_secs),
    )

    logger.info("Ingest worker ready, waiting for jobs...")

    async def _parse_and_queue(messages):
        """Parse messages and return list of process tasks."""
        tasks = []
        for msg in messages:
            try:
                payload = json.loads(msg.data.decode())
                job_id = payload["job_id"]
                job_type = payload.get("type", "document")
            except (json.JSONDecodeError, KeyError) as e:
                logger.error(f"Invalid message payload: {e}")
                await msg.term()
                continue

            job = await get_job(job_id)
            if not job:
                logger.error(f"Job {job_id} not found in database")
                await msg.term()
                continue
            if job["status"] == "completed":
                logger.info(f"Job {job_id} already completed, skipping")
                await msg.ack()
                continue

            await mark_job_started(job_id)
            tasks.append(_process_and_ack(msg, job_id, job_type, job))
        return tasks

    while not _shutdown.is_set():
        try:
            # Check priority queue first (short timeout)
            tasks = []
            try:
                priority_msgs = await priority_sub.fetch(batch=settings.fetch_batch, timeout=1)
                tasks = await _parse_and_queue(priority_msgs)
                if tasks:
                    logger.info(f"Processing {len(tasks)} priority job(s)")
            except nats.errors.TimeoutError:
                pass

            # Fill remaining slots from regular queue
            remaining = settings.fetch_batch - len(tasks)
            if remaining > 0:
                try:
                    messages = await sub.fetch(batch=remaining, timeout=4)
                    tasks.extend(await _parse_and_queue(messages))
                except nats.errors.TimeoutError:
                    pass

            if tasks:
                await asyncio.gather(*tasks)
        except nats.errors.TimeoutError:
            continue
        except Exception as e:
            logger.error(f"Error fetching messages: {e}")
            await asyncio.sleep(1)

    logger.info("Shutting down ingest worker...")
    await sub.unsubscribe()
    await nc.drain()
    await close_pool()


def main():
    loop = asyncio.new_event_loop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown.set)

    try:
        loop.run_until_complete(run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
