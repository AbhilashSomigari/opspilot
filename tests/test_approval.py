import pytest
from fastapi.testclient import TestClient

from agent.app import main
from agent.app.config import settings

TOKEN = "s3cret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
INCIDENT = {"id": "inc-1", "title": "t", "status": "awaiting_approval", "result": {}, "proposed_action": {"kind": "config_change"}}


@pytest.fixture
def api(monkeypatch):
    calls = {"claims": [], "audits": [], "statuses": []}

    def claim(incident_id, actor, status):
        calls["claims"].append((actor, status))
        return calls.get("claim_result", INCIDENT)

    monkeypatch.setattr(settings, "approver_tokens", {"alice@example.com": TOKEN})
    monkeypatch.setattr(main, "get_incident", lambda _id: INCIDENT)
    monkeypatch.setattr(main, "claim_decision", claim)
    monkeypatch.setattr(main, "audit", lambda *a, **k: calls["audits"].append(a[1:4]))
    monkeypatch.setattr(main, "mark_approved", lambda _id, actor, status: calls["statuses"].append(status))
    # Without a `with` block the app's startup (DB init, RAG ingestion) doesn't run.
    return TestClient(main.app), calls


def test_approvals_are_refused_when_no_approvers_are_configured(api, monkeypatch):
    client, calls = api
    monkeypatch.setattr(settings, "approver_tokens", {})
    assert client.post("/incidents/inc-1/approval", json={"approved": True}, headers=AUTH).status_code == 503
    assert calls["claims"] == []


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
def test_missing_or_wrong_token_is_rejected(api, headers):
    client, calls = api
    assert client.post("/incidents/inc-1/approval", json={"approved": True}, headers=headers).status_code == 401
    assert calls["claims"] == []


def test_actor_comes_from_the_token_not_the_body(api):
    client, calls = api
    r = client.post("/incidents/inc-1/approval", json={"approved": True, "actor": "mallory"}, headers=AUTH)
    assert r.status_code == 200
    assert calls["claims"] == [("alice@example.com", "executing")]
    assert ("approval", "alice@example.com", "action_approved") in calls["audits"]
    assert calls["statuses"] == ["approved_simulation"]


def test_losing_a_concurrent_claim_returns_409(api):
    client, calls = api
    calls["claim_result"] = None
    assert client.post("/incidents/inc-1/approval", json={"approved": True}, headers=AUTH).status_code == 409
    assert not any(a[0] == "action" for a in calls["audits"])


def test_failed_action_is_recorded_and_left_retryable(api, monkeypatch):
    client, calls = api
    calls["claim_result"] = {**INCIDENT, "proposed_action": {"kind": "github_issue"}}

    async def boom(*_):
        raise RuntimeError("GitHub API 503")

    monkeypatch.setattr(main, "create_github_issue", boom)
    assert client.post("/incidents/inc-1/approval", json={"approved": True}, headers=AUTH).status_code == 502
    assert calls["statuses"] == ["action_failed"]
