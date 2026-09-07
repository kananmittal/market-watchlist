# Since You Last Looked

**A time-aware market watchlist that remembers what you saw and tells you what meaningfully changed since.**

**▶ To run it: [RUN.md](RUN.md)** — verified setup, a two-minute review walkthrough and
troubleshooting. No API key or market-data account needed.

Traditional watchlists show you what the market looks like *now*. They have no memory, so
every visit starts from zero and you have to work out for yourself what is new. This system
remembers what each user has already seen and identifies what has **meaningfully changed
since then** — then shows the evidence for why it says so.

```
USER OPENS APP
      ↓
WHEN DID I LAST LOOK?   →  the reference point is per user, per symbol
      ↓
WHAT CHANGED SINCE?     →  measured from that point, not from midnight
      ↓
WHICH CHANGES MATTER?   →  scored against each stock's own normal behaviour
      ↓
WHY DO THEY MATTER?     →  every score ships with its evidence
      ↓
HAVE I SEEN THEM?       →  viewing ≠ acknowledging
      ↓
SYSTEM REMEMBERS        →  state is server-side, so any device resumes
```

---

## What makes this different

**Meaningful change is not a fixed threshold.** "Anything above 2%" is the obvious rule and
it is wrong: a 2% move in a placid large cap and a 2% move in a volatile small cap are
different events. Every move is normalised by that symbol's own expected daily move.

**Attribution, not just detection.** A 4% fall when the whole sector fell 4% is not the same
story as a 4% fall while the index rose. Every change is classified as `COMPANY_SPECIFIC`,
`SECTOR_DRIVEN`, `MARKET_DRIVEN`, `TECHNICAL` or `NO_MATERIAL_CHANGE`.

**Personal interest ranks, it never inflates.** A stock you check constantly is ranked higher,
but cannot be promoted to HIGH severity on a quiet day. Severity comes from base significance
alone; interest is a bounded additive adjustment. There is a test asserting exactly this.

**Evidence, never a bare score.** "Attention: 87" with no explanation is the anti-pattern this
product exists to avoid. Every score expands into the components that produced it.

**Viewing is not acknowledging.** Loading the dashboard does not mark anything as reviewed.
Opening a stock sets `last_viewed_at`. Only an explicit action sets `last_acknowledged_at`.

**The AI is an explanation layer, not the product.** The change engine is fully deterministic.
Groq explains the evidence the backend already computed; with Groq unavailable, the evidence
cards still answer the question.

---

## Screenshot of the core idea

The dashboard leads with what changed, ranked, each with its evidence:

```
You were away 17 hours. 3 meaningful changes and 2 normal movements.
2 high attention · 1 medium · 2 normal · 3 awaiting review     NIFTY 50 +0.20%

┌─ TCS   Tata Consultancy Services                              -4.29%  ▲ High ─┐
│  Tata Consultancy Services down 4.3% since you last looked - company-specific │
│  Company-specific · Company event · ● Unreviewed · since 17 hours ago         │
│                                                                                │
│  WHY IT MATTERS                                                                │
│   ◱ Price fell 4.29% since you last looked                                    │
│   ◇ Typical daily movement is ±1.51%; this is 2.8x a normal day               │
│   ⇅ NIFTY 50 is up 0.20% - underperforming by 4.49 points                     │
│   ⊞ NIFTY IT is down 0.80%                                                    │
│   ▤ Volume is 2.4x its recent average (significant)                           │
│                                                                                │
│  [How was this scored?]  [Open TCS]              [Mark as reviewed]           │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

## The meaningful-change algorithm

A base significance out of 85, plus a bounded user adjustment out of 15.

| Component | Max | What it measures |
|---|---:|---|
| Abnormality | 25 | `\|return\| / expected daily move` — how unusual for *this* stock |
| Benchmark-relative | 20 | Divergence from NIFTY 50, in multiples of a normal day |
| Volume anomaly | 15 | Current volume vs its rolling average |
| News significance | 25 | Weighted significance of the most material event |
| **Base significance** | **85** | Severity is derived from this alone |
| User relevance | +15 | Bounded, additive. Affects ranking only |

```
attention_score = base_significance + user_adjustment      (clamped 0-100)
severity        = f(base_significance)                     (interest excluded)
```

Worked example, matching the spec:

```
Base significance = 42,  user adjustment = +8  →  attention 50   (MEDIUM)
Base significance = 5,   user adjustment = +8  →  attention 13   (NORMAL)
```

Scores use piecewise-linear saturating curves, so 1.99x and 2.01x volume do not score
dramatically differently.

**Expected daily move** is resolved in preference order:

1. NSE's published `cmDailyVolatility` (exchange-computed — the most credible)
2. Standard deviation of recent daily returns
3. ATR as a percentage
4. A conservative default

**Classification order** matters. With no news, an abnormal move is reported as `TECHNICAL`
rather than asserting a company cause we have no evidence for. Only a divergence too large
for the market or sector to explain overrides that. Divergence is measured *sector-relative*
when a sector index exists, so a bank falling in line with every other bank is
`SECTOR_DRIVEN`, not company-specific.

---

## Architecture

A modular monolith. No Kafka, no Kubernetes, no microservices, no vector database.

```
        Next.js frontend  ──HTTP──▶  FastAPI backend  ──▶  MongoDB Atlas
                                            │
              ┌─────────────────────────────┼──────────────────────────┐
              ▼                             ▼                          ▼
      Market data service           Change engine              News engine
   yfinance → jugaad → demo    abnormality / relative /     Google News RSS
   batched · cached · shared    volume / news / user        normalise → classify
   conflict-aware                        │                  → dedupe → NewsEvent
                                         ▼
                                 Evidence builder
                                    │        │
                          Deterministic UI   Groq copilot (explanation only)
