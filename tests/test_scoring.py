from eval.scoring import root_cause_correct

CASE = {"expected_service": "catalog", "expected_any": ["error", "503"]}


def test_requires_the_structured_service_not_a_mention():
    assert not root_cause_correct(CASE, "payment", "payment errors; catalog looks healthy")


def test_accepts_matching_service_and_category_term():
    assert root_cause_correct(CASE, "Catalog", "catalog returns 503 to checkout")


def test_rejects_matching_service_with_wrong_category():
    assert not root_cause_correct(CASE, "catalog", "catalog p95 latency regression")
