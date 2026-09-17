import asyncio
from services.common.faults import FaultInjector


def test_fault_configuration_and_reset():
    f = FaultInjector()
    cfg = f.set(error_rate=2.0, latency_ms=-5, force_status=503)
    assert cfg["error_rate"] == 1.0
    assert cfg["latency_ms"] == 0
    assert cfg["force_status"] == 503
    assert f.reset()["force_status"] is None


def test_force_status_always_fails():
    f = FaultInjector()
    f.set(force_status=500)
    cfg = asyncio.run(f.before_request())
    assert f.should_fail(cfg)
