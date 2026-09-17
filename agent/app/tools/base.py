from __future__ import annotations

from typing import Any, Awaitable, Callable

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..db import audit


async def audited_tool(
    incident_id: str,
    name: str,
    payload: dict[str, Any],
    fn: Callable[..., Awaitable[Any]],
) -> Any:
    audit(incident_id, "tool_call", "agent", name, input_data=payload)
    last_error: Exception | None = None
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                try:
                    result = await fn(**payload)
                    audit(
                        incident_id,
                        "tool_result",
                        "tool",
                        name,
                        output_data={"attempt": attempt.retry_state.attempt_number, "result": result},
                    )
                    return result
                except Exception as exc:
                    last_error = exc
                    audit(
                        incident_id,
                        "tool_retry",
                        "tool",
                        name,
                        input_data={"attempt": attempt.retry_state.attempt_number},
                        ok=False,
                        error=str(exc),
                    )
                    raise
    except Exception as exc:
        last_error = exc
    error = str(last_error or "tool failed")
    audit(incident_id, "tool_result", "tool", name, ok=False, error=error)
    return {"error": error, "tool": name, "retries_exhausted": True}
