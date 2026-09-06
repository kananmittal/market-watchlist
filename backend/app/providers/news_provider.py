"""Free, key-less news retrieval.

Google News RSS is used as the primary source: it needs no API key, supports
targeted per-company queries, and attributes each item to its original
publisher. Economic Times provides a general market feed as a secondary.

No paid news API is required. If every feed fails, the product continues on
market signals alone.
"""

from __future__ import annotations

import asyncio
import urllib.parse
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import get_settings
from app.core.logging import get_logger
from app.providers.symbols import display_name, get_symbol_info

log = get_logger("provider.news")

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
ET_MARKETS_RSS = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"


@dataclass
class RawArticle:
    """An unprocessed feed item, before normalisation."""

    title: str
    link: str | None
    published_at: datetime
    source: str
    summary: str = ""
    query_symbol: str | None = None


def _parse_time(entry: object) -> datetime:
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if parsed:
        try:
            return datetime(*parsed[:6], tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    return datetime.now(UTC)


class NewsProvider:
    def __init__(self) -> None:
        self.settings = get_settings()

    # ---------------- fetching ----------------
    def _blocking_fetch(self, url: str, symbol: str | None) -> list[RawArticle]:
        import feedparser

        feed = feedparser.parse(url)
        articles: list[RawArticle] = []
        for entry in getattr(feed, "entries", [])[:25]:
            title = (getattr(entry, "title", "") or "").strip()
            if not title:
                continue
            source_obj = getattr(entry, "source", None)
            source = "Unknown"
            if isinstance(source_obj, dict):
                source = source_obj.get("title") or "Unknown"
            elif source_obj is not None:
                source = getattr(source_obj, "title", "Unknown")
            articles.append(
                RawArticle(
                    title=title,
                    link=getattr(entry, "link", None),
                    published_at=_parse_time(entry),
                    source=source,
                    summary=(getattr(entry, "summary", "") or "")[:500],
                    query_symbol=symbol,
                )
            )
        return articles

    async def _fetch(self, url: str, symbol: str | None = None) -> list[RawArticle]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._blocking_fetch, url, symbol),
                timeout=self.settings.provider_timeout_seconds,
            )
        except Exception as exc:
            log.warning("news_fetch_failed", url=url[:70], error=str(exc)[:140])
            return []

    def _query_for(self, symbol: str) -> str:
        """Company name plus a market word: the name alone returns unrelated
        coverage for names like Titan or Trent."""
        info = get_symbol_info(symbol)
        name = info.name if info else display_name(symbol)
        name = name.split("(")[0].strip()
        return urllib.parse.quote(f'"{name}" stock OR shares OR results')

    async def fetch_for_symbol(self, symbol: str) -> list[RawArticle]:
        url = GOOGLE_NEWS_RSS.format(query=self._query_for(symbol))
        return await self._fetch(url, symbol.strip().upper())

    async def fetch_for_symbols(
        self, symbols: list[str], *, max_concurrent: int = 5
    ) -> dict[str, list[RawArticle]]:
        """Bounded concurrency: a 20-symbol watchlist must not open 20 sockets."""
        if not symbols:
            return {}
        sem = asyncio.Semaphore(max_concurrent)

        async def one(sym: str) -> tuple[str, list[RawArticle]]:
            async with sem:
                return sym.strip().upper(), await self.fetch_for_symbol(sym)

        results = await asyncio.gather(*(one(s) for s in symbols), return_exceptions=True)
        out: dict[str, list[RawArticle]] = {}
        for res in results:
            if isinstance(res, tuple):
                out[res[0]] = res[1]
        return out

    async def fetch_market_news(self) -> list[RawArticle]:
        return await self._fetch(ET_MARKETS_RSS)

    async def health(self) -> dict[str, object]:
        articles = await self._fetch(GOOGLE_NEWS_RSS.format(query="NIFTY"))
        return {"provider": "google_news_rss", "ok": len(articles) > 0, "articles": len(articles)}
