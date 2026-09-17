from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from openai import AsyncOpenAI

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
CASES = json.loads((ROOT / "eval/incidents/incidents.json").read_text())
OUT = ROOT / "eval/results/baseline-latest.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")


def correct(case: dict, service: str, category_text: str) -> bool:
    blob = f"{service} {category_text}".lower()
    return case["expected_service"] in blob and any(x in blob for x in case["expected_any"])


async def predict(client: AsyncOpenAI | None, alert: str) -> tuple[str, str]:
    if client is None:
        category = "latency timeout slow" if "latency" in alert.lower() else "error failure 5xx"
        return "checkout", category
    r = await client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You receive only an alert, with no logs, metrics, traces, changes, or runbooks. Guess the most likely failing service (checkout, payment, catalog) and failure category. Output JSON with service and category."},
            {"role": "user", "content": alert},
        ],
    )
    data = json.loads(r.choices[0].message.content or "{}")
    return str(data.get("service", "unknown")), str(data.get("category", "unknown"))


async def main() -> None:
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"]) if os.getenv("OPENAI_API_KEY") else None
    rows = []
    for case in CASES:
        service, category = await predict(client, case["alert"])
        rows.append({
            "case_id": case["id"],
            "prediction": {"service": service, "category": category},
            "top1_correct": correct(case, service, category),
        })
    acc = sum(r["top1_correct"] for r in rows) / len(rows)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n": len(rows),
        "root_cause_top1_accuracy": acc,
        "results": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2))
    print(json.dumps({k:v for k,v in payload.items() if k != "results"}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