```

### Four layers of truth, kept strictly separate

| Layer | Storage | Scope |
|---|---|---|
| Market truth | `market_observations`, `price_history` | **Global** — one fetch serves every user |
| Event truth | `news_events` | **Global**, deduplicated by story |
| User truth | `user_symbol_state`, `activity_events` | **Per user** |
| Interpretation | `change_events` | **Per user** |

Duplicating market snapshots per user does not scale, so the system never does. One fetch of
TCS serves everyone watching TCS.

### Market data providers

Behind a single `MarketDataProvider` interface, so no upstream is a hard dependency:

| Provider | Role | Notes |
|---|---|---|
| **yfinance** | Primary | One multi-ticker download per watchlist, not one request per symbol |
| **jugaad-data** (NSE) | Enrichment | NSE often returns partial payloads, so it degrades to `None` rather than raising. Its real value is the exchange-published daily volatility |
| **demo** | Fallback + demo mode | Deterministic: a pure function of `(symbol, step)`, so a scripted demo reproduces exactly |

Disagreements are **never averaged**. Resolution prefers real over synthetic, then provider
priority, then freshness — and marks the result `CONFLICTED`, surfacing both values, when the
spread exceeds tolerance.

### Honest data states

Every observation carries `observed_at`, `received_at`, `source`, `source_timestamp` and
`quality`. The UI labels data `LIVE`, `DELAYED`, `STALE` or `UNAVAILABLE`, and is
market-session aware — outside trading hours it reads "At Fri 04 Sep close" rather than
alarmingly calling normal last-session data stale. Demo figures are always labelled as demo.

---

## Running locally

Full, verified reviewer instructions — including the click-by-click walkthrough and
troubleshooting — are in **[RUN.md](RUN.md)**. The short version:

**Prerequisites:** Python 3.11+ (macOS `python3` is often 3.9 — use `python3.12`), Node 20+,
MongoDB (local or Atlas).

```bash
git clone https://github.com/kananmittal/market-watchlist.git
cd market-watchlist
cp .env.example .env          # optional in demo mode; every setting has a working default
```

**Backend**

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
DEMO_MODE=true uvicorn app.main:app --reload --port 8000
```

**Frontend**

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open http://localhost:3000. API docs are at http://localhost:8000/docs, health at
http://localhost:8000/api/health.

No API key is required: with no `GROQ_API_KEY` the copilot degrades to evidence cards, and
`DEMO_MODE=true` needs no market credentials at all.

### Demo mode

Set `DEMO_MODE=true` to run entirely on deterministic synthetic data — no market credentials,
no internet. The change engine, persistence and UI all run for real; only the prices are
generated, and they are labelled as such everywhere. Real market moves are usually small, so
the "since you last looked" story is much easier to see this way.

To walk the scripted story:

```bash
curl -X POST $API/api/demo/reset  -H "Authorization: Bearer $TOKEN"   # clean slate
# load the dashboard (baseline), open a stock, then:
curl -X POST "$API/api/demo/step?step=1" -H "Authorization: Bearer $TOKEN"
# reload the dashboard → Catch Me Up reports what changed
```

