from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.common.faults import FaultInjector
from services.common.observability import instrument_app

app = FastAPI(title="OpsPilot Catalog", version="0.1.0")
faults = FaultInjector()
logger = instrument_app(app, "catalog")

PRODUCTS = {
    "sku-1": {"name": "Mechanical Keyboard", "price": 129.0, "stock": 12},
    "sku-2": {"name": "USB-C Dock", "price": 89.0, "stock": 7},
}

class FaultPatch(BaseModel):
    error_rate: float | None = None
    latency_ms: int | None = None
    force_status: int | None = None
    corrupt_response: bool | None = None

@app.get("/health")
def health():
    return {"ok": True, "service": "catalog"}

@app.get("/products/{sku}")
async def product(sku: str):
    cfg = await faults.before_request()
    if faults.should_fail(cfg):
        logger.error("injected_failure", extra={"service":"catalog", "fault": faults.get(), "status": cfg.force_status or 503})
        raise HTTPException(status_code=cfg.force_status or 503, detail="catalog injected failure")
    if sku not in PRODUCTS:
        raise HTTPException(status_code=404, detail="unknown sku")
    item = dict(PRODUCTS[sku])
    if cfg.corrupt_response:
        logger.error("invalid_catalog_price_injected", extra={"service":"catalog", "fault": faults.get()})
        item["price"] = -1
    return {"sku": sku, **item}

@app.get("/__faults")
def get_faults():
    return faults.get()

@app.post("/__faults")
def set_faults(patch: FaultPatch):
    return faults.set(**patch.model_dump(exclude_unset=True))

@app.delete("/__faults")
def reset_faults():
    return faults.reset()
