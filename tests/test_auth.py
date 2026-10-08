import pytest
from fastapi.testclient import TestClient

from agent.app import main
from agent.app.config import settings

CLIENT, APPROVER = "client-token", "approver-token"
INCIDENT = {"id": "inc-1", "status": "awaiting_approval", "title": "t", "result": {}, "proposed_action": {}}
CHANGE = {"service": "payment", "version": "v", "sha": "abc1234", "change": "config rollout",
          "deployed_at": "2026-10-08T03:00:00Z"}


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_tokens", {"eval-runner": CLIENT})
    monkeypatch.setattr(settings, "approver_tokens", {"alice@example.com": APPROVER})
    monkeypatch.setattr(main, "get_incident", lambda _id: INCIDENT)
    monkeypatch.setattr(main, "audit_trail", lambda _id: [])
    monkeypatch.setattr(main, "record_change", lambda event: {"id": 1})
    # Without a `with` block the app's startup (DB init, RAG ingestion) doesn't run.
    return TestClient(main.app)


PROTECTED = [
    ("post", "/changes", CHANGE),
    ("post", "/incidents", {"title": "t", "alert": "a"}),
    ("get", "/incidents/inc-1", None),
    ("get", "/incidents/inc-1/audit", None),
]


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_protected_routes_reject_missing_and_wrong_tokens(client, method, path, body):
    for headers in ({}, bearer("wrong")):
        assert client.request(method, path, json=body, headers=headers).status_code == 401


@pytest.mark.parametrize("method,path,body", PROTECTED)
def test_routes_fail_closed_without_configured_tokens(client, monkeypatch, method, path, body):
    monkeypatch.setattr(settings, "api_tokens", {})
    monkeypatch.setattr(settings, "approver_tokens", {})
    assert client.request(method, path, json=body, headers=bearer(CLIENT)).status_code == 503


def test_client_token_can_record_changes(client):
    assert client.post("/changes", json=CHANGE, headers=bearer(CLIENT)).status_code == 201


def test_investigation_is_attributed_to_the_calling_client(client, monkeypatch):
    audits = []

    async def finished(state, thread_id):
        return state

    monkeypatch.setattr(main, "create_incident", lambda *a: None)
    monkeypatch.setattr(main, "save_result", lambda *a: None)
    monkeypatch.setattr(main, "run_workflow", finished)
    monkeypatch.setattr(main, "audit", lambda *a, **k: audits.append(a[1:4]))
    r = client.post("/incidents", json={"title": "t", "alert": "a"}, headers=bearer(CLIENT))
    assert r.status_code == 200
    assert ("incident", "eval-runner", "investigation_started") in audits


@pytest.mark.parametrize("token", [CLIENT, APPROVER])
def test_clients_and_approvers_can_read_incidents(client, token):
    assert client.get("/incidents/inc-1", headers=bearer(token)).status_code == 200
    assert client.get("/incidents/inc-1/audit", headers=bearer(token)).status_code == 200


def test_roles_do_not_overlap(client):
    assert client.post("/changes", json=CHANGE, headers=bearer(APPROVER)).status_code == 401
    assert client.post("/incidents/inc-1/approval", json={"approved": True}, headers=bearer(CLIENT)).status_code == 401


def test_health_and_evaluation_summary_stay_public(client):
    assert client.get("/health").status_code == 200
    assert client.get("/evaluation/latest").status_code == 200
