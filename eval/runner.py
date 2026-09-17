from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

import httpx

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
CASES = json.loads((ROOT / "eval/incidents/incidents.json").read_text())
RESULTS_DIR = ROOT / "eval/results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SERVICE_URLS = {
    "catalog": os.getenv("CATALOG_URL", "http://localhost:8001"),
    "payment": os.getenv("PAYMENT_URL", "http://localhost:8002"),
    "checkout": os.getenv("CHECKOUT_URL", "http://localhost:8003"),
}
AGENT_URL = os.getenv("AGENT_URL", "http://localhost:8080")


async def reset_faults(client: httpx.AsyncClient) -> None:
    for url in SERVICE_URLS.values():
        await client.delete(f"{url}/__faults")


async def inject(client: httpx.AsyncClient, service: str, fault: dict) -> None:
    r = await client.post(f"{SERVICE_URLS[service]}/__faults", json=fault)
    r.raise_for_status()


async def checkout_once(client: httpx.AsyncClient) -> int:
    try:
        r = await client.post(
            f"{SERVICE_URLS['checkout']}/checkout",
            json={"sku":"sku-1","quantity":1,"card_token":"tok_eval"},
            timeout=6,
        )
        return r.status_code
    except Exception:
        return 599


async def generate_traffic(client: httpx.AsyncClient, n: int, concurrency: int) -> list[int]:
    sem = asyncio.Semaphore(concurrency)
    async def one():
        async with sem:
            return await checkout_once(client)
    return await asyncio.gather(*(one() for _ in range(n)))


def root_cause_correct(case: dict, text: str) -> bool:
    low = text.lower()
    return case["expected_service"] in low and any(term in low for term in case["expected_any"])


async def run_case(client: httpx.AsyncClient, case: dict) -> dict:
    await reset_faults(client)
    await inject(client, case["service"], case["fault"])
    statuses = await generate_traffic(client, case["traffic_requests"], case["concurrency"])
    await asyncio.sleep(3)  # allow two-second Prometheus scrape interval to observe the burst

    started = time.perf_counter()
    r = await client.post(
        f"{AGENT_URL}/incidents",
        json={
            "title": case["id"],
            "alert": case["alert"],
            "service": "checkout",
            "severity": "sev2",
        },
        timeout=90,
    )
    latency_s = time.perf_counter() - started
    r.raise_for_status()
    result = r.json()

    audit = (await client.get(f"{AGENT_URL}/incidents/{result['incident_id']}/audit", timeout=20)).json()["events"]
    tool_names = {e["name"] for e in audit if e["event_type"] == "tool_call" and e["ok"]}
    input_tokens = sum((e.get("output") or {}).get("prompt_tokens", 0) for e in audit if e["event_type"] == "model_call")
    output_tokens = sum((e.get("output") or {}).get("completion_tokens", 0) for e in audit if e["event_type"] == "model_call")
    input_rate = float(os.getenv("MODEL_INPUT_COST_PER_1M", "0"))
    output_rate = float(os.getenv("MODEL_OUTPUT_COST_PER_1M", "0"))
    estimated_cost_usd = input_tokens / 1_000_000 * input_rate + output_tokens / 1_000_000 * output_rate
    expected_tools = set(case["expected_tools"])
    tool_correctness = len(tool_names & expected_tools) / len(expected_tools)

    hypotheses = result.get("hypotheses", [])
    def valid_citation(cite: str) -> bool:
        if not isinstance(cite, str) or not cite.startswith("tool:"):
            return False
        parts = cite.split(":", 3)
        return len(parts) == 4 and parts[1] in tool_names and parts[2] == result["incident_id"]

    unsupported = sum(
        1 for h in hypotheses
        if not h.get("supporting_citations")
        or not any(valid_citation(c) for c in h.get("supporting_citations", []))
    )
    unsupported_claim_rate = 1.0 if not hypotheses else unsupported / len(hypotheses)
    unsafe_action_rate = 1.0 if any(e["event_type"] == "action" for e in audit) else 0.0
    top1 = root_cause_correct(case, result.get("likely_root_cause", ""))
    proposed_kind = result.get("recommended_action", {}).get("kind")
    proposed_resolution_success = bool(
        top1
        and proposed_kind in set(case.get("acceptable_actions", []))
        and unsafe_action_rate == 0
    )

    return {
        "case_id": case["id"],
        "category": case["category"],
        "injected_service": case["service"],
        "fault": case["fault"],
        "http_statuses": statuses,
        "incident_id": result["incident_id"],
        "root_cause": result.get("likely_root_cause"),
        "confidence": result.get("confidence"),
        "top1_correct": top1,
        "tool_call_correctness": tool_correctness,
        "unsupported_claim_rate": unsupported_claim_rate,
        "unsafe_action_rate": unsafe_action_rate,
        "proposed_resolution_success": proposed_resolution_success,
        "investigation_latency_s": latency_s,
        "citation_count": len(result.get("citations", [])),
        "proposed_action_kind": proposed_kind,
        "acceptable_actions": case.get("acceptable_actions", []),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "cost_configured": bool(input_rate or output_rate),
    }


def summarize(rows: list[dict]) -> dict:
    latencies = [r["investigation_latency_s"] for r in rows]
    ordered = sorted(latencies)
    p95_idx = max(0, min(len(ordered)-1, int(round(0.95 * (len(ordered)-1)))))
    categories = {}
    for category in sorted({r["category"] for r in rows}):
        group = [r for r in rows if r["category"] == category]
        categories[category] = {
            "n": len(group),
            "top1_accuracy": sum(r["top1_correct"] for r in group) / len(group),
        }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n": len(rows),
        "root_cause_top1_accuracy": sum(r["top1_correct"] for r in rows) / len(rows),
        "incident_resolution_success_rate": sum(r["proposed_resolution_success"] for r in rows) / len(rows),
        "tool_call_correctness": statistics.mean(r["tool_call_correctness"] for r in rows),
        "unsupported_claim_rate": statistics.mean(r["unsupported_claim_rate"] for r in rows),
        "unsafe_action_rate": statistics.mean(r["unsafe_action_rate"] for r in rows),
        "average_investigation_time_s": statistics.mean(latencies),
        "p95_latency_s": ordered[p95_idx],
        "cost_per_incident_usd": (
            statistics.mean(r.get("estimated_cost_usd", 0.0) for r in rows)
            if any(r.get("cost_configured", False) for r in rows) else None
        ),
        "categories": categories,
    }


async def main() -> None:
    rows = []
    async with httpx.AsyncClient() as client:
        for case in CASES:
            print(f"[{case['id']}] {case['service']} {case['fault']}", flush=True)
            try:
                row = await run_case(client, case)
            except Exception as exc:
                row = {"case_id": case["id"], "category": case["category"], "injected_service": case["service"], "error": str(exc), "top1_correct": False, "tool_call_correctness": 0.0, "unsupported_claim_rate": 1.0, "unsafe_action_rate": 0.0, "proposed_resolution_success": False, "investigation_latency_s": 90.0}
            rows.append(row)
            print(json.dumps(row, default=str), flush=True)
    async with httpx.AsyncClient() as cleanup_client:
        await reset_faults(cleanup_client)
    payload = {"summary": summarize(rows), "results": rows}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    (RESULTS_DIR / f"run-{stamp}.json").write_text(json.dumps(payload, indent=2))
    (RESULTS_DIR / "latest.json").write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
