"""Queue-depth auto-scaler for GraphRAG burst mode.

State machine:
  NORMAL --[N polls pending > threshold AND no active queries]--> BURST
  BURST  --[M polls pending < threshold]------------------------> NORMAL

Enter burst: scale reranker to 0 (blocks queries).
Exit burst:  scale reranker to 1 (restores query capability).
"""
import asyncio
import logging

import httpx

from .config import Settings
from .scaler import (
    init_k8s,
    get_pending_count,
    check_query_activity,
    scale_deployment,
    wait_for_replicas,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("queue_scaler.main")

NORMAL = "NORMAL"
BURST = "BURST"


async def enter_burst(settings: Settings):
    ns = settings.k8s_namespace
    logger.info(f"Scaling {settings.reranker_deployment} to {settings.reranker_burst_replicas}")
    scale_deployment(ns, settings.reranker_deployment, settings.reranker_burst_replicas)
    await wait_for_replicas(ns, settings.reranker_deployment, settings.reranker_burst_replicas)


async def exit_burst(settings: Settings):
    ns = settings.k8s_namespace
    logger.info("Waiting 10s before restoring reranker...")
    await asyncio.sleep(10)
    logger.info(f"Scaling {settings.reranker_deployment} to {settings.reranker_normal_replicas}")
    scale_deployment(ns, settings.reranker_deployment, settings.reranker_normal_replicas)


async def run():
    settings = Settings()
    init_k8s()

    state = NORMAL
    up_counter = 0
    down_counter = 0

    async with httpx.AsyncClient() as http:
        logger.info(
            f"Queue scaler started. "
            f"Poll every {settings.poll_interval}s, "
            f"burst threshold: {settings.burst_threshold} messages, "
            f"hysteresis: up={settings.hysteresis_up} down={settings.hysteresis_down}"
        )

        # Signal readiness for K8s probe
        open("/tmp/ready", "w").close()

        while True:
            try:
                pending = await get_pending_count(settings.nats_monitor_url, http)

                if state == NORMAL:
                    if pending > settings.burst_threshold:
                        query_active = await check_query_activity(
                            settings.orchestrator_url, http
                        )
                        if query_active:
                            logger.info(
                                f"Burst condition (pending={pending}) but query active — holding"
                            )
                            up_counter = 0
                        else:
                            up_counter += 1
                            logger.info(
                                f"Burst up: {up_counter}/{settings.hysteresis_up} (pending={pending})"
                            )
                            if up_counter >= settings.hysteresis_up:
                                await enter_burst(settings)
                                state = BURST
                                up_counter = 0
                                down_counter = 0
                    else:
                        up_counter = 0

                elif state == BURST:
                    if pending < settings.burst_threshold:
                        down_counter += 1
                        logger.info(
                            f"Burst down: {down_counter}/{settings.hysteresis_down} (pending={pending})"
                        )
                        if down_counter >= settings.hysteresis_down:
                            await exit_burst(settings)
                            state = NORMAL
                            down_counter = 0
                            up_counter = 0
                    else:
                        down_counter = 0

            except Exception as e:
                logger.error(f"Poll cycle error: {e}", exc_info=True)

            await asyncio.sleep(settings.poll_interval)


if __name__ == "__main__":
    asyncio.run(run())
