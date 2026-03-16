import asyncio
import logging

import httpx
from kubernetes import client as k8s_client, config as k8s_config

logger = logging.getLogger("queue_scaler.scaler")

_apps_v1: k8s_client.AppsV1Api | None = None


def init_k8s():
    global _apps_v1
    k8s_config.load_incluster_config()
    _apps_v1 = k8s_client.AppsV1Api()


async def get_pending_count(nats_monitor_url: str, http: httpx.AsyncClient) -> int:
    try:
        resp = await http.get(
            f"{nats_monitor_url}/jsz",
            params={"streams": 1, "stream": "INGEST"},
            timeout=5.0,
        )
        resp.raise_for_status()
        data = resp.json()
        # Stream detail is nested under account_details[].stream_detail[]
        for acct in data.get("account_details", []):
            for sd in acct.get("stream_detail", []):
                if sd.get("name") == "INGEST":
                    return sd.get("state", {}).get("messages", 0)
        # Fallback: top-level messages count
        return data.get("messages", 0)
    except Exception as e:
        logger.warning(f"Failed to get NATS pending count: {e}")
        return 0


async def check_query_activity(orchestrator_url: str, http: httpx.AsyncClient) -> bool:
    try:
        resp = await http.get(
            f"{orchestrator_url}/internal/query-activity",
            timeout=3.0,
        )
        resp.raise_for_status()
        return resp.json().get("active", False)
    except Exception as e:
        logger.warning(f"Failed to check query activity: {e}. Assuming active.")
        return True


def scale_deployment(namespace: str, deployment: str, replicas: int):
    body = {"spec": {"replicas": replicas}}
    _apps_v1.patch_namespaced_deployment_scale(deployment, namespace, body)
    logger.info(f"Scaled {namespace}/{deployment} to {replicas} replicas")


def count_ready_pods(namespace: str, label_selector: str) -> int:
    core = k8s_client.CoreV1Api()
    pods = core.list_namespaced_pod(namespace, label_selector=label_selector)
    ready = 0
    for pod in pods.items:
        for c in (pod.status.conditions or []):
            if c.type == "Ready" and c.status == "True":
                ready += 1
    return ready


async def wait_for_replicas(
    namespace: str, deployment: str, target: int,
    timeout: int = 300, interval: int = 10,
):
    label = f"app={deployment}"
    elapsed = 0
    while elapsed < timeout:
        ready = count_ready_pods(namespace, label)
        if ready == target:
            logger.info(f"{deployment} reached {target} ready replicas")
            return
        await asyncio.sleep(interval)
        elapsed += interval
    logger.warning(f"Timeout: {deployment} did not reach {target} replicas in {timeout}s")
