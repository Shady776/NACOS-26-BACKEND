"""
Shared rate limiter, built on slowapi (a thin wrapper around the
`limits` library) so every route in the app uses the same limiter
instance and the same exception handler.

Usage in a route file:

    from fastapi import Request
    from ..utils.rate_limit import limiter

    @router.post("/login")
    @limiter.limit("5/minute")
    def login(request: Request, ...):
        ...

Notes:
- The decorated function MUST accept a `request: Request` parameter —
  slowapi reads `request.app.state.limiter` to enforce the limit.
- Limits are keyed by client IP by default (get_remote_address). Behind a
  proxy (Railway, or Vercel proxying /api/*) start uvicorn with
  `--proxy-headers --forwarded-allow-ips="*"` so the real client IP is used.
- Counters live in each worker's memory, so with `--workers 2` the effective
  limit is roughly doubled. That is fine for abuse protection.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from limits import parse
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter

limiter = Limiter(key_func=get_remote_address)

# ── Per username + IP login limit ────────────────────────────────────────────
# The per-IP limit on /auth/login is generous because a whole campus can share
# one IP. This second limit is keyed by (IP, username), so one student
# mistyping their password locks only themselves out, not everyone else.
_login_storage = MemoryStorage()
_login_strategy = MovingWindowRateLimiter(_login_storage)
_LOGIN_ATTEMPTS = parse("10/minute")


def login_attempt_allowed(ip: str, username: str) -> bool:
    """Record one login attempt; return False once the limit is exceeded."""
    return _login_strategy.hit(_LOGIN_ATTEMPTS, "login", ip or "unknown", (username or "").lower().strip())
