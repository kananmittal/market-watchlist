"""News normalisation pipeline.

    RawArticle -> normalise -> resolve entity -> classify -> deduplicate -> NewsEvent

The rest of the application only ever sees NewsEvent. This keeps the change
engine independent of any particular feed, and means a dead news source
degrades the product rather than breaking it.

Deduplication matters for correctness, not tidiness: three outlets covering one
earnings release must contribute one event's worth of significance, otherwise
widely-reported news mechanically outranks genuinely bigger news.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.models.domain import NewsEvent
from app.models.enums import NewsEventType
from app.providers.news_provider import NewsProvider, RawArticle
from app.providers.symbols import get_symbol_info

log = get_logger("service.news")

# Words carrying no discriminating power when comparing headlines.
STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "but",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "at",
    "by",
    "from",
    "up",
    "down",
    "as",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "will",
    "would",
    "can",
    "could",
    "may",
    "might",
    "this",
    "that",
    "these",
    "those",
    "it",
    "its",
    "after",
    "before",
    "over",
    "under",
    "amid",
    "says",
    "said",
    "new",
    "here",
    "what",
    "why",
    "how",
    "you",
    "your",
    "should",
    "know",
    "more",
    "than",
    "into",
    "out",
    "about",
    "vs",
    "amp",
}

#: Event taxonomy. Order matters: the first matching pattern wins, so specific
#: corporate events are tested before generic market commentary.
EVENT_PATTERNS: list[tuple[NewsEventType, float, tuple[str, ...]]] = [
    (
        NewsEventType.EARNINGS,
        0.90,
        (
            "q1",
            "q2",
            "q3",
            "q4",
            "quarterly",
            "quarter",
            "results",
            "earnings",
            "profit",
            "revenue",
            "net income",
            "topline",
            "bottomline",
            "ebitda",
            "margin",
        ),
    ),
    (
        NewsEventType.MERGER_ACQUISITION,
        0.92,
        (
            "acquire",
            "acquisition",
            "merger",
            "merges",
            "takeover",
            "buyout",
            "stake sale",
            "acquires",
            "to buy",
            "divest",
        ),
    ),
    (
        NewsEventType.REGULATORY,
        0.85,
        (
            "sebi",
            "rbi",
            "cci",
            "regulator",
            "regulatory",
            "probe",
            "investigation",
            "penalty",
            "fine",
            "notice",
            "compliance",
            "ban",
        ),
    ),
    (
        NewsEventType.LEGAL,
        0.82,
        (
            "lawsuit",
            "court",
            "tribunal",
            "nclt",
            "verdict",
            "litigation",
            "sues",
            "legal",
            "arbitration",
            "insolvency",
        ),
    ),
    (
        NewsEventType.MANAGEMENT,
        0.78,
        (
            "ceo",
            "cfo",
            "managing director",
            "chairman",
            "resign",
            "steps down",
            "appoints",
            "appointment",
            "board",
            "succession",
        ),
    ),
    (
        NewsEventType.CORPORATE_ACTION,
        0.75,
        (
            "dividend",
            "bonus issue",
            "stock split",
            "buyback",
            "rights issue",
            "ipo",
            "fundraise",
            "qip",
            "delisting",
        ),
    ),
    (
        NewsEventType.PRODUCT_BUSINESS,
        0.58,
        (
            "launch",
            "invest",
            "investment",
            "expansion",
            "plant",
            "capacity",
            "contract",
            "order win",
            "deal",
            "partnership",
            "tie-up",
            "data centre",
            "data center",
            "crore",
        ),
    ),
    (
        NewsEventType.ANALYST,
        0.45,
        (
            "target price",
            "upgrade",
            "downgrade",
            "brokerage",
            "analyst",
            "rating",
            "outperform",
            "underperform",
            "buy call",
            "sell call",
            "initiate coverage",
        ),
    ),
    (
        NewsEventType.SECTOR,
        0.40,
        (
            "sector",
            "industry",
            "peers",
            "nifty it",
            "nifty bank",
            "auto sector",
        ),
    ),
]

#: Headlines that are noise regardless of keywords.
LOW_VALUE_MARKERS = (
    "stocks to watch",
    "top gainers",
    "top losers",
    "market wrap",
    "closing bell",
    "opening bell",
    "technical view",
    "trade setup",
    "stocks to buy",
    "muhurat",
    "dividend anchors",
    "things to know",
    "market live",
    "sensex today",
    "nifty today",
    "share price",
    "52-week low",
    "52-week high",
    "stock hits",
    "underperforms market",
    "outperforms market",
    "shares in focus",
    "day trading guide",
)

TOKEN_RE = re.compile(r"[a-z0-9]+")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def _keyword_regex(keywords: tuple[str, ...]) -> re.Pattern[str]:
    """Word-boundary matcher for a keyword group.

    Plain substring matching is unsafe here: "ban" matches inside "Bank", which
    tagged every bank headline as REGULATORY. Boundaries make short keywords
    safe while still allowing multi-word phrases.
    """
    alternatives = "|".join(re.escape(k) for k in sorted(keywords, key=len, reverse=True))
    return re.compile(rf"(?<![a-z0-9])(?:{alternatives})(?![a-z0-9])")


#: Precompiled once at import: classification runs per article per symbol.
_COMPILED_PATTERNS: list[tuple[NewsEventType, float, re.Pattern[str]]] = [
    (event_type, significance, _keyword_regex(keywords))
    for event_type, significance, keywords in EVENT_PATTERNS
]


#: Google News appends " - Publisher" to titles.
SOURCE_SUFFIX_RE = re.compile(r"\s+-\s+[^-]{2,40}$")

#: Jaccard similarity above which two headlines are treated as one story.
SIMILARITY_THRESHOLD = 0.45
#: Corporate events that occur once and get covered many times. Same symbol,
#: same event type, same day is a single underlying story.
SINGULAR_EVENTS = {
    NewsEventType.EARNINGS,
    NewsEventType.MERGER_ACQUISITION,
    NewsEventType.CORPORATE_ACTION,
    NewsEventType.MANAGEMENT,
}


@dataclass
class NormalizedArticle:
    raw: RawArticle
    clean_title: str
    tokens: frozenset[str]
    event_type: NewsEventType
    significance: float
    entity_confidence: float


def normalize_title(title: str) -> str:
    return SOURCE_SUFFIX_RE.sub("", title or "").strip()


def strip_html(text: str) -> str:
    """Feed summaries arrive as HTML anchor blobs; keep only readable text."""
    return re.sub(r"\s+", " ", HTML_TAG_RE.sub(" ", text or "")).strip()


def tokenize(text: str) -> frozenset[str]:
    return frozenset(t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOPWORDS and len(t) > 2)


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def classify(title: str, summary: str = "") -> tuple[NewsEventType, float]:
    """Map a headline to an event type and a base significance in 0-1.

    Deliberately reads the TITLE only. Google News RSS "summaries" are HTML
    anchor blobs containing base64 tracking URLs and unrelated related-article
    text; classifying on them tagged routine price updates as EARNINGS at 0.94
    significance, which then dominated the news score. `summary` is retained in
    the signature for callers but intentionally unused.
    """
    text = (title or "").lower()
    if any(marker in text for marker in LOW_VALUE_MARKERS):
        return NewsEventType.GENERAL, 0.12
    for event_type, significance, pattern in _COMPILED_PATTERNS:
        if pattern.search(text):
            return event_type, significance
    return NewsEventType.GENERAL, 0.22


def resolve_entity(symbol: str, title: str, summary: str = "") -> float:
    """Confidence in 0-1 that this article is really about this symbol.

    Title-only for the same reason as `classify`: feed summaries are unreliable.
    Guards against a query for "Trent" matching unrelated coverage.
    """
    info = get_symbol_info(symbol)
    text = (title or "").lower()
    sym = symbol.lower()

    if re.search(rf"\b{re.escape(sym)}\b", text):
        return 0.95
    if info:
        full = info.name.split("(")[0].strip().lower()
        if full and full in text:
            return 0.92
        words = [w for w in TOKEN_RE.findall(full) if w not in STOPWORDS and len(w) > 3]
        if words:
            hits = sum(1 for w in words if w in text)
            if hits == len(words):
                return 0.88
            if hits >= max(1, len(words) - 1):
                return 0.72
    # Came back from a targeted query but nothing matched explicitly.
    return 0.45


class NewsEngine:
    def __init__(self, provider: NewsProvider | None = None) -> None:
        self.provider = provider or NewsProvider()

    # ---------------- normalisation ----------------
    def _normalize(self, symbol: str, articles: list[RawArticle]) -> list[NormalizedArticle]:
        out: list[NormalizedArticle] = []
        for art in articles:
            clean = normalize_title(art.title)
            event_type, significance = classify(clean, art.summary)
            confidence = resolve_entity(symbol, clean, art.summary)
            if confidence < 0.5:
                continue  # not confidently about this symbol - drop rather than mislead
            out.append(
                NormalizedArticle(
                    raw=art,
                    clean_title=clean,
                    tokens=tokenize(clean),
                    event_type=event_type,
                    significance=significance,
                    entity_confidence=confidence,
                )
            )
        return out

    # ---------------- deduplication ----------------
    def _cluster(self, articles: list[NormalizedArticle]) -> list[list[NormalizedArticle]]:
        """Greedy single-pass clustering of articles about one underlying story."""
        clusters: list[list[NormalizedArticle]] = []
        for art in sorted(articles, key=lambda a: a.raw.published_at, reverse=True):
            placed = False
            for cluster in clusters:
                head = cluster[0]
                same_day = abs((art.raw.published_at - head.raw.published_at).total_seconds()) < 86_400
                if jaccard(art.tokens, head.tokens) >= SIMILARITY_THRESHOLD:
                    cluster.append(art)
                    placed = True
                    break
                # One corporate event, many outlets: collapse by type and day.
                if same_day and art.event_type is head.event_type and art.event_type in SINGULAR_EVENTS:
                    cluster.append(art)
                    placed = True
                    break
            if not placed:
                clusters.append([art])
        return clusters

    def _to_event(self, symbol: str, cluster: list[NormalizedArticle]) -> NewsEvent:
        """Represent a cluster by its most significant, best-attributed article."""
        lead = max(cluster, key=lambda a: (a.significance * a.entity_confidence, a.raw.published_at))
        signature = hashlib.sha256(
            f"{symbol}:{lead.event_type.value}:"
            f"{lead.raw.published_at:%Y-%m-%d}:"
            f"{'-'.join(sorted(lead.tokens)[:6])}".encode()
        ).hexdigest()[:20]

        # Corroboration across outlets is mild evidence the story is real, but
        # it is capped so widely-syndicated news cannot dominate on volume alone.
        corroboration = min((len(cluster) - 1) * 0.02, 0.06)
        significance = min(lead.significance + corroboration, 1.0)

        return NewsEvent(
            event_id=f"evt_{signature}",
            symbol=symbol.strip().upper(),
            event_type=lead.event_type,
            headline=lead.clean_title[:300],
            summary=strip_html(lead.raw.summary)[:400] or None,
            source=lead.raw.source,
            source_url=lead.raw.link,
            published_at=lead.raw.published_at,
            entity_confidence=round(lead.entity_confidence, 4),
            event_significance=round(significance, 4),
            dedupe_key=f"{symbol.strip().upper()}:{signature}",
            article_count=len(cluster),
        )

    # ---------------- public API ----------------
    def build_events(
        self, symbol: str, articles: list[RawArticle], *, max_age_days: int = 7, limit: int = 8
    ) -> list[NewsEvent]:
        cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
        recent = [a for a in articles if a.published_at >= cutoff]
        normalized = self._normalize(symbol, recent)
        if not normalized:
            return []
        events = [self._to_event(symbol, c) for c in self._cluster(normalized)]
        events.sort(key=lambda e: (e.weighted_significance, e.published_at), reverse=True)
        return events[:limit]

    async def fetch_and_normalize(self, symbol: str, **kw) -> list[NewsEvent]:
        try:
            return self.build_events(symbol, await self.provider.fetch_for_symbol(symbol), **kw)
        except Exception as exc:
            log.warning("news_pipeline_failed", symbol=symbol, error=str(exc)[:160])
            return []

    async def fetch_and_normalize_many(self, symbols: list[str], **kw) -> dict[str, list[NewsEvent]]:
        try:
            raw = await self.provider.fetch_for_symbols(symbols)
        except Exception as exc:
            log.warning("news_batch_failed", error=str(exc)[:160])
            return {s.strip().upper(): [] for s in symbols}
        return {sym: self.build_events(sym, arts, **kw) for sym, arts in raw.items()}
