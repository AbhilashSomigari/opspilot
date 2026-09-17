from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from ..config import settings


def _parse_lines(lines: list[str], contains: str, limit: int) -> list[dict]:
    entries = []
    for line in reversed(lines):
        if contains.lower() not in line.lower():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            entries.append({"raw": line})
        if len(entries) >= limit:
            break
    return list(reversed(entries))


def _kubernetes_logs(service: str, contains: str, limit: int) -> dict:
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
            timestamps=False,
        )
        lines.extend(text.splitlines())
    return {
        "service": service,
        "backend": "kubernetes",
        "pods": pod_names,
        "entries": _parse_lines(lines, contains, limit),
    }


async def search_logs(service: str, contains: str = "", limit: int = 80) -> dict:
    if os.getenv("KUBERNETES_SERVICE_HOST"):
        return await asyncio.to_thread(_kubernetes_logs, service, contains, limit)

    path = Path(settings.log_dir) / f"{service}.jsonl"
    if not path.exists():
        return {"service": service, "backend": "file", "entries": [], "warning": f"missing log file {path}"}
    lines = path.read_text(errors="replace").splitlines()[-2000:]
    return {
        "service": service,
        "backend": "file",
        "entries": _parse_lines(lines, contains, limit),
    }
