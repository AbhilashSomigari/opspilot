import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.common.faults import FaultInjector
from services.common.observability import instrument_app

app = FastAPI(title="OpsPilot Checkout", version="0.1.0")
faults = FaultInjector()
logger = instrument_app(app, "checkout")

CATALOG_URL = os.getenv("CATALOG_URL", "http://catalog:8000")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://payment:8000")

class Order(BaseModel):
    sku: str = "sku-1"
    quantity: int = 1
    card_token: str = "tok_demo"

class FaultPatch(BaseModel):
    error_rate: float | None = None
    latency_ms: int | None = None
    force_status: int | None = None
    corrupt_response: bool | None = None

@app.get("/health")
def health():
    return {"ok": True, "service": "checkout"}

@app.post("/checkout")
async def checkout(order: Order):
    cfg = await faults.before_request()
    if faults.should_fail(cfg):
        logger.error("injected_failure", extra={"service":"checkout", "fault": faults.get(), "status": cfg.force_status or 500})
        raise HTTPException(status_code=cfg.force_status or 500, detail="checkout injected failure")

    timeout = httpx.Timeout(2.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            catalog = await client.get(f"{CATALOG_URL}/products/{order.sku}")
            catalog.raise_for_status()
            item = catalog.json()
            amount = item["price"] * order.quantity
            payment = await client.post(
                f"{PAYMENT_URL}/charge",
                json={"amount": amount, "card_token": order.card_token},
            )
            payment.raise_for_status()
        except httpx.TimeoutException as exc:
            logger.error("dependency_timeout", extra={"service":"checkout", "status":504})
            raise HTTPException(status_code=504, detail=f"dependency timeout: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            logger.error("dependency_failure", extra={"service":"checkout", "status":502})
            raise HTTPException(status_code=502, detail=f"dependency failure: {exc.response.text}") from exc

    if cfg.corrupt_response:
        return {"status": "ok", "order_id": None, "charged": amount}
    return {"status": "ok", "order_id": "ord-demo", "charged": amount}

@app.get("/__faults")
def get_faults():
    return faults.get()

@app.post("/__faults")
def set_faults(patch: FaultPatch):
    return faults.set(**patch.model_dump(exclude_unset=True))

@app.delete("/__faults")
def reset_faults():
    return faults.reset()
