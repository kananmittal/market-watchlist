"""Grounded Groq copilot.

Groq is an explanation layer over evidence the backend already computed. It is
never the source of market truth:

  * the model receives a compact, structured evidence package and is told to
    use nothing else
  * it is instructed to say when evidence is insufficient rather than guess
  * it must not give buy/sell advice or claim to have browsed anything
  * every failure mode degrades to the deterministic evidence cards, which are
    returned alongside the answer regardless

The API key stays server-side. It is never returned by any endpoint.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.domain import ChangeEvent, MarketObservation, NewsEvent, UserSymbolState
from app.providers.symbols import display_name, search

log = get_logger("service.copilot")

SYSTEM_PROMPT = """You are the explanation layer of a market watchlist product.

You will be given a JSON EVIDENCE package that the application already computed
from market data, benchmark indices and news feeds.

Rules you must follow:
1. Use ONLY facts present in the EVIDENCE. Never introduce prices, percentages,
   dates, volumes, news or company facts that are not there.
2. If the evidence does not answer the question, say so plainly and state what
   is missing. Do not speculate to fill the gap.
3. Separate fact from interpretation. Facts come from EVIDENCE; interpretation
   is clearly hedged ("this pattern usually suggests...").
4. Never give investment advice. No buy, sell, hold, target price or
   allocation recommendations. If asked, explain what the data shows instead.
5. Never claim to have browsed the web, read a filing, or consulted a source.
   You have only the EVIDENCE.
6. If evidence is marked synthetic or demo, say the figures are demo data.
7. If data quality is CONFLICTED or STALE, mention that before interpreting.

Style: direct and concise. Lead with the answer. 2-5 short sentences, or a
short bullet list when several factors matter. No preamble, no restating the
question, no sign-off.

