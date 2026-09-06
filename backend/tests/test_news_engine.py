"""Unit tests for news normalisation, classification and deduplication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models.enums import NewsEventType
from app.providers.news_provider import RawArticle
from app.services.news_engine import (
    NewsEngine,
    classify,
    jaccard,
    normalize_title,
    resolve_entity,
    strip_html,
    tokenize,
)


def article(
    title: str,
    *,
    source: str = "Reuters",
    hours_ago: float = 1.0,
    summary: str = "",
    link: str = "https://example.test/a",
) -> RawArticle:
    return RawArticle(
        title=title,
        link=link,
        published_at=datetime.now(UTC) - timedelta(hours=hours_ago),
        source=source,
        summary=summary,
    )


class TestNormalizeTitle:
    def test_strips_google_news_publisher_suffix(self):
        assert normalize_title("TCS Q2 profit rises 8% - Reuters") == "TCS Q2 profit rises 8%"

    def test_leaves_clean_titles_alone(self):
        assert normalize_title("TCS Q2 profit rises 8%") == "TCS Q2 profit rises 8%"

    def test_handles_empty(self):
        assert normalize_title("") == ""


class TestStripHtml:
    def test_removes_anchor_blobs(self):
        raw = '<a href="https://news.google.com/rss/x?oc=5" target="_blank">TCS results</a>'
        assert strip_html(raw) == "TCS results"

    def test_collapses_whitespace(self):
        assert strip_html("<p>a</p>   <p>b</p>") == "a b"


class TestClassification:
    @pytest.mark.parametrize(
        "title,expected",
        [
            ("TCS Q4 Results Preview: net profit expected to rise", NewsEventType.EARNINGS),
            ("Reliance to acquire stake in renewable firm", NewsEventType.MERGER_ACQUISITION),
            ("SEBI issues notice to company over disclosure", NewsEventType.REGULATORY),
            ("NCLT admits insolvency plea against firm", NewsEventType.LEGAL),
            ("Infosys CFO resigns after four years", NewsEventType.MANAGEMENT),
            ("Company announces dividend of Rs 70 per share", NewsEventType.CORPORATE_ACTION),
            ("TCS arm plans to invest Rs 70,000 crore in data centre", NewsEventType.PRODUCT_BUSINESS),
            ("Brokerage raises target price on HDFC Bank", NewsEventType.ANALYST),
        ],
    )
    def test_maps_headlines_to_event_types(self, title, expected):
        assert classify(title)[0] is expected

    def test_material_events_outrank_commentary(self):
        _, earnings = classify("TCS Q4 results: net profit rises 12%")
        _, analyst = classify("Brokerage raises target price on TCS")
        _, generic = classify("TCS Share Price today: down 2.08%")
        assert earnings > analyst > generic

    @pytest.mark.parametrize(
        "title",
        [
            "Stocks to watch: TCS, Reliance, Infosys",
            "Top gainers and losers on Nifty today",
            "TCS Share Price August 31: Down 2.08% to Rs 3,157",
            "Tata Consultancy Services Ltd. Stock Hits 52-Week Low",
        ],
    )
    def test_routine_wire_copy_is_low_significance(self, title):
        event_type, significance = classify(title)
        assert event_type is NewsEventType.GENERAL
        assert significance <= 0.2

    def test_ignores_summary_because_feeds_are_unreliable(self):
        """Google News summaries are HTML link farms; they must not drive scoring."""
        polluted = '<a href="x">TCS Q4 results net profit earnings revenue</a>'
        event_type, significance = classify("TCS Share Price today: down 2%", polluted)
        assert event_type is NewsEventType.GENERAL
        assert significance <= 0.2


class TestEntityResolution:
    def test_exact_symbol_match_is_confident(self):
        assert resolve_entity("TCS", "TCS Q4 results beat estimates") >= 0.9

    def test_full_company_name_match(self):
        assert resolve_entity("TCS", "Tata Consultancy Services announces buyback") >= 0.85

    def test_unrelated_headline_scores_low(self):
        assert resolve_entity("TRENT", "Nifty ends higher led by banking stocks") < 0.5

    def test_low_confidence_articles_are_dropped(self):
        engine = NewsEngine()
        events = engine.build_events("TRENT", [article("Nifty ends higher on banking strength")])
        assert events == []


class TestDeduplication:
    def test_three_outlets_one_earnings_release_becomes_one_event(self):
        """Spec section 11: three articles about one event are not three events."""
        engine = NewsEngine()
        events = engine.build_events(
            "TCS",
            [
                article("TCS Q4 results: net profit rises 12% to Rs 12,400 crore", source="Reuters"),
                article("TCS Q4 net profit up 12%, revenue beats estimates", source="Mint"),
                article("Tata Consultancy Services posts 12% rise in Q4 profit", source="ET"),
            ],
        )
        assert len(events) == 1
        assert events[0].article_count == 3

    def test_distinct_stories_stay_separate(self):
        engine = NewsEngine()
        events = engine.build_events(
            "TCS",
            [
                article("TCS Q4 results: net profit rises 12%"),
                article("SEBI issues notice to TCS over disclosure lapse"),
            ],
        )
        assert len(events) == 2
        assert {e.event_type for e in events} == {NewsEventType.EARNINGS, NewsEventType.REGULATORY}

    def test_corroboration_bonus_is_capped(self):
        """Widely syndicated news must not outrank genuinely bigger news on volume."""
        engine = NewsEngine()
        many = [article(f"TCS Q4 results: net profit rises 12% ({i})") for i in range(20)]
        events = engine.build_events("TCS", many)
        assert len(events) == 1
        assert events[0].event_significance <= 0.96

    def test_dedupe_key_is_stable_and_symbol_scoped(self):
        engine = NewsEngine()
        arts = [article("TCS Q4 results: net profit rises 12%")]
        first = engine.build_events("TCS", arts)[0]
        second = engine.build_events("TCS", arts)[0]
        assert first.dedupe_key == second.dedupe_key
        assert first.dedupe_key.startswith("TCS:")


class TestFiltering:
    def test_old_articles_are_excluded(self):
        engine = NewsEngine()
        events = engine.build_events(
            "TCS", [article("TCS Q4 results announced", hours_ago=24 * 30)], max_age_days=7
        )
        assert events == []

    def test_results_are_ranked_by_weighted_significance(self):
        engine = NewsEngine()
        events = engine.build_events(
            "TCS",
            [
                article("TCS Share Price today: down 2%"),
                article("TCS Q4 results: net profit rises 12%"),
            ],
        )
        assert events[0].event_type is NewsEventType.EARNINGS
        assert events[0].weighted_significance > events[-1].weighted_significance

    def test_limit_is_respected(self):
        engine = NewsEngine()
        arts = [article(f"TCS announces unrelated development number {i}") for i in range(30)]
        assert len(engine.build_events("TCS", arts, limit=3)) <= 3

    def test_empty_input_is_safe(self):
        assert NewsEngine().build_events("TCS", []) == []


class TestTextUtilities:
    def test_tokenize_drops_stopwords_and_short_tokens(self):
        tokens = tokenize("The TCS results are in for the quarter")
        assert "the" not in tokens and "are" not in tokens
        assert "tcs" in tokens and "results" in tokens

    def test_jaccard_bounds(self):
        a, b = tokenize("tcs quarterly profit rises"), tokenize("tcs quarterly profit rises")
        assert jaccard(a, b) == 1.0
        assert jaccard(a, tokenize("reliance refinery expansion plan")) < 0.2
        assert jaccard(frozenset(), a) == 0.0


class TestGracefulDegradation:
    async def test_provider_failure_returns_empty_not_exception(self, monkeypatch):
        engine = NewsEngine()

        async def boom(_symbol):
            raise RuntimeError("feed down")

        monkeypatch.setattr(engine.provider, "fetch_for_symbol", boom)
        assert await engine.fetch_and_normalize("TCS") == []

    async def test_batch_failure_returns_empty_buckets(self, monkeypatch):
        engine = NewsEngine()

        async def boom(_symbols, **_kw):
            raise RuntimeError("feed down")

        monkeypatch.setattr(engine.provider, "fetch_for_symbols", boom)
        result = await engine.fetch_and_normalize_many(["TCS", "INFY"])
        assert result == {"TCS": [], "INFY": []}
