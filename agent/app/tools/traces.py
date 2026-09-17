from __future__ import annotations
import httpx
from ..config import settings


async def recent_traces(service: str, limit: int = 20) -> dict:
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(
            f"{settings.jaeger_url}/api/traces",
            params={"service": service, "limit": limit, "lookback": "1h"},
        )
        r.raise_for_status()
        payload = r.json()
    traces = []
    for trace in payload.get("data", []):
        spans = trace.get("spans", [])
        traces.append({
            "traceID": trace.get("traceID"),
            "start_time_us": min((s.get("startTime", 0) for s in spans if s.get("startTime")), default=0),
            "duration_us": max((s.get("duration", 0) for s in spans), default=0),
            "spans": [
                {
                    "operation": s.get("operationName"),
                    "duration_us": s.get("duration"),
                    "tags": s.get("tags", []),
                }
                for s in spans[:25]
            ],
        })
    return {"service": service, "traces": traces}
