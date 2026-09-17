from __future__ import annotations

import asyncio
import random
from dataclasses import asdict, dataclass
from threading import Lock


@dataclass
class FaultConfig:
    error_rate: float = 0.0
    latency_ms: int = 0
    force_status: int | None = None
    corrupt_response: bool = False


class FaultInjector:
    def __init__(self) -> None:
        self._config = FaultConfig()
        self._lock = Lock()

    def get(self) -> dict:
        with self._lock:
            return asdict(self._config)

    def set(self, **changes) -> dict:
        with self._lock:
            data = asdict(self._config)
            for key, value in changes.items():
                if value is not None and key in data:
                    data[key] = value
            data["error_rate"] = min(1.0, max(0.0, float(data["error_rate"])))
            data["latency_ms"] = max(0, int(data["latency_ms"]))
            self._config = FaultConfig(**data)
            return asdict(self._config)

    def reset(self) -> dict:
        with self._lock:
            self._config = FaultConfig()
            return asdict(self._config)

    async def before_request(self) -> FaultConfig:
        with self._lock:
            cfg = FaultConfig(**asdict(self._config))
        if cfg.latency_ms:
            await asyncio.sleep(cfg.latency_ms / 1000)
        return cfg

    @staticmethod
    def should_fail(cfg: FaultConfig) -> bool:
        return cfg.force_status is not None or random.random() < cfg.error_rate
