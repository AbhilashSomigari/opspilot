import json
from types import SimpleNamespace

import pytest

from agent.app.graph import workflow
from agent.app.graph.workflow import CATEGORY_ANSWERS, SERVICE_ANSWERS, _enum_answer


@pytest.mark.parametrize("value,expected", [
    ("availability", "availability"),
    # Verbatim from eval run 3 (EVAL-010): the model copied the field description back.
    ("availability: the origin returns errors (catalog returning 429 Too Many Requests)", "availability"),
    ("Data_Contract", "data_contract"),
    ("timeouts", "unknown"),
    (None, "unknown"),
    ("", "unknown"),
])
def test_category_answers_are_reduced_to_a_valid_word(value, expected):
    assert _enum_answer(value, CATEGORY_ANSWERS) == expected


def test_service_answers_are_validated():
    assert _enum_answer("Catalog service", SERVICE_ANSWERS) == "catalog"
    assert _enum_answer("database", SERVICE_ANSWERS) == "unknown"


def _model_returning(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    response = SimpleNamespace(usage=None, choices=[SimpleNamespace(message=message)])

    async def create(**_):
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


STATE = {"incident_id": "inc-1", "alert": "a", "service": "checkout", "evidence": []}


@pytest.fixture
def audits(monkeypatch):
    events = []
    monkeypatch.setattr(workflow, "llm_available", lambda: True)
    monkeypatch.setattr(workflow, "audit", lambda *a, **k: events.append((a[3], k)))
    return events


async def test_prose_answers_are_repaired_and_audited(monkeypatch, audits):
    monkeypatch.setattr(workflow, "llm_client", lambda: _model_returning(
        {"root_cause_service": "catalog", "failure_category": "availability: the origin returns errors"}))
    out = await workflow.reason(STATE)
    assert (out["root_cause_service"], out["failure_category"]) == ("catalog", "availability")
    repairs = [k for name, k in audits if name == "output_repaired"]
    assert repairs == [{"input_data": {"failure_category": "availability: the origin returns errors"},
                        "output_data": {"failure_category": "availability"}}]


async def test_missing_answers_become_unknown(monkeypatch, audits):
    monkeypatch.setattr(workflow, "llm_client", lambda: _model_returning({}))
    out = await workflow.reason(STATE)
    assert (out["root_cause_service"], out["failure_category"]) == ("unknown", "unknown")


async def test_valid_answers_are_not_reported_as_repairs(monkeypatch, audits):
    monkeypatch.setattr(workflow, "llm_client", lambda: _model_returning(
        {"root_cause_service": "payment", "failure_category": "latency"}))
    await workflow.reason(STATE)
    assert not any(name == "output_repaired" for name, _ in audits)
