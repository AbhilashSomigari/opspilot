import json
from types import SimpleNamespace

from agent.app.graph import tool_agent


def _call(name, service):
    fn = SimpleNamespace(name=name, arguments=json.dumps({"service": service}))
    return SimpleNamespace(id=f"{name}-{service}", function=fn)


def _response(calls):
    message = SimpleNamespace(tool_calls=calls, model_dump=lambda **_: {"role": "assistant"})
    return SimpleNamespace(usage=None, choices=[SimpleNamespace(message=message)])


class _FakeClient:
    """Replays scripted turns and records what the agent sent."""

    def __init__(self, turns):
        self.turns = iter(turns)
        self.sent = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, messages, **_):
        self.sent.append(list(messages))
        return _response(next(self.turns))


async def _fake_dispatch(incident_id, name, args, since):
    return {"source": name, "data": {}, "citation": f"tool:{name}:{args.get('service')}"}


def _patch(monkeypatch, client):
    monkeypatch.setattr(tool_agent, "llm_available", lambda: True)
    monkeypatch.setattr(tool_agent, "llm_client", lambda: client)
    monkeypatch.setattr(tool_agent, "audit", lambda *a, **k: None)
    monkeypatch.setattr(tool_agent, "_dispatch", _fake_dispatch)


def _full_coverage(services):
    return [_call(tool, svc) for svc in services for tool in tool_agent.REQUIRED_PER_SERVICE]


async def test_stopping_early_triggers_one_coverage_nudge(monkeypatch):
    client = _FakeClient([
        _full_coverage(["checkout"]),
        [],  # tries to conclude without looking at dependencies
        _full_coverage(["catalog", "payment"]),
        [],
    ])
    _patch(monkeypatch, client)
    evidence = await tool_agent.investigate_with_tools("inc-1", "alert", "checkout", since=0.0)

    nudge = client.sent[2][-1]
    assert nudge["role"] == "user"
    assert "get_metrics(catalog)" in nudge["content"] and "get_changes(payment)" in nudge["content"]
    assert "checkout)" not in nudge["content"]
    assert len(evidence) == 9


async def test_nudges_at_most_once(monkeypatch):
    client = _FakeClient([[], []])
    _patch(monkeypatch, client)
    await tool_agent.investigate_with_tools("inc-1", "alert", "checkout", since=0.0)
    assert len(client.sent) == 2


def test_failing_path_follows_dependencies():
    assert tool_agent.failing_path("checkout") == ["checkout", "catalog", "payment"]
    assert tool_agent.failing_path("payment") == ["payment"]
