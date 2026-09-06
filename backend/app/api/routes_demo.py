"""Demo controls.

Lets the deterministic scenario be stepped so the "leave, come back, catch up"
story can be demonstrated reliably without waiting for a real market move.
Demo data is always labelled synthetic and never presented as live.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user, get_market_service, get_memory_service
from app.db.mongo import Collections, get_db
from app.models.domain import User, utcnow
from app.providers.demo_provider import SCENARIO, DemoProvider
from app.repositories.watchlists import WatchlistRepository
from app.services.market_data import MarketDataService
from app.services.user_memory import UserMemoryService

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/status")
async def demo_status(market: MarketDataService = Depends(get_market_service)) -> dict:
    provider = market._providers.get("demo")
    step = provider.step if isinstance(provider, DemoProvider) else 1
    return {
        "demo_mode": market.demo_mode,
        "step": step,
        "available_steps": sorted(SCENARIO.keys()),
        "scenario": DemoProvider(step=step).describe_scenario(),
    }


@router.post("/step")
async def set_demo_step(
    step: int = Query(ge=0, le=2),
    market: MarketDataService = Depends(get_market_service),
    _: User = Depends(get_current_user),
) -> dict:
    """Advance the scripted scenario, simulating time passing in the market."""
    market.set_demo_step(step)
    market.cache.clear()
    return {
        "demo_mode": market.demo_mode,
        "step": step,
        "scenario": DemoProvider(step=step).describe_scenario(),
    }


@router.post("/mode")
async def set_demo_mode(
    enabled: bool = Query(),
    market: MarketDataService = Depends(get_market_service),
    _: User = Depends(get_current_user),
) -> dict:
    """Toggle demo mode at runtime so a live demo can survive a provider outage."""
    market.settings.demo_mode = enabled
    market.cache.clear()
    return {"demo_mode": market.demo_mode}


@router.post("/reset")
async def reset_demo(
    market: MarketDataService = Depends(get_market_service),
    user: User = Depends(get_current_user),
    memory: UserMemoryService = Depends(get_memory_service),
) -> dict:
    """Rewind the scenario so the demo can be replayed from a clean slate.

    Synthetic observations accumulate in the shared observation store as the
    scenario is stepped, so a later run would baseline against a previous
    step's prices and report that nothing changed. This clears the synthetic
    rows, drops this user's computed changes, and re-anchors their symbols to
    now - giving the reliable "previous state -> change -> catch up" sequence
    the demo depends on. Only synthetic rows are removed; real observations are
    never touched.
    """
    db = get_db()
    removed = await db[Collections.MARKET_OBSERVATIONS].delete_many({"is_synthetic": True})
    await db[Collections.CHANGE_EVENTS].delete_many({"user_id": user.id})

    now = utcnow()
    symbols = await WatchlistRepository().all_symbols_for_user(user.id)
    if symbols:
        await db[Collections.USER_SYMBOL_STATE].update_many(
            {"user_id": user.id, "symbol": {"$in": symbols}},
            {
                "$set": {
                    "first_added_at": now,
                    "last_viewed_at": None,
                    "last_acknowledged_at": None,
                    "view_count": 0,
                    "interest_score": 0.0,
                }
            },
        )
    # Reset the "when did I last look" anchor too, so the next load is visit one.
    await db[Collections.USERS].update_one({"id": user.id}, {"$set": {"last_dashboard_view_at": None}})

    market.set_demo_step(0)
    market.cache.clear()
    return {
        "reset": True,
        "step": 0,
        "symbols_reanchored": len(symbols),
        "synthetic_observations_cleared": removed.deleted_count,
        "next": "Load the dashboard for the baseline, open a stock, then POST /demo/step?step=1",
    }
