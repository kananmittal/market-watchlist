"""Shared API dependencies: auth and long-lived service singletons."""

from __future__ import annotations

from fastapi import Depends, Header

from app.core.errors import AuthError
from app.core.security import decode_access_token
from app.models.domain import User
from app.repositories.users import UserRepository
from app.services.copilot import CopilotService
from app.services.dashboard import DashboardService
from app.services.market_data import MarketDataService
from app.services.user_memory import UserMemoryService

# Built once per process. The market service owns caches and provider clients,
# so creating it per request would discard every cache on every call.
_market = MarketDataService()
_dashboard = DashboardService(market=_market)
_copilot = CopilotService()
_memory = UserMemoryService()


def get_market_service() -> MarketDataService:
    return _market


def get_dashboard_service() -> DashboardService:
    return _dashboard


def get_copilot_service() -> CopilotService:
    return _copilot


def get_memory_service() -> UserMemoryService:
    return _memory


async def get_current_user(authorization: str | None = Header(default=None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Sign in to continue.")
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("Invalid authentication token.")
    user = await UserRepository().get_by_id(user_id)
    if user is None:
        raise AuthError("Account no longer exists.")
    return user


CurrentUser = Depends(get_current_user)
