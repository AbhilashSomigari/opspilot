import json
from pathlib import Path


def test_exactly_30_reproducible_cases():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "eval/incidents/incidents.json").read_text())
    assert len(cases) == 30
    assert len({c["id"] for c in cases}) == 30
    for c in cases:
        assert c["service"] in {"checkout", "payment", "catalog"}
        assert c["fault"]
        assert c["expected_tools"]
