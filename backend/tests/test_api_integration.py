"""Integration tests against the real FastAPI app and a real MongoDB.

These exercise the whole stack - routing, validation, auth, repositories,
change engine - with only the market provider forced to deterministic demo
data, so assertions are stable without mocking the parts under test.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DEMO_MODE", "true")

TEST_DB = f"mw_test_{uuid.uuid4().hex[:10]}"

# pymongo's AsyncMongoClient binds to the event loop that created it, so the
# app-wide client and every test touching it must share one loop. Scoped here
# rather than globally, so unrelated async tests keep an isolated loop each.
pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def client():
    """Boot the app against a throwaway database, then drop it."""
    from app.core.config import get_settings

    settings = get_settings()
    settings.mongodb_db = TEST_DB
    settings.demo_mode = True

    from app.db.indexes import ensure_indexes
    from app.db.mongo import close_mongo_connection, connect_to_mongo
    from app.main import app

    db = await connect_to_mongo(db_name=TEST_DB)
    await ensure_indexes()

    # Route the app's shared services at the demo provider deterministically.
    from app.api import deps

    deps._market.settings.demo_mode = True
    deps._market.set_demo_step(0)
    deps._market.cache.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await db.client.drop_database(TEST_DB)
    await close_mongo_connection()


@pytest_asyncio.fixture(loop_scope="module")
async def auth(client):
    """A registered user plus ready-to-use auth headers."""
    email = f"user_{uuid.uuid4().hex[:10]}@example.com"
    res = await client.post(
        "/api/auth/register",
        json={"email": email, "password": "correct-horse-9", "display_name": "Tester"},
    )
    assert res.status_code == 201, res.text
    token = res.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "email": email}


class TestHealth:
    async def test_health_is_public_and_cheap(self, client):
        res = await client.get("/api/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"

    async def test_provider_health_never_leaks_credentials(self, client):
        res = await client.get("/api/health/providers")
        assert res.status_code == 200
        assert "gsk_" not in res.text
        assert "mongodb://" not in res.text
        assert "mongodb+srv://" not in res.text


class TestAuth:
    async def test_register_returns_token_and_user(self, client):
        email = f"new_{uuid.uuid4().hex[:8]}@example.com"
        res = await client.post(
            "/api/auth/register",
            json={"email": email, "password": "correct-horse-9", "display_name": "New"},
        )
        assert res.status_code == 201
        assert res.json()["user"]["email"] == email
        assert len(res.json()["access_token"]) > 20

    async def test_duplicate_email_rejected(self, client, auth):
        res = await client.post(
            "/api/auth/register",
            json={"email": auth["email"], "password": "correct-horse-9", "display_name": "Dup"},
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "CONFLICT"

    async def test_short_password_rejected(self, client):
        res = await client.post(
            "/api/auth/register",
            json={"email": "x@y.com", "password": "short", "display_name": "X"},
        )
        assert res.status_code == 422
        assert res.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_wrong_password_does_not_reveal_account_existence(self, client, auth):
        known = await client.post(
            "/api/auth/login", json={"email": auth["email"], "password": "wrong-password"}
        )
        unknown = await client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password"},
        )
        assert known.status_code == unknown.status_code == 401
        assert known.json()["error"]["message"] == unknown.json()["error"]["message"]

    async def test_login_round_trip(self, client, auth):
        res = await client.post(
            "/api/auth/login", json={"email": auth["email"], "password": "correct-horse-9"}
        )
        assert res.status_code == 200
        me = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {res.json()['access_token']}"},
        )
        assert me.json()["email"] == auth["email"]

    @pytest.mark.parametrize("path", ["/api/dashboard", "/api/watchlists", "/api/changes", "/api/stocks/TCS"])
    async def test_protected_routes_require_auth(self, client, path):
        res = await client.get(path)
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "UNAUTHORIZED"


class TestWatchlists:
    async def test_full_lifecycle(self, client, auth):
        h = auth["headers"]

        created = await client.post("/api/watchlists", json={"name": "Core"}, headers=h)
        assert created.status_code == 201
        wid = created.json()["id"]

        added = await client.post(f"/api/watchlists/{wid}/items", json={"symbol": "tcs"}, headers=h)
        assert added.status_code == 201
        assert added.json()["items"][0]["symbol"] == "TCS"  # normalised

        dup = await client.post(f"/api/watchlists/{wid}/items", json={"symbol": "TCS"}, headers=h)
        assert dup.status_code == 409

        await client.post(f"/api/watchlists/{wid}/items", json={"symbol": "INFY"}, headers=h)
        reordered = await client.post(
            f"/api/watchlists/{wid}/reorder", json={"symbols": ["INFY", "TCS"]}, headers=h
        )
        assert [i["symbol"] for i in reordered.json()["items"]] == ["INFY", "TCS"]

        renamed = await client.patch(f"/api/watchlists/{wid}", json={"name": "Renamed"}, headers=h)
        assert renamed.json()["name"] == "Renamed"

        removed = await client.delete(f"/api/watchlists/{wid}/items/TCS", headers=h)
        assert [i["symbol"] for i in removed.json()["items"]] == ["INFY"]

        assert (await client.delete(f"/api/watchlists/{wid}", headers=h)).status_code == 204
        assert (await client.get(f"/api/watchlists/{wid}", headers=h)).status_code == 404

    async def test_watchlists_are_private_to_their_owner(self, client, auth):
        other = await client.post(
            "/api/auth/register",
            json={
                "email": f"other_{uuid.uuid4().hex[:8]}@example.com",
                "password": "correct-horse-9",
                "display_name": "Other",
            },
        )
        other_h = {"Authorization": f"Bearer {other.json()['access_token']}"}
        mine = await client.post("/api/watchlists", json={"name": "Mine"}, headers=auth["headers"])
        wid = mine.json()["id"]

        assert (await client.get(f"/api/watchlists/{wid}", headers=other_h)).status_code == 404
        assert (await client.delete(f"/api/watchlists/{wid}", headers=other_h)).status_code == 404

    async def test_persists_across_sessions(self, client, auth):
        h = auth["headers"]
        created = await client.post("/api/watchlists", json={"name": "Persist"}, headers=h)
        await client.post(f"/api/watchlists/{created.json()['id']}/items", json={"symbol": "TCS"}, headers=h)
        # A completely new login must see the same data.
        again = await client.post(
            "/api/auth/login", json={"email": auth["email"], "password": "correct-horse-9"}
        )
        fresh = {"Authorization": f"Bearer {again.json()['access_token']}"}
        lists = await client.get("/api/watchlists", headers=fresh)
        assert any(w["name"] == "Persist" for w in lists.json())


class TestMarket:
    async def test_search_ranks_exact_symbol_first(self, client, auth):
        res = await client.get("/api/market/search?q=TCS", headers=auth["headers"])
        assert res.status_code == 200
        assert res.json()[0]["symbol"] == "TCS"

    async def test_retired_ticker_resolves_through_alias(self, client, auth):
        res = await client.get("/api/market/search?q=ZOMATO", headers=auth["headers"])
        assert res.json()[0]["symbol"] == "ETERNAL"

    async def test_quote_reports_freshness_and_demo_labelling(self, client, auth):
        res = await client.get("/api/market/quote/TCS", headers=auth["headers"])
        assert res.status_code == 200
        body = res.json()
        assert body["price"] is not None
        assert body["freshness"]["label"]
        assert body["freshness"]["is_synthetic"] is True  # demo mode must say so

    async def test_history_returns_bars(self, client, auth):
        res = await client.get("/api/market/history/TCS?period=3mo", headers=auth["headers"])
        assert res.status_code == 200
        assert len(res.json()["bars"]) > 10


class TestDashboardAndChanges:
    async def test_catch_up_flow_end_to_end(self, client, auth):
        """The product's core loop, over HTTP."""
        h = auth["headers"]
        from app.api import deps

        wid = (await client.post("/api/watchlists", json={"name": "Flow"}, headers=h)).json()["id"]
        for sym in ["TCS", "RELIANCE", "INFY"]:
            await client.post(f"/api/watchlists/{wid}/items", json={"symbol": sym}, headers=h)

        await client.post("/api/demo/reset", headers=h)

        first = await client.get("/api/dashboard?include_news=false", headers=h)
        assert first.status_code == 200
        assert first.json()["is_first_visit"] is True

        # The user opens TCS. Viewing is not acknowledging.
        detail = await client.get("/api/stocks/TCS", headers=h)
        assert detail.status_code == 200
        assert detail.json()["last_viewed_at"] is not None
        assert detail.json()["last_acknowledged_at"] is None

        # Market moves while they are away.
        deps._market.set_demo_step(1)
        deps._market.cache.clear()

        second = await client.get("/api/dashboard?include_news=false", headers=h)
        body = second.json()
        assert body["is_first_visit"] is False
        assert body["last_checked_at"] is not None
        assert len(body["meaningful_changes"]) >= 1

        tcs = next(c for c in body["meaningful_changes"] if c["symbol"] == "TCS")
        assert tcs["change_type"] == "COMPANY_SPECIFIC"
        assert tcs["metrics"]["price_change_pct"] < 0
        assert len(tcs["evidence"]) >= 4
        assert tcs["status"] in {"NEW", "IMPORTANT", "VIEWED"}
        # Score decomposition must add up and be explainable.
        b = tcs["breakdown"]
        assert b["total"] == pytest.approx(b["base_significance"] + b["user_adjustment"], abs=0.05)

        # Acknowledge, then confirm it persists and stays visible.
        ack = await client.post(f"/api/changes/{tcs['id']}/acknowledge", headers=h)
        assert ack.json()["status"] == "ACKNOWLEDGED"

        after = await client.get("/api/dashboard?include_news=false", headers=h)
        still = next((c for c in after.json()["meaningful_changes"] if c["symbol"] == "TCS"), None)
        assert still is not None, "an acknowledged change must remain visible as reviewed"
        assert still["status"] == "ACKNOWLEDGED"

    async def test_change_filters(self, client, auth):
        h = auth["headers"]
        assert (await client.get("/api/changes?status=ACKNOWLEDGED", headers=h)).status_code == 200
        assert (await client.get("/api/changes?severity=HIGH", headers=h)).status_code == 200

    async def test_unknown_change_is_404(self, client, auth):
        res = await client.get("/api/changes/chg_does_not_exist", headers=auth["headers"])
        assert res.status_code == 404

    async def test_empty_watchlist_dashboard_is_valid(self, client):
        fresh = await client.post(
            "/api/auth/register",
            json={
                "email": f"empty_{uuid.uuid4().hex[:8]}@example.com",
                "password": "correct-horse-9",
                "display_name": "Empty",
            },
        )
        h = {"Authorization": f"Bearer {fresh.json()['access_token']}"}
        res = await client.get("/api/dashboard", headers=h)
        assert res.status_code == 200
        assert res.json()["watchlist"] == []
        assert res.json()["catch_up"]["meaningful_count"] == 0


