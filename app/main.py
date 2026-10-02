import asyncio
import logging
import os
import re
import time
from urllib.parse import urlparse
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from .database import init_db
from .routes import (auth, courses, assignments, users, submissions, enrollments, 
                     admin, dashboard, teacher_dashboard, course_materials, test, warnings, Notifications)
from .utils.rate_limit import limiter
from contextlib import asynccontextmanager
from app.utils.admin import setup_admin
from app.config import CONFIG
from app.oauth2 import ACCESS_COOKIE, REFRESH_COOKIE

IS_PRODUCTION = CONFIG.ENVIRONMENT.lower() == "production"
logger = logging.getLogger("uvicorn.error")

# Frontend origins allowed to call this API (CORS + the CSRF check below).
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:8080",
    "http://localhost:4173",
] + [o.strip().rstrip("/") for o in CONFIG.ALLOWED_ORIGINS.split(",") if o.strip()]

def _run_auto_submit_once() -> int:
    from app.database import SessionLocal
    from app.routes.test import auto_submit_overdue_attempts
    db = SessionLocal()
    try:
        return auto_submit_overdue_attempts(db)
    finally:
        db.close()


async def _auto_submit_loop():
    """Every 30 seconds, submit tests whose time ran out but were never submitted."""
    while True:
        await asyncio.sleep(30)
        try:
            count = await asyncio.to_thread(_run_auto_submit_once)
            if count:
                logger.info("auto-submitted %s overdue test attempt(s)", count)
        except Exception as exc:
            logger.warning("auto-submit sweep failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = None
    try:
        init_db()
        setup_admin()
        task = asyncio.create_task(_auto_submit_loop())
        yield
    finally:
        if task:
            task.cancel()
        print("shutting down")


app = FastAPI(
    title="Learning Management System API",
    description="A comprehensive LMS backend for teachers and students",
    version="1.0.0",
    lifespan=lifespan,
    # Swagger/ReDoc expose the full API surface to anyone — fine for dev,
    # not something we want sitting open on the public internet.
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
)

# Rate limiting (slowapi) — currently applied per-route in routes/auth.py
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CSRF protection ──────────────────────────────────────────────────────────
# Cookies are sent automatically by the browser, so another website could try
# to make a logged-in student's browser POST to this API. For any request that
# changes data and is authenticated by cookie (no Authorization header), the
# Origin (or Referer) must be one of our own frontends. Together with
# SameSite=Lax cookies this blocks cross-site forged requests.
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def csrf_origin_check(request: Request, call_next):
    if (
        request.method in _UNSAFE_METHODS
        and "authorization" not in request.headers
        and (request.cookies.get(ACCESS_COOKIE) or request.cookies.get(REFRESH_COOKIE))
    ):
        origin = request.headers.get("origin")
        if not origin:
            referer = request.headers.get("referer")
            if referer:
                parts = urlparse(referer)
                origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in ALLOWED_ORIGINS:
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
    return await call_next(request)


# ── Request timing + no-cache header ─────────────────────────────────────────
# Logs every /tests/.../start and /submit call, plus any request slower than
# 1 second, so slow spots show up in the Railway logs during a real test.
_TIMED_PATHS = re.compile(r"^/tests/[^/]+/(start|submit|answers)$")


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    # API answers are per-user. Tell Vercel's proxy (and any browser/CDN cache)
    # never to store them, or one student's data could be served to another.
    response.headers.setdefault("Cache-Control", "no-store")
    elapsed_ms = (time.perf_counter() - started) * 1000
    if elapsed_ms > 1000 or _TIMED_PATHS.match(request.url.path):
        logger.info(
            "timing %s %s -> %s in %.0f ms",
            request.method, request.url.path, response.status_code, elapsed_ms,
        )
    return response


# CORS middleware (added last so it wraps the middleware above and its
# error responses still carry CORS headers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(assignments.router)
app.include_router(enrollments.router)
app.include_router(submissions.router)
app.include_router(admin.router)
app.include_router(dashboard.router)
app.include_router(teacher_dashboard.router)
app.include_router(users.router)
app.include_router(course_materials.router)
app.include_router(test.router)
app.include_router(warnings.router)
app.include_router(Notifications.router)

@app.get("/")
def root():
    return {
        "message": "Welcome to the Learning Management System API",
        "docs": "/docs",
        "version": "1.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)