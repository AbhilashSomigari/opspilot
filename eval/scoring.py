"""Root-cause scoring shared by the agent eval and the no-tools baseline."""

from agent.app.models.schemas import FAILURE_CATEGORIES

__all__ = ["FAILURE_CATEGORIES", "root_cause_correct"]

# A mixed fault (latency plus errors) is correctly described as either.
_ACCEPTED = {"mixed": {"availability", "latency"}}


def root_cause_correct(case: dict, service: str, category: str) -> bool:
    # Both halves are structured answers: substring matching on prose scored "payment is failing;
    # catalog looks healthy" as a catalog diagnosis and failed "processing delay" for latency.
    accepted = _ACCEPTED.get(case["category"], {case["category"]})
    return service.strip().lower() == case["expected_service"] and category.strip().lower() in accepted
