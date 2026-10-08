from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path

from ..config import settings
from .base import window_start


def _parse_lines(lines: list[str], contains: str, limit: int, since: float) -> list[dict]:
    entries = []
    for line in reversed(lines):
        if contains.lower() not in line.lower():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            entry = {"raw": line}
        if isinstance(entry.get("ts"), (int, float)) and entry["ts"] < since:
            continue
        entries.append(entry)
        if len(entries) >= limit:
            break
    return list(reversed(entries))


def _kubernetes_logs(service: str, contains: str, limit: int, since: float) -> dict:
    from kubernetes import client, config

    config.load_incluster_config()
    api = client.CoreV1Api()
    namespace = os.getenv("POD_NAMESPACE", "opspilot")
    pods = api.list_namespaced_pod(namespace=namespace, label_selector=f"app={service}").items
    lines: list[str] = []
    pod_names: list[str] = []
    for pod in pods[:5]:
        pod_names.append(pod.metadata.name)
        text = api.read_namespaced_pod_log(
            name=pod.metadata.name,
            namespace=namespace,
            tail_lines=500,
            since_seconds=max(1, math.ceil(time.time() - since)),
            timestamps=False,
        )
        lines.extend(text.splitlines())
    return {
        "service": service,
        "backend": "kubernetes",
        "pods": pod_names,
        "entries": _parse_lines(lines, contains, limit, since),
    }


async def search_logs(service: str, contains: str = "", limit: int = 80, since: float | None = None) -> dict:
    since = window_start(since)
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return await asyncio.to_thread(_kubernetes_logs, service, contains, limit, since)

    path = Path(settings.log_dir) / f"{service}.jsonl"
    if not path.exists():
        return {"service": service, "backend": "file", "entries": [], "warning": f"missing log file {path}"}
    lines = path.read_text(errors="replace").splitlines()[-2000:]
    return {
        "service": service,
        "backend": "file",
        "entries": _parse_lines(lines, contains, limit, since),
    }
