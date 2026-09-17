from __future__ import annotations

import json
import operator
import re
from datetime import datetime, timezone
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from ..config import settings
from ..llm import client as llm_client, llm_available, model_name, sampling_kwargs
from ..db import audit
from .tool_agent import investigate_with_tools


class IncidentState(TypedDict, total=False):
    incident_id: str
    title: str
    alert: str
    service: str
    severity: str
    evidence: Annotated[list[dict], operator.add]
    hypotheses: list[dict]
    likely_root_cause: str
    confidence: float
    recommended_action: dict
    timeline: list[str]
    report: str


def _evidence_digest(evidence: list[dict]) -> str:
    return json.dumps(evidence, default=str)[:70000]


async def gather(state: IncidentState) -> dict:
    evidence = await investigate_with_tools(state["incident_id"], state["alert"], state["service"])
    return {"evidence": evidence}


def _metric_scalar(data: Any, key: str) -> float | None:
    try:
        result = data["results"][key]["result"]
        if not result:
            return None
        return float(result[0]["value"][1])
    except Exception:
        return None


def _fallback_reason(state: IncidentState) -> dict:
    scores: list[tuple[float, str, list[str]]] = []
    for ev in state.get("evidence", []):
        if ev["source"] != "get_metrics" or not isinstance(ev.get("data"), dict):
            continue
        svc = ev["data"].get("service", "unknown")
        err = _metric_scalar(ev["data"], "error_rate")
        p95 = _metric_scalar(ev["data"], "p95_latency")
        if err is not None:
            scores.append((err * 2, f"Elevated 5xx failures in {svc}", [ev["citation"]]))
        if p95 is not None:
            scores.append((min(p95 / 3, 1.0), f"Latency regression in {svc}", [ev["citation"]]))
    scores.sort(reverse=True)
    if scores and scores[0][0] > 0.05:
        confidence = min(0.92, max(0.45, scores[0][0]))
        cause, cites = scores[0][1], scores[0][2]
    else:
        cause = f"Insufficient evidence; suspected failure in {state['service']} path"
        confidence = 0.35
        cites = [e["citation"] for e in state.get("evidence", [])[:2]]

    action_kind = "rollback" if "deploy" in state["alert"].lower() else "github_issue"
    return {
        "likely_root_cause": cause,
        "confidence": confidence,
        "hypotheses": [
            {"cause": cause, "confidence": confidence, "supporting_citations": cites, "contradicting_citations": []}
        ],
        "recommended_action": {
            "kind": action_kind,
            "description": f"Validate and remediate: {cause}. Execute only after human approval.",
            "risk": "medium",
            "requires_approval": True,
            "payload": {},
        },
    }


async def reason(state: IncidentState) -> dict:
    incident_id = state["incident_id"]
    if not llm_available():
        output = _fallback_reason(state)
        audit(incident_id, "decision", "agent", "root_cause_reasoning", input_data={"evidence_count": len(state.get("evidence", []))}, output_data=output)
        return output

    client = llm_client()
    prompt = f"""Analyze this production incident using ONLY the supplied evidence.
Alert: {state['alert']}
Service: {state['service']}
Evidence JSON: {_evidence_digest(state.get('evidence', []))}

Return strict JSON with keys:
likely_root_cause (string), confidence (0..1), hypotheses (array of up to 3 objects with cause, confidence, supporting_citations, contradicting_citations), and recommended_action (object with kind: rollback|config_change|code_fix|github_issue|none, description, risk: low|medium|high, requires_approval:true, payload:object).
Every factual claim must be supported by citation strings copied from the evidence. If evidence is weak, lower confidence. Never claim an action was executed."""
    response = await client.chat.completions.create(
        model=model_name(),
        messages=[{"role": "system", "content": "You are a skeptical SRE. Output JSON only."}, {"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        **sampling_kwargs(),
    )
    if response.usage:
        audit(incident_id, "model_call", "agent", "root_cause_model", output_data={
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        })
    output = json.loads(response.choices[0].message.content or "{}")
    output.setdefault("confidence", 0.3)
    output.setdefault("hypotheses", [])
    output.setdefault("recommended_action", {"kind":"none","description":"Gather more evidence","risk":"low","requires_approval":True,"payload":{}})
    audit(incident_id, "decision", "agent", "root_cause_reasoning", input_data={"evidence_count": len(state.get("evidence", []))}, output_data=output)
    return output


async def compose_report(state: IncidentState) -> dict:
    now = datetime.now(timezone.utc)
    citations = []
    for h in state.get("hypotheses", []):
        citations.extend(h.get("supporting_citations", []))
    citations = list(dict.fromkeys(citations))

    events: list[tuple[datetime, str]] = []
    for ev in state.get("evidence", []):
        source = ev.get("source")
        data = ev.get("data") or {}
        cite = ev.get("citation", "")
        if source == "get_changes" and isinstance(data, dict):
            for dep in data.get("deployments", []):
                try:
                    ts = datetime.fromisoformat(dep["deployed_at"].replace("Z", "+00:00"))
                    events.append((ts, f"Deployment {dep.get('service')} {dep.get('version')} ({dep.get('sha')}) [{cite}]"))
                except Exception:
                    pass
        elif source == "search_logs" and isinstance(data, dict):
            for entry in data.get("entries", [])[-6:]:
                try:
                    ts = datetime.fromtimestamp(float(entry["ts"]), tz=timezone.utc)
                    events.append((ts, f"Log {entry.get('service','?')}: {entry.get('message','event')} status={entry.get('status','-')} [{cite}]"))
                except Exception:
                    pass
        elif source == "get_traces" and isinstance(data, dict):
            for tr in data.get("traces", [])[:4]:
                try:
                    start_us = int(tr.get("start_time_us") or 0)
                    if start_us:
                        ts = datetime.fromtimestamp(start_us / 1_000_000, tz=timezone.utc)
                        events.append((ts, f"Trace {tr.get('traceID')} duration={tr.get('duration_us',0)}us [{cite}]"))
                except Exception:
                    pass

    events.append((now, f"Alert received: {state['alert']}"))
    events.sort(key=lambda x: x[0])
    timeline = [f"{ts.isoformat()} — {message}" for ts, message in events[-24:]]

    action = state.get("recommended_action", {})
    report = (
        f"# Incident {state['incident_id']}: {state['title']}\n\n"
        f"## Finding\n{state.get('likely_root_cause','Unknown')} "
        f"(confidence {state.get('confidence',0):.2f}).\n\n"
        f"## Timeline\n" + "\n".join(f"- {item}" for item in timeline) + "\n\n"
        f"## Recommended action\n{action.get('description','No action proposed')}\n\n"
        f"**Execution status:** NOT EXECUTED — human approval required.\n\n"
        f"## Evidence citations\n" + "\n".join(f"- {c}" for c in citations)
    )
    audit(state["incident_id"], "decision", "agent", "report_generated", output_data={"citations": citations, "timeline_events": len(timeline)})
    return {"timeline": timeline, "report": report}


def build_graph(checkpointer=None):
    graph = StateGraph(IncidentState)
    graph.add_node("gather", gather)
    graph.add_node("reason", reason)
    graph.add_node("report", compose_report)
    graph.add_edge(START, "gather")
    graph.add_edge("gather", "reason")
    graph.add_edge("reason", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)


async def run_workflow(initial_state: IncidentState, thread_id: str) -> IncidentState:
    # PostgreSQL-backed checkpoints make the LangGraph state durable between nodes.
    # setup() is idempotent and applies any pending checkpoint schema migrations.
    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer=checkpointer)
        return await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": thread_id}},
        )
