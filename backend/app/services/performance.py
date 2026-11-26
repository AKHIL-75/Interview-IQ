"""Opt-in request timings. Never collect request bodies, headers, row IDs or text."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import time

trace = ContextVar("performance_trace", default=None)


def metric(stage, **numbers):
    current = trace.get()
    if current is not None:
        current["stages"].append({"stage": stage, "at_ms": round((time.perf_counter() - current["start"]) * 1000, 2),
                                  **{k: round(v, 2) for k, v in numbers.items() if isinstance(v, (int, float))}})


@contextmanager
def span(stage):
    start = time.perf_counter()
    metric(stage + ".start")
    try:
        yield
    finally:
        metric(stage, duration_ms=(time.perf_counter() - start) * 1000)


def timed(stage):
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def asynchronous(*args, **kwargs):
                with span(stage):
                    return await fn(*args, **kwargs)
            return asynchronous
        @wraps(fn)
        def synchronous(*args, **kwargs):
            with span(stage):
                return fn(*args, **kwargs)
        return synchronous
    return decorate
