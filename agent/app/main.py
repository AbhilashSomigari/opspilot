from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from .auth import authenticated_approver, authenticated_client, authenticated_reader
from .config import settings
from .db import (
    audit, audit_trail, claim_decision, create_incident, get_incident, init_db, mark_approved, record_change,
    save_result,
)
from .graph.workflow import run_workflow
from .models.schemas import ChangeEvent, IncidentRequest
from .rag.hybrid import ingest_paths
from .tools.base import DEFAULT_WINDOW_S
from .tools.changes import create_github_issue

app = FastAPI(title="OpsPilot Agent API", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    init_db()
    root = Path(settings.repo_root)
    ingest_paths([root / "runbooks", root / "incidents"])


@app.get("/health")
def health():
    return {"ok": True, "service": "agent"}


@app.post("/changes", status_code=201, dependencies=[Depends(authenticated_client)])
def ingest_change(event: ChangeEvent):
    # Deployment/config events as a CI/CD pipeline would report them.
    return record_change(event.model_dump())


@app.post("/incidents")
async def investigate(req: IncidentRequest, client: str = Depends(authenticated_client)):
    incident_id = f"inc-{uuid.uuid4().hex[:10]}"
    started = datetime.now(timezone.utc)
    window_start = req.window_start or started - timedelta(seconds=DEFAULT_WINDOW_S)
    payload = req.model_dump(mode="json")
    create_incident(incident_id, payload)
    audit(incident_id, "incident", client, "investigation_started", input_data=payload)
    try:
        state = await run_workflow(
            {"incident_id": incident_id, **payload, "window_start": window_start.timestamp(), "evidence": []},
            thread_id=incident_id,
        )
    except Exception as exc:
        audit(incident_id, "incident", "agent", "investigation_failed", ok=False, error=str(exc))
        raise HTTPException(status_code=500, detail=f"investigation failed: {exc}") from exc

    completed = datetime.now(timezone.utc)
    result = {
        "incident_id": incident_id,
        "status": "awaiting_approval",
        "title": req.title,
        "likely_root_cause": state.get("likely_root_cause", "Unknown"),
        "root_cause_service": state.get("root_cause_service", "unknown"),
        "failure_category": state.get("failure_category", "unknown"),
        "confidence": state.get("confidence", 0.0),
        "hypotheses": state.get("hypotheses", []),
        "recommended_action": state.get("recommended_action", {}),
        "timeline": state.get("timeline", []),
        "citations": list(dict.fromkeys(
            c for h in state.get("hypotheses", []) for c in h.get("supporting_citations", [])
        )),
        "report": state.get("report", ""),
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
    }
    save_result(incident_id, result, result["recommended_action"])
    return result


@app.get("/incidents/{incident_id}", dependencies=[Depends(authenticated_reader)])
def incident(incident_id: str):
    row = get_incident(incident_id)
    if not row:
        raise HTTPException(404, "incident not found")
    return row


@app.get("/incidents/{incident_id}/audit", dependencies=[Depends(authenticated_reader)])
def incident_audit(incident_id: str):
    if not get_incident(incident_id):
        raise HTTPException(404, "incident not found")
    return {"incident_id": incident_id, "events": audit_trail(incident_id)}


class Approval(BaseModel):
    approved: bool


@app.post("/incidents/{incident_id}/approval")
async def approve(incident_id: str, decision: Approval, actor: str = Depends(authenticated_approver)):
    if not get_incident(incident_id):
        raise HTTPException(404, "incident not found")
    # The approval check is server-side. The model cannot bypass it by writing "approved" in a prompt.
    row = claim_decision(incident_id, actor, "executing" if decision.approved else "rejected")
    if not row:
        raise HTTPException(409, f"incident status is {get_incident(incident_id)['status']}")
    if not decision.approved:
        audit(incident_id, "approval", actor, "action_rejected", output_data={"approved": False})
        return {"status": "rejected", "executed": False}

    action = row.get("proposed_action") or {}
    kind = action.get("kind", "unknown")
    audit(incident_id, "approval", actor, "action_approved", output_data=action)
    try:
        if kind == "github_issue":
            result = await create_github_issue(
                f"[OpsPilot] {row['title']}",
                (row.get("result") or {}).get("report", "Incident investigation"),
            )
        else:
            # Destructive rollback/config/code mutation is deliberately not wired into the MVP executor.
            # Approval records intent, while execution remains simulated until a policy-scoped deploy tool exists.
            result = {"simulated": True, "kind": kind, "description": action.get("description")}
    except Exception as exc:
        audit(incident_id, "action", "executor", kind, input_data=action, ok=False, error=str(exc))
        mark_approved(incident_id, actor, "action_failed")
        raise HTTPException(502, f"approved action failed: {exc}") from exc

    audit(incident_id, "action", "executor", kind, input_data=action, output_data=result)
    mark_approved(incident_id, actor, "action_executed" if not result.get("simulated") else "approved_simulation")
    return {"status": "approved", "executed": not result.get("simulated", False), "result": result}

@app.get("/evaluation/latest")
def evaluation_latest():
    path = Path(settings.repo_root) / "eval" / "results" / "latest.json"
    baseline = Path(settings.repo_root) / "eval" / "results" / "baseline-latest.json"
    payload = {"available": path.exists(), "evaluation": None, "baseline": None}
    if path.exists():
        import json
        payload["evaluation"] = json.loads(path.read_text())
    if baseline.exists():
        import json
        payload["baseline"] = json.loads(baseline.read_text())
    return payload
