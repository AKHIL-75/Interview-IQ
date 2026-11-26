"""Bounded local protection; run Uvicorn with --no-proxy-headers for direct peers.

This middleware never reads forwarded headers, but the ASGI server can rewrite
scope['client'] before middleware executes. Configure proxy trust at the server.
"""
import time
from collections import OrderedDict, deque

from app.core.exceptions import problem

GUEST_INFERENCE_PATHS = frozenset({
    "/ai/test", "/resume/parse", "/job/parse", "/analysis/match",
    "/interview/generate-questions", "/evaluation/evaluate",
})
INFERENCE_PATHS = GUEST_INFERENCE_PATHS | {"/interview/start", "/interview/next-question"}
GUEST_CAPABLE_PATHS = GUEST_INFERENCE_PATHS | {"/interview/generate-report"}
EXPENSIVE_PATHS = GUEST_CAPABLE_PATHS | {
    "/interview/start", "/interview/next-question", "/audio/transcribe",
    "/interview/report", "/speech/synthesize", "/speech/stt-token",
}


class LocalRateLimiter:
    def __init__(self, limit=30, window=60, capacity=4096, clock=time.monotonic):
        self.limit, self.window, self.capacity, self.clock = limit, window, capacity, clock
        self.clients = OrderedDict()

    def retry_after(self, peer):
        now = self.clock()
        # Ordered by last use, with bounded memory even for arbitrary peer IPs.
        while self.clients:
            key, events = next(iter(self.clients.items()))
            if events[-1] > now - self.window:
                break
            self.clients.pop(key)
        events = self.clients.get(peer)
        if events is None:
            if len(self.clients) >= self.capacity:
                return self.window  # Fail closed instead of evicting active limits.
            events = self.clients[peer] = deque()
        while events and events[0] <= now - self.window:
            events.popleft()
        self.clients.move_to_end(peer)
        if len(events) >= self.limit:
            return max(1, int(self.window - (now - events[0]) + 0.999))
        events.append(now)
        return 0


class RequestLimitsMiddleware:
    def __init__(self, app, limiter=None, api_prefix="/api/v1", serial_inference=False):
        self.app = app
        self.limiter = limiter or LocalRateLimiter()
        self.api_prefix = api_prefix
        self.guest_capable_limiter = LocalRateLimiter(limit=20)
        self.diagnostic_limiter = LocalRateLimiter(limit=2)
        self.active_guest_capable = 0
        self.active_by_peer = {}
        self.serial_inference = serial_inference
        self.inference_active = False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        path = scope["path"].rstrip("/")
        path = path.removeprefix(self.api_prefix) if path.startswith(self.api_prefix + "/") else None
        peer = (scope.get("client") or ("unknown", 0))[0]
        if path in EXPENSIVE_PATHS:
            retry = self.limiter.retry_after(peer)
            if retry:
                return await problem(429, headers={"Retry-After": str(retry)})(scope, receive, send)
        limit = (26 * 1024 * 1024 if path == "/audio/transcribe" else
                 11 * 1024 * 1024 if path == "/resume/parse" else 1024 * 1024)
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
            if declared < 0:
                raise ValueError()
        except ValueError:
            return await problem(400)(scope, receive, send)
        if declared > limit:
            return await problem(413)(scope, receive, send)

        if self.serial_inference and path in INFERENCE_PATHS:
            if self.inference_active:
                return await problem(429, headers={"Retry-After": "5"})(scope, receive, send)
            self.inference_active = True
            try:
                return await self._admit_and_dispatch(scope, receive, send, path, peer, limit)
            finally:
                self.inference_active = False
        return await self._admit_and_dispatch(scope, receive, send, path, peer, limit)

    async def _admit_and_dispatch(self, scope, receive, send, path, peer, limit):
        if path not in GUEST_CAPABLE_PATHS:
            return await self._read_and_dispatch(scope, receive, send, limit)

        # Treat every caller to these routes alike. Authorization headers are not
        # proof of identity at this point and cannot grant a larger budget.
        peer_active = self.active_by_peer.get(peer, 0)
        if self.active_guest_capable >= 4 or peer_active >= 2:
            return await problem(429, headers={"Retry-After": "5"})(scope, receive, send)
        retry = self.guest_capable_limiter.retry_after(peer)
        if not retry and path == "/ai/test":
            retry = self.diagnostic_limiter.retry_after(peer)
        if retry:
            return await problem(429, headers={"Retry-After": str(retry)})(scope, receive, send)

        # These counters belong to one ASGI worker. No await separates check
        # from increment. Release on success, failure, cancellation or disconnect.
        self.active_guest_capable += 1
        self.active_by_peer[peer] = peer_active + 1
        try:
            await self._read_and_dispatch(scope, receive, send, limit)
        finally:
            self.active_guest_capable -= 1
            if self.active_by_peer[peer] == 1:
                del self.active_by_peer[peer]
            else:
                self.active_by_peer[peer] -= 1

    async def _read_and_dispatch(self, scope, receive, send, limit):
        # Bound chunked bodies before multipart spooling/JSON decoding and inference.
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > limit:
                return await problem(413)(scope, receive, send)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, bounded_receive, send)
