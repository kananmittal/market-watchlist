"""Grounded copilot endpoint. The Groq key never leaves the server."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_copilot_service,
    get_current_user,
    get_dashboard_service,
    get_market_service,
    get_memory_service,
)
from app.api.schemas import CopilotRequest, CopilotResponse
from app.models.domain import User
from app.models.enums import ActivityType
from app.repositories.news import NewsRepository
from app.services.copilot import CopilotService
from app.services.dashboard import DashboardService
from app.services.market_data import MarketDataService
from app.services.user_memory import UserMemoryService

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.post("/chat", response_model=CopilotResponse)
async def chat(
    body: CopilotRequest,
    user: User = Depends(get_current_user),
    copilot: CopilotService = Depends(get_copilot_service),
    dashboard: DashboardService = Depends(get_dashboard_service),
    market: MarketDataService = Depends(get_market_service),
    memory: UserMemoryService = Depends(get_memory_service),
) -> CopilotResponse:
    """Answer a question strictly from evidence the backend already computed.

    Building the dashboard without advancing the anchor is deliberate: asking a
    question must not count as "looking", or the next visit would report that
    nothing changed.
    """
    result = await dashboard.build(user.id, advance_anchor=False, include_news=True)

    changes = list(result.meaningful_changes) + list(result.normal_movements)
    focus = (body.symbol or "").strip().upper()
    if not focus:
        candidates = [c.symbol for c in changes]
        identified = copilot.identify_symbols(body.question, candidates)
        if identified:
            focus_set = set(identified)
            changes = [c for c in changes if c.symbol in focus_set] + [
                c for c in changes if c.symbol not in focus_set
            ]
    else:
        changes = [c for c in changes if c.symbol == focus] + [c for c in changes if c.symbol != focus]

    symbols = [c.symbol for c in changes[:5]]
    observations = {v.symbol: v.observation for v in result.symbols if v.observation is not None}
    news = await NewsRepository().for_symbols(symbols, per_symbol_limit=3) if symbols else {}
    states = await memory.states_for(user.id, symbols)

    evidence = copilot.build_evidence(
        question=body.question,
        changes=changes,
        observations=observations,
        news=news,
        states=states,
        market_label=result.market.label,
        benchmark=result.benchmark,
        away_for=result.away_for,
    )
    answer = await copilot.answer(body.question, evidence)

    await memory.log(
        user.id,
        ActivityType.COPILOT_QUERY,
        symbol=focus or (answer.symbols[0] if answer.symbols else None),
        metadata={"question": body.question[:200], "grounded": answer.grounded},
    )
    return CopilotResponse(
        answer=answer.answer,
        grounded=answer.grounded,
        evidence=answer.evidence,
        symbols=answer.symbols,
        model=answer.model,
        degraded_reason=answer.degraded_reason,
        cached=answer.cached,
    )
