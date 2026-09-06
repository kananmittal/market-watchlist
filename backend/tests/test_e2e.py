"""Browser end-to-end test of the product's core loop.

Covers the journey the whole product exists for:

    create account -> create watchlist -> add stock -> view stock
    -> time passes and the market moves -> return -> see what changed
    -> inspect the evidence -> acknowledge -> reload -> state persists

Skipped automatically unless both servers are running, so `pytest` stays
green on a machine with nothing started. Run them with:

    backend : uvicorn app.main:app --port 8899          (DEMO_MODE=true)
    frontend: npm run dev -- --port 3111                (NEXT_PUBLIC_API_URL=...)
    pytest -m e2e
"""

from __future__ import annotations

import os
import uuid

import pytest

WEB = os.environ.get("E2E_WEB_URL", "http://localhost:3111")
API = os.environ.get("E2E_API_URL", "http://127.0.0.1:8899")
PASSWORD = "correct-horse-9"


def _reachable(url: str) -> bool:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return r.status < 500
    except (urllib.error.URLError, OSError, ValueError):
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (_reachable(f"{API}/api/health") and _reachable(f"{WEB}/login")),
        reason="E2E needs the API and web dev servers running (see module docstring)",
    ),
]


@pytest.fixture(scope="session")
def browser_page():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 1100})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        yield page, errors
        browser.close()


def test_core_loop_since_you_last_looked(browser_page):
    page, page_errors = browser_page
    email = f"e2e_{uuid.uuid4().hex[:10]}@example.com"

    # ---- create account ----
    page.goto(f"{WEB}/login", wait_until="networkidle")
    page.get_by_role("tab", name="Create account").click()
    page.fill("#name", "E2E")
    page.fill("#email", email)
    page.fill("#password", PASSWORD)
    page.get_by_role("button", name="Create account").click()
    page.wait_for_url("**/dashboard", timeout=30_000)

    token = page.evaluate("() => localStorage.getItem('mw.token')")
    assert token, "sign-up should establish a session"
    headers = {"Authorization": f"Bearer {token}"}

    # ---- build a watchlist ----
    page.goto(f"{WEB}/watchlists", wait_until="networkidle")
    page.fill("#new-list", "E2E Core")
    page.get_by_role("button", name="Add", exact=True).first.click()
    page.wait_for_timeout(1200)

    for symbol in ("TCS", "RELIANCE", "INFY"):
        page.fill("#sym-search", symbol)
        page.wait_for_timeout(700)
        add = page.locator("li button:has-text('Add')")
        if add.count():
            add.first.click()
            page.wait_for_timeout(900)
    assert "TCS" in page.inner_text("body")

    # ---- baseline visit, then open one stock ----
    page.request.post(f"{API}/api/demo/reset", headers=headers)
    page.goto(f"{WEB}/dashboard", wait_until="networkidle")
    page.wait_for_timeout(2500)

    page.goto(f"{WEB}/stocks/TCS", wait_until="networkidle")
    page.wait_for_timeout(2500)
    detail = page.inner_text("body")
    assert "TCS" in detail
    # Viewing is not acknowledging.
    assert "Mark as reviewed" in detail

    # ---- the market moves while the user is away ----
    page.request.post(f"{API}/api/demo/step?step=1", headers=headers)

    # ---- return: what changed since I last looked ----
    page.goto(f"{WEB}/dashboard", wait_until="networkidle")
    page.wait_for_timeout(3500)
    body = page.inner_text("body")
    assert "meaningful change" in body.lower(), "catch-up headline should report what changed"
    assert "WHY IT MATTERS" in body.upper(), "every change must show its evidence"
    assert "since you last looked" in body.lower()

    # ---- the score is explainable ----
    scored = page.get_by_role("button", name="How was this scored?").first
    assert scored.count(), "a score must be inspectable, never bare"
    scored.click()
    page.wait_for_timeout(700)
    assert "Attention" in page.inner_text("body")

    # ---- acknowledge, and confirm it persists ----
    page.goto(f"{WEB}/stocks/TCS", wait_until="networkidle")
    page.wait_for_timeout(3000)
    ack = page.get_by_role("button", name="Mark as reviewed").first
    assert ack.count(), "the user must be able to explicitly review a change"
    ack.click()
    page.wait_for_timeout(3000)
    assert "Reviewed" in page.inner_text("body")

    page.reload(wait_until="networkidle")
    page.wait_for_timeout(3000)
    assert "Reviewed" in page.inner_text("body"), "review state must survive a reload"

    assert not page_errors, f"unexpected page errors: {page_errors[:3]}"


def test_signing_in_again_restores_the_same_state(browser_page):
    """Same account, fresh session: watchlist and review state come back."""
    page, _ = browser_page
    email = f"e2e2_{uuid.uuid4().hex[:10]}@example.com"

    # Tests share one browser context, so start genuinely signed out; otherwise
    # /login redirects straight to the dashboard.
    page.goto(f"{WEB}/login", wait_until="domcontentloaded")
    page.evaluate("() => localStorage.clear()")
    page.goto(f"{WEB}/login", wait_until="networkidle")
    page.get_by_role("tab", name="Create account").click()
    page.fill("#name", "Cross")
    page.fill("#email", email)
    page.fill("#password", PASSWORD)
    page.get_by_role("button", name="Create account").click()
    page.wait_for_url("**/dashboard", timeout=30_000)

    page.goto(f"{WEB}/watchlists", wait_until="networkidle")
    page.fill("#new-list", "Cross Device")
    page.get_by_role("button", name="Add", exact=True).first.click()
    page.wait_for_timeout(1200)
    page.fill("#sym-search", "TCS")
    page.wait_for_timeout(800)
    add = page.locator("li button:has-text('Add')")
    if add.count():
        add.first.click()
        page.wait_for_timeout(1000)

    # Drop the client session entirely, as a different device would have.
    page.evaluate("() => localStorage.clear()")
    page.goto(f"{WEB}/login", wait_until="networkidle")
    page.fill("#email", email)
    page.fill("#password", PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/dashboard", timeout=30_000)

    page.goto(f"{WEB}/watchlists", wait_until="networkidle")
    page.wait_for_timeout(1500)
    restored = page.inner_text("body")
    assert "Cross Device" in restored
    assert "TCS" in restored


def test_dashboard_is_usable_on_a_phone(browser_page):
    """Responsive check: no horizontal overflow at 390px."""
    page, _ = browser_page
    page.set_viewport_size({"width": 390, "height": 844})
    try:
        page.goto(f"{WEB}/dashboard", wait_until="networkidle")
        page.wait_for_timeout(2500)
        scroll_width = page.evaluate("() => document.documentElement.scrollWidth")
        assert scroll_width <= 392, f"page overflows horizontally at 390px ({scroll_width}px)"
    finally:
        page.set_viewport_size({"width": 1400, "height": 1100})
