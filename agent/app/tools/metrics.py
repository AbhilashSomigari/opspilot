from __future__ import annotations

import math
import time

import httpx

from ..config import settings
from .base import window_start


async def prometheus_query(query: str) -> dict:
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(f"{settings.prometheus_url}/api/v1/query", params={"query": query})
        r.raise_for_status()
        return r.json()["data"]


async def service_metrics(service: str, since: float | None = None) -> dict:
    window = f"{max(1, math.ceil(time.time() - window_start(since)))}s"
    queries = {
        "request_rate": f'sum(rate(opspilot_http_requests_total{{service="{service}"}}[{window}]))',
        "error_rate": (
            f'sum(rate(opspilot_http_requests_total{{service="{service}",status=~"5.."}}[{window}])) '
            f'/ clamp_min(sum(rate(opspilot_http_requests_total{{service="{service}"}}[{window}])), 0.000001)'
        ),
        "p95_latency": (
            f'histogram_quantile(0.95, sum by (le) '
            f'(rate(opspilot_http_request_duration_seconds_bucket{{service="{service}"}}[{window}])))'
        ),
    }
    out = {}
    for name, query in queries.items():
        try:
            out[name] = await prometheus_query(query)
        except Exception as exc:
            out[name] = {"error": str(exc)}
    return {"service": service, "queries": queries, "results": out}
