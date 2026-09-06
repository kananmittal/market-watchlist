"""MarketDataProvider interface.

Every provider is optional and replaceable. The product must never hard-depend
on a single upstream, so each implementation is expected to fail gracefully and
report its own health.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod

from app.core.errors import ProviderTimeoutError
from app.models.domain import MarketObservation, PriceHistory


class MarketDataProvider(ABC):
    """Abstract market data source."""

    name: str = "base"
    #: Higher wins when two providers disagree within tolerance.
    priority: int = 0
    #: True when the data is generated, not observed. Must surface to the UI.
    synthetic: bool = False

    @abstractmethod
    async def get_quote(self, symbol: str) -> MarketObservation | None:
        """Latest observation for one symbol, or None if unavailable."""

    @abstractmethod
    async def get_batch_quotes(self, symbols: list[str]) -> dict[str, MarketObservation]:
        """Batched quotes. Implementations SHOULD issue one upstream request."""

    @abstractmethod
    async def get_history(
        self, symbol: str, period: str = "3mo", interval: str = "1d"
    ) -> PriceHistory | None:
        """Historical bars used for volatility and volume baselines."""

    async def health(self) -> dict[str, object]:
        """Cheap liveness probe. Never raises, never leaks credentials."""
        return {"provider": self.name, "ok": True, "synthetic": self.synthetic}

    async def _with_timeout(self, coro, timeout: float, what: str):
        """Bound every upstream call: a hung provider must not hang a request."""
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except TimeoutError as exc:
            raise ProviderTimeoutError(
                f"{self.name} timed out fetching {what}.",
                details={"provider": self.name, "timeout_seconds": timeout},
            ) from exc
