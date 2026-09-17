from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field


class IncidentRequest(BaseModel):
    title: str
    alert: str
    service: str = "checkout"
    severity: Literal["sev1", "sev2", "sev3"] = "sev2"


class Evidence(BaseModel):
    source: str
    summary: str
    data: Any = None
    citation: str


class Hypothesis(BaseModel):
    cause: str
    confidence: float = Field(ge=0, le=1)
    supporting_citations: list[str] = []
    contradicting_citations: list[str] = []


class ActionProposal(BaseModel):
    kind: Literal["rollback", "config_change", "code_fix", "github_issue", "none"]
    description: str
    risk: Literal["low", "medium", "high"] = "medium"
    requires_approval: bool = True
    payload: dict[str, Any] = {}


class InvestigationResult(BaseModel):
    incident_id: str
    status: str
    title: str
    likely_root_cause: str
    confidence: float
    hypotheses: list[Hypothesis]
    recommended_action: ActionProposal
    timeline: list[str]
    citations: list[str]
    report: str
    started_at: datetime
    completed_at: datetime
