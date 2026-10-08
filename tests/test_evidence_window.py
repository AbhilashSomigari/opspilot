import json

from agent.app.llm import sampling_kwargs_for
from agent.app.tools.logs import _parse_lines


def test_log_entries_before_the_window_are_dropped():
    lines = [json.dumps({"ts": ts, "message": f"m{ts}"}) for ts in (90, 100, 110)]
    entries = _parse_lines(lines, "", limit=10, since=100)
    assert [e["ts"] for e in entries] == [100, 110]


def test_undated_lines_are_kept():
    assert _parse_lines(["plain text"], "", limit=10, since=100) == [{"raw": "plain text"}]


def test_reasoning_models_get_default_temperature():
    assert sampling_kwargs_for("gpt-5-mini") == {}
    assert sampling_kwargs_for("o3") == {}
    assert sampling_kwargs_for("gpt-4.1") == {"temperature": 0}


def test_unmatched_filter_falls_back_to_error_entries():
    from agent.app.tools.logs import _select_entries

    lines = [
        json.dumps({"ts": 100, "level": "INFO", "message": "request_complete", "status": 200}),
        json.dumps({"ts": 101, "level": "ERROR", "message": "invalid_charge_amount", "status": 400}),
    ]
    out = _select_entries(lines, "502", limit=10, since=0)
    assert [e["message"] for e in out["entries"]] == ["invalid_charge_amount"]
    assert "502" in out["note"]
    assert "note" not in _select_entries(lines, "invalid", limit=10, since=0)
