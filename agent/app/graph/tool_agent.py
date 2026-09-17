from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..llm import client as llm_client, llm_available, model_name, sampling_kwargs
from ..db import audit
from ..rag.hybrid import hybrid_search
from ..tools.base import audited_tool
from ..tools.changes import recent_changes
from ..tools.logs import search_logs
from ..tools.metrics import service_metrics
from ..tools.traces import recent_traces

TOOL_SCHEMAS = [
    {"type":"function","function":{"name":"get_metrics","description":"Get recent Prometheus request rate, 5xx error rate, and p95 latency for a service.","parameters":{"type":"object","properties":{"service":{"type":"string","enum":["checkout","payment","catalog"]}},"required":["service"]}}},
    {"type":"function","function":{"name":"search_logs","description":"Search recent structured logs for a service.","parameters":{"type":"object","properties":{"service":{"type":"string","enum":["checkout","payment","catalog"]},"contains":{"type":"string"}},"required":["service"]}}},
    {"type":"function","function":{"name":"get_traces","description":"Get recent distributed traces for a service from Jaeger.","parameters":{"type":"object","properties":{"service":{"type":"string","enum":["checkout","payment","catalog"]}},"required":["service"]}}},
    {"type":"function","function":{"name":"get_changes","description":"Get recent deployments and GitHub commits for a service.","parameters":{"type":"object","properties":{"service":{"type":"string","enum":["checkout","payment","catalog"]}},"required":["service"]}}},
    {"type":"function","function":{"name":"search_runbooks","description":"Hybrid search over runbooks and previous incidents.","parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
]


async def _dispatch(incident_id: str, name: str, args: dict[str, Any]) -> dict:
    if name == "get_metrics":
        data = await audited_tool(incident_id, name, args, service_metrics)
    elif name == "search_logs":
        payload = {"service": args["service"], "contains": args.get("contains", ""), "limit": 80}
        data = await audited_tool(incident_id, name, payload, search_logs)
    elif name == "get_traces":
        data = await audited_tool(incident_id, name, {"service": args["service"], "limit": 20}, recent_traces)
    elif name == "get_changes":
        data = await audited_tool(incident_id, name, {"service": args["service"], "limit": 10}, recent_changes)
    elif name == "search_runbooks":
        audit(incident_id, "tool_call", "agent", name, input_data=args)
        try:
            data = hybrid_search(args["query"], 6)
            audit(incident_id, "tool_result", "tool", name, output_data=data)
        except Exception as exc:
            data = {"error": str(exc)}
            audit(incident_id, "tool_result", "tool", name, ok=False, error=str(exc))
    else:
        data = {"error": f"unknown tool {name}"}
    return {
        "source": name,
        "summary": f"{name} result for {args}",
        "data": data,
        "citation": f"tool:{name}:{incident_id}:{datetime.now(timezone.utc).isoformat()}",
    }


async def investigate_with_tools(incident_id: str, alert: str, service: str) -> list[dict]:
    # Offline/dev mode remains reproducible and exercises the exact same audited tools.
    if not llm_available():
        services = [service] if service != "checkout" else ["checkout", "payment", "catalog"]
        evidence = []
        for svc in services:
            for name in ("get_metrics", "search_logs", "get_traces", "get_changes"):
                args = {"service": svc}
                evidence.append(await _dispatch(incident_id, name, args))
        evidence.append(await _dispatch(incident_id, "search_runbooks", {"query": alert}))
        return evidence

    client = llm_client()
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are OpsPilot, a production incident investigator. Gather enough evidence to explain the alert. "
                "Prefer metrics to establish blast radius, logs/traces to localize failure, changes for temporal correlation, "
                "and runbooks/previous incidents for known patterns. Do not recommend an action yet."
            ),
        },
        {"role": "user", "content": f"Alert: {alert}\nPrimary service: {service}"},
    ]
    evidence: list[dict] = []
    for _ in range(8):
        response = await client.chat.completions.create(
            model=model_name(),
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            **sampling_kwargs(),
        )
        if response.usage:
            audit(incident_id, "model_call", "agent", "tool_planner", output_data={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            })
        msg = response.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        calls = msg.tool_calls or []
        if not calls:
            break
        for call in calls:
            args = json.loads(call.function.arguments or "{}")
            item = await _dispatch(incident_id, call.function.name, args)
            evidence.append(item)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(item["data"], default=str)[:20000],
            })
    return evidence
