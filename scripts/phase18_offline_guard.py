"""Pytest plugin: selected Phase 18 regressions cannot open network connections."""
import socket
import sys

_connect = socket.socket.connect
_socketpair_code = getattr(getattr(socket, "_fallback_socketpair", None), "__code__", None)


def _guard_connect(self, *args, **kwargs):
    # Windows implements asyncio's private socketpair via a loopback connection.
    # Permit only the stdlib socketpair call site, not arbitrary localhost HTTP.
    if _socketpair_code is not None and sys._getframe(1).f_code is _socketpair_code:
        return _connect(self, *args, **kwargs)
    return _deny_network()


def _deny_network(*args, **kwargs):
    raise AssertionError("External socket connections are forbidden in Phase 18 offline checks")


def pytest_sessionstart(session):
    socket.socket.connect = _guard_connect
    socket.socket.connect_ex = _deny_network