class TestCopilot:
    async def test_answers_are_grounded_or_degrade_cleanly(self, client, auth):
        """Either Groq answers from evidence, or the evidence itself is returned.

        Both outcomes are acceptable; a broken copilot must never break the app.
        """
        h = auth["headers"]
        wid = (await client.post("/api/watchlists", json={"name": "AI"}, headers=h)).json()["id"]
        await client.post(f"/api/watchlists/{wid}/items", json={"symbol": "TCS"}, headers=h)
        await client.get("/api/dashboard?include_news=false", headers=h)

        res = await client.post("/api/copilot/chat", json={"question": "Why is TCS highlighted?"}, headers=h)
        assert res.status_code == 200
        body = res.json()
        assert body["answer"]
        assert isinstance(body["grounded"], bool)
        if not body["grounded"]:
            assert body["degraded_reason"]

    async def test_empty_question_rejected(self, client, auth):
        res = await client.post("/api/copilot/chat", json={"question": ""}, headers=auth["headers"])
        assert res.status_code == 422


class TestDemoControls:
    async def test_step_and_reset(self, client, auth):
        h = auth["headers"]
        assert (await client.post("/api/demo/step?step=1", headers=h)).json()["step"] == 1
        assert (await client.post("/api/demo/reset", headers=h)).json()["reset"] is True
        assert (await client.get("/api/demo/status")).json()["step"] == 0

    async def test_step_is_range_validated(self, client, auth):
        res = await client.post("/api/demo/step?step=99", headers=auth["headers"])
        assert res.status_code == 422
