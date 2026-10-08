from agent.app.graph.workflow import _fallback_reason


def _metrics(service, error_rate):
    result = [{"value": [0, str(error_rate)]}]
    return {
        "source": "get_metrics",
        "citation": f"tool:get_metrics:{service}",
        "data": {"service": service, "results": {"error_rate": {"result": result}, "p95_latency": {"result": []}}},
    }


def _changes(service, deployed_at):
    return {
        "source": "get_changes",
        "citation": f"tool:get_changes:{service}",
        "data": {"service": service, "deployments": [{"service": service, "deployed_at": deployed_at}]},
    }


STATE = {"service": "checkout", "alert": "Checkout error rate up", "window_start": 1_800_000_000}


def test_rolls_back_when_the_failing_service_just_changed():
    out = _fallback_reason({**STATE, "evidence": [_metrics("catalog", 0.9), _changes("catalog", "2027-01-15T08:00:00+00:00")]})
    assert (out["root_cause_service"], out["failure_category"]) == ("catalog", "availability")
    assert out["recommended_action"]["kind"] == "rollback"


def test_opens_an_issue_when_only_old_changes_exist():
    out = _fallback_reason({**STATE, "evidence": [_metrics("catalog", 0.9), _changes("catalog", "2026-09-10T12:00:00Z")]})
    assert out["recommended_action"]["kind"] == "github_issue"