Write plain prose. Do not use markdown formatting - no **bold**, no headings,
no backticks. Bullets may start with a simple "- "."""

MAX_EVIDENCE_CHARS = 7000
CACHE_TTL_SECONDS = 180


@dataclass
class CopilotAnswer:
    answer: str
    grounded: bool  # True when Groq produced it from evidence
    evidence: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    model: str | None = None
    degraded_reason: str | None = None
    cached: bool = False


@dataclass
class _Entry:
    value: CopilotAnswer
    expires_at: float


class CopilotService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Any = None
        self._cache: dict[str, _Entry] = {}

    # ---------------- client ----------------
    @property
    def available(self) -> bool:
        return bool(self.settings.resolved_groq_key)

    def _get_client(self):
        if self._client is None:
            from groq import AsyncGroq

            self._client = AsyncGroq(
                api_key=self.settings.resolved_groq_key,
                timeout=self.settings.groq_timeout_seconds,
                max_retries=0,  # retries handled here, with backoff and jitter
            )
        return self._client

    # ---------------- context resolution ----------------
    def identify_symbols(self, question: str, candidates: list[str]) -> list[str]:
        """Find which watchlist symbols a question is about.

        Matching is restricted to the user's own symbols so the copilot cannot
        be steered onto instruments they do not track.
        """
        text = (question or "").upper()
        hits = [s for s in candidates if s in text]
        if not hits:
            for symbol in candidates:
                name = display_name(symbol).split("(")[0].strip().upper()
                if name and name in text:
                    hits.append(symbol)
        if not hits:
            for token in {t for t in text.replace("?", " ").split() if len(t) > 2}:
                for info in search(token, limit=2):
                    if info.symbol in candidates:
                        hits.append(info.symbol)
        return list(dict.fromkeys(hits))[:4]

    def build_evidence(
        self,
        *,
        question: str,
        changes: list[ChangeEvent],
        observations: dict[str, MarketObservation],
        news: dict[str, list[NewsEvent]],
        states: dict[str, UserSymbolState],
        market_label: str,
        benchmark: MarketObservation | None,
        away_for: str | None = None,
    ) -> dict[str, Any]:
        """Compact, bounded evidence package. Bounded prompts keep the free tier
        usable and stop one huge watchlist from blowing the context window."""
        payload: dict[str, Any] = {
            "market_status": market_label,
            "time_since_user_last_looked": away_for,
            "benchmark": None,
            "stocks": [],
        }
        if benchmark and benchmark.price is not None:
            payload["benchmark"] = {
                "name": "NIFTY 50",
                "price": round(benchmark.price, 2),
                "change_pct": benchmark.change_pct,
            }

        for change in changes[:5]:
            obs = observations.get(change.symbol)
            state = states.get(change.symbol)
            entry: dict[str, Any] = {
                "symbol": change.symbol,
                "name": display_name(change.symbol),
                "price": round(obs.price, 2) if obs and obs.price else None,
                "data_quality": change.data_quality.value,
                "is_demo_data": change.is_synthetic,
                "change_since_user_last_looked_pct": change.metrics.price_change_pct,
                "typical_daily_move_pct": change.metrics.expected_daily_move_pct,
                "move_vs_typical_multiple": change.metrics.normalized_move,
                "vs_benchmark_pct": change.metrics.relative_to_benchmark_pct,
                "vs_sector_pct": change.metrics.relative_to_sector_pct,
                "volume_vs_average_multiple": change.metrics.volume_multiple,
                "attribution": change.change_type.value,
                "severity": change.severity.value,
                "attention_score": change.attention_score,
                "why_it_matters": change.evidence_labels[:6],
                "review_status": change.status.value,
            }
            if state:
                entry["user_last_viewed"] = state.last_viewed_at.isoformat() if state.last_viewed_at else None
                entry["user_last_acknowledged"] = (
                    state.last_acknowledged_at.isoformat() if state.last_acknowledged_at else None
                )
            items = news.get(change.symbol, [])[:3]
            if items:
                entry["news"] = [
                    {
                        "headline": n.headline,
                        "type": n.event_type.value,
                        "source": n.source,
                        "published_at": n.published_at.isoformat(),
                        "articles_merged": n.article_count,
                    }
                    for n in items
                ]
            payload["stocks"].append(entry)
        return payload

    # ---------------- generation ----------------
    def _cache_key(self, question: str, evidence: dict[str, Any]) -> str:
        raw = json.dumps({"q": question.strip().lower(), "e": evidence}, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    def _fallback(self, evidence: dict[str, Any], reason: str) -> CopilotAnswer:
        """Deterministic answer when Groq is unavailable. The product still works."""
        stocks = evidence.get("stocks", [])
        if not stocks:
            text = (
                "I do not have enough information to answer that yet. "
                "Add symbols to your watchlist, or open a stock to see its evidence."
            )
        else:
            lines = []
            for s in stocks[:3]:
                move = s.get("change_since_user_last_looked_pct")
                bits = [f"{s['name']} ({s['symbol']})"]
                if move is not None:
                    bits.append(f"{'up' if move >= 0 else 'down'} {abs(move):.2f}%")
                if s.get("attribution"):
                    bits.append(f"classified {s['attribution'].replace('_', ' ').lower()}")
                lines.append("- " + ", ".join(bits))
                for why in (s.get("why_it_matters") or [])[:3]:
                    lines.append(f"    - {why}")
            text = (
                "The AI explanation is unavailable right now, so here is the "
                "underlying evidence:\n" + "\n".join(lines)
            )
        return CopilotAnswer(
            answer=text,
            grounded=False,
            evidence=[w for s in stocks for w in (s.get("why_it_matters") or [])][:8],
            symbols=[s["symbol"] for s in stocks],
            degraded_reason=reason,
        )

    async def answer(self, question: str, evidence: dict[str, Any]) -> CopilotAnswer:
        question = (question or "").strip()
        if not question:
            return CopilotAnswer(
                answer="Ask me about a stock in your watchlist.",
                grounded=False,
                degraded_reason="empty_question",
            )

        symbols = [s["symbol"] for s in evidence.get("stocks", [])]
        base_evidence = [w for s in evidence.get("stocks", []) for w in (s.get("why_it_matters") or [])][:8]

        if not self.available:
            return self._fallback(evidence, "groq_not_configured")

        key = self._cache_key(question, evidence)
        hit = self._cache.get(key)
        if hit and hit.expires_at > time.monotonic():
            return CopilotAnswer(**{**hit.value.__dict__, "cached": True})

        serialized = json.dumps(evidence, default=str, separators=(",", ":"))
        if len(serialized) > MAX_EVIDENCE_CHARS:
            trimmed = dict(evidence)
            trimmed["stocks"] = evidence.get("stocks", [])[:3]
            serialized = json.dumps(trimmed, default=str, separators=(",", ":"))[:MAX_EVIDENCE_CHARS]

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"EVIDENCE:\n{serialized}\n\nQUESTION: {question}"},
        ]

        last_error = "unknown"
        for attempt in range(self.settings.groq_max_retries + 1):
            try:
                client = self._get_client()
                response = await client.chat.completions.create(
                    model=self.settings.groq_model,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=self.settings.groq_max_output_tokens,
                )
                message = response.choices[0].message
                text = (getattr(message, "content", "") or "").strip()
                if not text:
                    # Reasoning models can spend the whole budget on reasoning.
                    last_error = "empty_completion"
                    raise ValueError(last_error)

                answer = CopilotAnswer(
                    answer=text,
                    grounded=True,
                    evidence=base_evidence,
                    symbols=symbols,
                    model=self.settings.groq_model,
                )
                self._cache[key] = _Entry(answer, time.monotonic() + CACHE_TTL_SECONDS)
                return answer

            except Exception as exc:
                name = type(exc).__name__
                status = getattr(exc, "status_code", None)
                last_error = f"{name}:{status}" if status else name
                retryable = status in (408, 409, 429, 500, 502, 503, 504) or status is None
                if attempt < self.settings.groq_max_retries and retryable:
                    # Exponential backoff; 429 on a free tier is expected, not exceptional.
                    await asyncio.sleep(min(0.6 * (2**attempt), 4.0))
                    continue
                log.warning("groq_failed", error=last_error, attempt=attempt)
                break

        return self._fallback(evidence, last_error)

    async def health(self) -> dict[str, object]:
        """Reports configuration and reachability without exposing the key."""
        if not self.available:
            return {
                "provider": "groq",
                "ok": False,
                "configured": False,
                "note": "GROQ_API_KEY not set - copilot degrades to evidence cards",
            }
        try:
            client = self._get_client()
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self.settings.groq_model,
                    messages=[{"role": "user", "content": "ok"}],
                    max_tokens=400,
                ),
                timeout=self.settings.groq_timeout_seconds,
            )
            return {
                "provider": "groq",
                "ok": True,
                "configured": True,
                "model": self.settings.groq_model,
                "tokens": response.usage.total_tokens if response.usage else None,
            }
        except Exception as exc:
            return {
                "provider": "groq",
                "ok": False,
                "configured": True,
                "model": self.settings.groq_model,
                "error": type(exc).__name__,
            }
