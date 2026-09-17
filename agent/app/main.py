from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .config import settings
from .db import audit, audit_trail, create_incident, get_incident, init_db, mark_approved, save_result
from .graph.workflow import run_workflow
from .models.schemas import IncidentRequest
from .rag.hybrid import ingest_paths
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


@app.post("/incidents")
async def investigate(req: IncidentRequest):
    incident_id = f"inc-{uuid.uuid4().hex[:10]}"
    started = datetime.now(timezone.utc)
    payload = req.model_dump()
    create_incident(incident_id, payload)
    audit(incident_id, "incident", "user", "investigation_started", input_data=payload)
    try:
        state = await run_workflow({"incident_id": incident_id, **payload, "evidence": []}, thread_id=incident_id)
    except Exception as exc:
        audit(incident_id, "incident", "agent", "investigation_failed", ok=False, error=str(exc))
        raise HTTPException(status_code=500, detail=f"investigation failed: {exc}") from exc

    completed = datetime.now(timezone.utc)
    result = {
        "incident_id": incident_id,
        "status": "awaiting_approval",
        "title": req.title,
        "likely_root_cause": state.get("likely_root_cause", "Unknown"),
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


@app.get("/incidents/{incident_id}")
def incident(incident_id: str):
    row = get_incident(incident_id)
    if not row:
        raise HTTPException(404, "incident not found")
    return row


@app.get("/incidents/{incident_id}/audit")
def incident_audit(incident_id: str):
    if not get_incident(incident_id):
        raise HTTPException(404, "incident not found")
    return {"incident_id": incident_id, "events": audit_trail(incident_id)}


class Approval(BaseModel):
    approved: bool
    actor: str


@app.post("/incidents/{incident_id}/approval")
async def approve(incident_id: str, decision: Approval):
    row = get_incident(incident_id)
    if not row:
        raise HTTPException(404, "incident not found")
    if row["status"] not in {"awaiting_approval", "approved"}:
        raise HTTPException(409, f"incident status is {row['status']}")
    if not decision.approved:
        mark_approved(incident_id, decision.actor, "rejected")
        audit(incident_id, "approval", decision.actor, "action_rejected", output_data={"approved": False})
        return {"status": "rejected", "executed": False}

    # The approval check is server-side. The model cannot bypass it by writing "approved" in a prompt.
    action = row.get("proposed_action") or {}
    audit(incident_id, "approval", decision.actor, "action_approved", output_data=action)
    mark_approved(incident_id, decision.actor, "approved")

    if action.get("kind") == "github_issue":
        result = await create_github_issue(
            f"[OpsPilot] {row['title']}",
            (row.get("result") or {}).get("report", "Incident investigation"),
        )
    else:
        # Destructive rollback/config/code mutation is deliberately not wired into the MVP executor.
        # Approval records intent, while execution remains simulated until a policy-scoped deploy tool exists.
        result = {"simulated": True, "kind": action.get("kind"), "description": action.get("description")}

    audit(incident_id, "action", "executor", action.get("kind", "unknown"), input_data=action, output_data=result)
    mark_approved(incident_id, decision.actor, "action_executed" if not result.get("simulated") else "approved_simulation")
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
