"""FastAPI application entrypoint.

Boots the database, ensures indexes, mounts routers and installs consistent
error handling. Designed for Render's free tier: it binds 0.0.0.0:$PORT, keeps
startup cheap because the service sleeps after inactivity, and never depends on
a long-running background worker for correctness.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    routes_auth,
    routes_copilot,
    routes_dashboard,
    routes_demo,
    routes_health,
    routes_market,
    routes_watchlists,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, get_logger
from app.db.indexes import ensure_indexes
from app.db.mongo import close_mongo_connection, connect_to_mongo

log = get_logger("app")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    try:
        await connect_to_mongo()
        await ensure_indexes()
    except Exception as exc:
        # Fail loudly in logs but still start, so /api/health can report the
        # problem instead of the platform showing an opaque boot crash.
        log.error("startup_database_failed", error=str(exc)[:200])
    log.info(
        "app_started",
        env=settings.app_env,
        demo_mode=settings.demo_mode,
        providers=settings.provider_order,
        groq_configured=bool(settings.resolved_groq_key),
    )
    yield
    await close_mongo_connection()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Time-Aware Market Watchlist API",
        description=(
            "Remembers what a user has seen and surfaces what meaningfully changed since they last looked."
        ),
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------- error handling ----------------
    @app.exception_handler(AppError)
    async def handle_app_error(_r: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_r: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Some fields are invalid.",
                    "details": {
                        "fields": [
                            {
                                "field": ".".join(str(p) for p in e.get("loc", [])[1:]),
                                "message": e.get("msg", "invalid"),
                            }
                            for e in exc.errors()[:10]
                        ]
                    },
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_r: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail)}},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Log the detail, return none of it: no stack traces to users.
        log.error(
            "unhandled_error", path=str(request.url.path), error=type(exc).__name__, detail=str(exc)[:300]
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {"code": "INTERNAL_ERROR", "message": "Something went wrong. Please try again."}
            },
        )

    # ---------------- request logging ----------------
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        started = time.perf_counter()
        response = await call_next(request)
        if not request.url.path.startswith(("/docs", "/openapi", "/api/health")):
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                ms=round((time.perf_counter() - started) * 1000, 1),
            )
        return response

    # ---------------- routes ----------------
    prefix = settings.api_prefix
    app.include_router(routes_health.router, prefix=prefix)
    app.include_router(routes_auth.router, prefix=prefix)
    app.include_router(routes_watchlists.router, prefix=prefix)
    app.include_router(routes_market.router, prefix=prefix)
    app.include_router(routes_dashboard.router, prefix=prefix)
    app.include_router(routes_copilot.router, prefix=prefix)
    app.include_router(routes_demo.router, prefix=prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "name": "Time-Aware Market Watchlist API",
            "docs": "/docs",
            "health": f"{prefix}/health",
        }

    return app


app = create_app()
