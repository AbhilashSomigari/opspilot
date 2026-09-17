from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.common.faults import FaultInjector
from services.common.observability import instrument_app

app = FastAPI(title="OpsPilot Payment", version="0.1.0")
faults = FaultInjector()
logger = instrument_app(app, "payment")

class Charge(BaseModel):
    amount: float
    card_token: str

class FaultPatch(BaseModel):
    error_rate: float | None = None
    latency_ms: int | None = None
    force_status: int | None = None
    corrupt_response: bool | None = None

@app.get("/health")
def health():
    return {"ok": True, "service": "payment"}

@app.post("/charge")
async def charge(req: Charge):
    cfg = await faults.before_request()
    if faults.should_fail(cfg):
        logger.error("injected_failure", extra={"service":"payment", "fault": faults.get(), "status": cfg.force_status or 502})
        raise HTTPException(status_code=cfg.force_status or 502, detail="payment processor injected failure")
    if req.amount <= 0:
        logger.error("invalid_charge_amount", extra={"service":"payment", "status": 400})
        raise HTTPException(status_code=400, detail="invalid amount")
    return {"status": "charged", "transaction_id": "txn-demo", "amount": req.amount}

@app.get("/__faults")
def get_faults():
    return faults.get()

@app.post("/__faults")
def set_faults(patch: FaultPatch):
    return faults.set(**patch.model_dump(exclude_unset=True))

@app.delete("/__faults")
def reset_faults():
    return faults.reset()
