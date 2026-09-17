from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from fastapi import FastAPI, Request
from prometheus_client import Counter, Histogram, make_asgi_app

REQUESTS = Counter(
    "opspilot_http_requests_total",
    "HTTP requests",
    ["service", "method", "path", "status"],
)
LATENCY = Histogram(
    "opspilot_http_request_duration_seconds",
    "HTTP request latency",
    ["service", "method", "path"],
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.time(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key in ("service", "path", "status", "trace_id", "fault"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, separators=(",", ":"))


def configure_logging(service: str) -> logging.Logger:
    logger = logging.getLogger(service)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = JsonFormatter()
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    logger.addHandler(stdout)

    log_dir = Path(os.getenv("LOG_DIR", "/tmp/opspilot-logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / f"{service}.jsonl")
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    return logger


def instrument_app(app: FastAPI, service: str) -> logging.Logger:
    app.mount("/metrics", make_asgi_app())
    logger = configure_logging(service)

    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry import trace

        provider = TracerProvider(resource=Resource.create({"service.name": service}))
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://jaeger:4318").rstrip("/") + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        HTTPXClientInstrumentor().instrument()
    except Exception as exc:
        logger.warning("otel_init_failed:%s", exc)

    @app.middleware("http")
    async def metrics_and_logs(request: Request, call_next):
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - started
            path = request.url.path
            REQUESTS.labels(service, request.method, path, str(status)).inc()
            LATENCY.labels(service, request.method, path).observe(elapsed)
            logger.info(
                "request_complete",
                extra={"service": service, "path": path, "status": status},
            )

    return logger
