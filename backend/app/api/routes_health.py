"""Health and provider status. Never exposes secrets."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from app.api.deps import get_copilot_service, get_market_service
from app.api.schemas import HealthResponse
from app.core.config import get_settings
from app.core.market_time import get_market_state
from app.db.mongo import ping
from app.providers.news_provider import NewsProvider
from app.services.copilot import CopilotService
from app.services.market_data import MarketDataService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe. Intentionally cheap: Render pings this to wake the service."""
    settings = get_settings()
    return HealthResponse(status="ok", app_env=settings.app_env, demo_mode=settings.demo_mode)


@router.get("/providers")
async def provider_health(
    market: MarketDataService = Depends(get_market_service),
    copilot: CopilotService = Depends(get_copilot_service),
) -> dict:
    """Readiness detail across every dependency, with no credentials in the output."""
    db_task = ping()
    market_task = market.health()
    news_task = NewsProvider().health()
    copilot_task = copilot.health()
    db, providers, news, llm = await asyncio.gather(
        db_task, market_task, news_task, copilot_task, return_exceptions=True
    )

    def safe(value, fallback):
        return value if not isinstance(value, BaseException) else fallback

    db_result = safe(db, {"ok": False, "error": "probe_failed"})
    providers_result = safe(providers, [])
    market_ok = any(p.get("ok") for p in providers_result if isinstance(p, dict))
    state = get_market_state()

    return {
        # The product is usable whenever the database is up: market data falls
        # back to demo, and the copilot degrades to evidence cards.
        "status": "ok" if db_result.get("ok") else "degraded",
        "database": db_result,
        "market_providers": providers_result,
        "market_provider_ok": market_ok,
        "news_provider": safe(news, {"ok": False}),
        "llm": safe(llm, {"ok": False}),
        "market_session": {"status": state.status.value, "label": state.label},
        "demo_mode": get_settings().demo_mode,
    }
