from eval.scoring import root_cause_correct

CASE = {"expected_service": "catalog", "category": "availability"}


def test_requires_the_structured_service_not_a_mention():
    assert not root_cause_correct(CASE, "payment", "availability")


def test_accepts_matching_service_and_category():
    assert root_cause_correct(CASE, "Catalog", "availability")


def test_rejects_matching_service_with_wrong_category():
    assert not root_cause_correct(CASE, "catalog", "latency")


def test_mixed_faults_accept_either_symptom():
    mixed = {"expected_service": "payment", "category": "mixed"}
    assert root_cause_correct(mixed, "payment", "latency")
    assert root_cause_correct(mixed, "payment", "availability")
    assert not root_cause_correct(mixed, "payment", "data_contract")
