"""Timings must remain isolated, numeric and unable to alter return/error behavior."""
import asyncio
import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.services.performance import metric, timed, trace


def test_numeric_only_and_disabled_by_default():
    assert trace.get() is None
    metric("disabled", text="never record")
    state = {"start": time.perf_counter(), "stages": []}
    token = trace.set(state)
    try:
        metric("test", duration_ms=12.3456, answer="private", jwt="secret", audio=b"data")
        assert state["stages"][0] == {"stage": "test", "at_ms": state["stages"][0]["at_ms"], "duration_ms": 12.35}
    finally:
        trace.reset(token)


def test_concurrent_spans_are_request_local_and_errors_propagate():
    @timed("work")
    async def work(fail):
        await asyncio.sleep(0)
        if fail:
            raise ValueError("expected")
        return 42
    async def run(fail):
        state = {"start": time.perf_counter(), "stages": []}
        token = trace.set(state)
        try:
            if fail:
                with pytest.raises(ValueError):
                    await work(True)
            else:
                assert await work(False) == 42
            return state
        finally:
            trace.reset(token)
    async def pair():
        return await asyncio.gather(run(False), run(True))
    states = asyncio.run(pair())
    assert states[0] is not states[1]
    assert all([s["stage"] for s in state["stages"]] == ["work.start", "work"] for state in states)
    assert trace.get() is None


def test_diagnostics_do_not_bypass_auth_and_are_opt_in(caplog):
    client = TestClient(app)
    for enabled in (False, True):
        with patch.object(settings, "PERFORMANCE_DIAGNOSTICS", enabled):
            response = client.post('/api/v1/interview/start', json={})
        assert response.status_code == 401
        assert ("server-timing" in response.headers) is enabled
    assert 'request_id' in caplog.text
    assert 'Bearer' not in caplog.text
