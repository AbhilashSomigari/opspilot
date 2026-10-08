"""Root-cause scoring shared by the agent eval and the no-tools baseline."""


def root_cause_correct(case: dict, service: str, description: str) -> bool:
    # The failing service must be the structured answer, not merely mentioned in prose:
    # a substring match scored "payment is failing; catalog looks healthy" as a catalog diagnosis.
    low = description.lower()
    return service.strip().lower() == case["expected_service"] and any(
        term in low for term in case["expected_any"]
    )