`reset` exists because synthetic observations accumulate as the scenario is stepped; without
it a second run would baseline against the previous step and report that nothing changed. It
clears only synthetic rows — real observations are never touched.

[RUN.md](RUN.md) has a copy-pasteable version of this that creates its own account.

---

## Testing

```bash
cd backend
pytest                    # 118 unit + integration tests
ruff check app/ tests/    # lint
mypy app/                 # type check

cd ../frontend
npx tsc --noEmit && npx eslint src && npm run build
```

The 3 Playwright browser tests run as a separate suite, because Playwright's sync API installs
its own event loop, which prevents pytest-asyncio creating one for any async test collected
afterwards. They need Playwright and both servers running — see
[RUN.md](RUN.md#8-tests) for the exact commands:

```bash
pip install playwright && playwright install chromium
pytest -m e2e             # skips itself if the servers are not up
```

---

## Environment variables

Nothing is required to run it locally in demo mode — every setting has a working default.
See [`.env.example`](.env.example) for the full list.

| Variable | Required | Purpose |
|---|---|---|
| `GROQ_API_KEY` | For AI prose | Copilot. Without it the copilot returns the evidence instead. `GROQ` is accepted as a shorthand |
| `MONGODB_URI` | Non-local DB | Database. Defaults to `mongodb://localhost:27017`. `DATABASE_URL` accepted as an alias |
| `JWT_SECRET` | Production | Token signing; 32+ random characters |
| `NEXT_PUBLIC_API_URL` | Frontend | Public backend URL |
| `CORS_ORIGINS` | Production | Allowed origins; `*.vercel.app` always permitted |
| `DEMO_MODE` | No | Deterministic synthetic data |
| `GROQ_MODEL` | No | Defaults to `openai/gpt-oss-120b` |

Upstox variables are **optional** and unnecessary — yfinance plus the demo provider cover
everything the product needs.

---

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for exact steps. Target is a zero-cost stack:

| Layer | Platform |
|---|---|
| Frontend | Vercel Hobby |
| Backend | Render free web service |
| Database | MongoDB Atlas M0 free tier |

Render's free tier sleeps after ~15 minutes of inactivity and has an ephemeral filesystem, so
nothing is stored locally and correctness never depends on a long-running worker. When the
cache is cold, a request refreshes and persists on demand.

---

## Design decisions worth arguing about

**Why MongoDB rather than PostgreSQL?** Change events carry a variable-length evidence list
and per-component score breakdowns — document-shaped data that would otherwise need a join
table read on every dashboard render. Watchlist items are embedded in their parent because
they are always read together and are bounded in number. Index definitions live in one
idempotent module that runs at boot, which is this project's equivalent of migrations.

**Why no charting library?** The chart is inline SVG. It keeps the bundle small, renders
deterministically, and the shape is all the page needs.

**Why is the copilot in a sidebar?** Because AI is the explanation layer, not the product. The
deterministic evidence has to stand on its own, and the layout should say so.

**Why does an acknowledged change stay visible?** Acknowledging deliberately does not move
`last_viewed_at`. Moving it would reset the comparison window, so the change the user just
reviewed would recompute as a 0% move and vanish — the opposite of confirming their action.

---

## Known limitations

- **Cross-outlet news dedup is partial.** Multiple articles about one earnings release are
  reliably collapsed. Two differently-worded headlines about the same story (Reuters'
  "$7.4 billion" and Upstox's "₹70,000 crore") are not always merged; merging them
  incorrectly would be worse than leaving them separate.
- **Index comparison windows differ.** A stock's move is measured since the user last looked;
  the index move is its own session change. Storing a per-user index baseline would be more
  precise. The UI states which window each figure covers.
- **`jugaad-data` frequently returns partial payloads** to non-browser clients, so NSE-native
  live quotes are best-effort. yfinance carries the load.
- **Free-tier cold starts.** The first request after the backend sleeps takes 30–60 seconds.
  The frontend reports this as the server waking rather than as a failure.
- **The market calendar is a static holiday list**, deliberately simple and replaceable. A
  missing holiday degrades to "market appears open but no ticks", which the freshness layer
  already handles.

---

## Not built, deliberately

No trading, no buy/sell recommendations, no portfolio optimisation, no twenty indicators, no
social features, no vector database, no message queue. The sophistication is meant to come
from persistent state, meaningful change, user context, evidence and explanation — not from
infrastructure.

---

*Market data is for information only and may be delayed. Nothing here is investment advice.*
