from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

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


# Request path of the system under investigation. An alert names where symptoms surface, which
# is often not where the fault originates: checkout errors can start in catalog or payment.
SERVICE_DEPENDENCIES = {"checkout": ["catalog", "payment"], "catalog": [], "payment": []}
# Evidence required from every service on the failing path before the agent may conclude.
# Without this, the model stopped after one checkout-only round and blamed the wrong service.
REQUIRED_PER_SERVICE = ("get_metrics", "search_logs", "get_changes")


def failing_path(service: str) -> list[str]:
    return [service, *SERVICE_DEPENDENCIES.get(service, [])]


def unexamined(path: list[str], examined: set[tuple[str, str]]) -> list[str]:
    return [f"{tool}({svc})" for svc in path for tool in REQUIRED_PER_SERVICE if (tool, svc) not in examined]


async def _dispatch(incident_id: str, name: str, args: dict[str, Any], since: float) -> dict:
    # The evidence window comes from the incident, never from model-chosen arguments.
    if name == "get_metrics":
        data = await audited_tool(incident_id, name, {"service": args["service"], "since": since}, service_metrics)
    elif name == "search_logs":
        payload = {"service": args["service"], "contains": args.get("contains", ""), "limit": 80, "since": since}
        data = await audited_tool(incident_id, name, payload, search_logs)
    elif name == "get_traces":
        data = await audited_tool(incident_id, name, {"service": args["service"], "limit": 20, "since": since}, recent_traces)
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


async def investigate_with_tools(incident_id: str, alert: str, service: str, since: float) -> list[dict]:
    # Offline/dev mode remains reproducible and exercises the exact same audited tools.
    if not llm_available():
        evidence = []
        for svc in failing_path(service):
            for name in ("get_metrics", "search_logs", "get_traces", "get_changes"):
                args = {"service": svc}
                evidence.append(await _dispatch(incident_id, name, args, since))
        evidence.append(await _dispatch(incident_id, "search_runbooks", {"query": alert}, since))
        return evidence

    client = llm_client()
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are OpsPilot, a production incident investigator. Gather enough evidence to explain the alert. "
                "Prefer metrics to establish blast radius, logs/traces to localize failure, changes for temporal correlation, "
                "and runbooks/previous incidents for known patterns. Do not recommend an action yet.\n"
                f"Service dependencies: {json.dumps(SERVICE_DEPENDENCIES)}. The alerting service is where symptoms "
                "surface; the fault may originate in a dependency. Examine every service on the failing path and "
                "test each hypothesis against evidence from the service it blames before stopping."
            ),
        },
        {"role": "user", "content": f"Alert: {alert}\nPrimary service: {service}"},
    ]
    evidence: list[dict] = []
    examined: set[tuple[str, str]] = set()
    nudged = False
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
            missing = unexamined(failing_path(service), examined)
            if missing and not nudged:
                nudged = True
                audit(incident_id, "decision", "agent", "coverage_nudge", output_data={"missing": missing})
                messages.append({
                    "role": "user",
                    "content": f"Before concluding, also examine: {', '.join(missing)}. "
                               "Symptoms surface at the alerting service; the origin may be a dependency.",
                })
                continue
            break
        for call in calls:
            args = json.loads(call.function.arguments or "{}")
            examined.add((call.function.name, args.get("service", "")))
            item = await _dispatch(incident_id, call.function.name, args, since)
            evidence.append(item)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(item["data"], default=str)[:20000],
            })
    return evidence
