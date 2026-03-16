import json
import logging

import nats
from nats.js import JetStreamContext
from nats.js.api import StreamConfig

logger = logging.getLogger("orchestrator.nats")

STREAM_NAME = "INGEST"
STREAM_SUBJECTS = [
    "ingest.document", "ingest.codebase",
    "ingest.priority.document", "ingest.priority.codebase",
]

_nc: nats.NATS | None = None
_js: JetStreamContext | None = None


async def init_nats(nats_url: str):
    global _nc, _js
    _nc = await nats.connect(nats_url)
    _js = _nc.jetstream()
    logger.info(f"Connected to NATS at {nats_url}")

    # Ensure INGEST stream exists with priority subjects
    cfg = StreamConfig(
        name=STREAM_NAME,
        subjects=STREAM_SUBJECTS,
        retention="workqueue",
        max_msgs=10000,
        storage="file",
    )
    try:
        await _js.find_stream_name_by_subject("ingest.>")
        await _js.update_stream(cfg)
        logger.info(f"Stream {STREAM_NAME} updated with subjects {STREAM_SUBJECTS}")
    except Exception:
        await _js.add_stream(cfg)
        logger.info(f"Created stream {STREAM_NAME}")


async def close_nats():
    global _nc, _js
    if _nc:
        await _nc.drain()
        _nc = None
        _js = None


async def publish_ingest_job(job_id: str, job_type: str = "document", priority: bool = False):
    """Publish an ingestion job to the NATS INGEST stream."""
    assert _js is not None, "NATS not initialized"
    prefix = "ingest.priority" if priority else "ingest"
    subject = f"{prefix}.{job_type}"
    payload = json.dumps({"job_id": job_id, "type": job_type}).encode()
    ack = await _js.publish(subject, payload)
    logger.info(f"Published job {job_id} to {subject} (seq={ack.seq})")
    return ack
