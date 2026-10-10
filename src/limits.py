"""
Two brakes on what anyone on the internet can send:

- a request body over 1 MB is refused (413) before it is read; a body sent
  without a length (chunked) is cut off at 1 MB while it is read. The largest
  real body, a first step sync of ~550 days, is about 30 kB.
- the patient endpoints (the ones the app and the web form call with
  X-Patient-Code, no login) take about 120 requests a minute per address,
  all of them together - many times what one patient's app sends. Beyond
  that: 429 + Retry-After. Kept in this server's memory (one replica); a
  restart forgets the counts.

Every refusal prints a "🚦 [limit]" line, so they are easy to find in the
Railway logs.
"""
import time

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from limits import parse
from slowapi import Limiter

MAX_BODY_BYTES = 1024 * 1024
PATIENT_LIMIT = parse("120/minute")


def client_ip(request: Request) -> str:
    """The caller's address as Railway's proxy reports it (the same rule as the Doctor Filler server)."""
    forwarded = [s.strip() for s in request.headers.get("x-forwarded-for", "").split(",") if s.strip()]
    return request.headers.get("x-real-ip") or (forwarded[-1] if forwarded else None) or (request.client.host if request.client else "?")


limiter = Limiter(key_func=client_ip)


async def patient_rate_limit(request: Request) -> None:
    """FastAPI dependency for the patient endpoints: one shared count per address."""
    ip = client_ip(request)
    if limiter.limiter.hit(PATIENT_LIMIT, "patient", ip):
        return
    reset_at, _ = limiter.limiter.get_window_stats(PATIENT_LIMIT, "patient", ip)
    retry_after = max(1, int(reset_at - time.time()) + 1)
    print(f"🚦 [limit] patient endpoints: refused ip={ip} {request.method} {request.url.path} ({PATIENT_LIMIT}) retryAfter={retry_after}s")
    raise HTTPException(
        status_code=429,
        detail="Too many requests. Please try again in a minute.",
        headers={"Retry-After": str(retry_after)},
    )


class BodySizeLimit:
    """ASGI middleware: 413 for a request body over MAX_BODY_BYTES."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = next((value for key, value in scope["headers"] if key == b"content-length"), b"")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            print(f"🚦 [limit] body too large: {int(declared)} bytes, {scope.get('method')} {scope.get('path')}")
            response = JSONResponse({"status": "error", "detail": "Request body too large (max 1 MB)"}, status_code=413)
            await response(scope, receive, send)
            return

        received = 0

        async def counted_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    print(f"🚦 [limit] body too large: over {MAX_BODY_BYTES} bytes without a length, {scope.get('method')} {scope.get('path')}")
                    raise HTTPException(status_code=413, detail="Request body too large (max 1 MB)")
            return message

        await self.app(scope, counted_receive, send)
