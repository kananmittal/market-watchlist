# Architecture

A modular monolith. The sophistication is meant to live in the domain model — persistent
state, meaningful change, evidence — not in the infrastructure.

---

## Module map

```
backend/app/
  core/           config, structured logging, typed errors, security, market calendar
  models/         domain objects and the shared enum vocabulary
  db/             Mongo client lifecycle + idempotent index definitions
  repositories/   data access, one module per aggregate
  providers/      external integrations behind interfaces
  services/       business logic: market data, change engine, news, memory, dashboard, copilot
  api/            routers, request/response schemas, mappers, dependencies

frontend/src/
  app/            routes: login, dashboard, stocks/[symbol], watchlists, changes
  components/     shell, change + evidence cards, copilot panel, chart, primitives
  lib/            typed API client, auth context, formatters, shared types
```

Dependencies point inwards: `api → services → repositories → db`, and `services → providers`.
Nothing in `core` or `models` imports upwards.

---

## The four layers of truth

Keeping these separate is the central design decision.

| Layer | Collections | Scope | Why |
|---|---|---|---|
| **Market truth** | `market_observations`, `price_history` | Global | One fetch of TCS serves every user watching TCS |
| **Event truth** | `news_events` | Global | One story is one event regardless of how many users see it |
| **User truth** | `user_symbol_state`, `activity_events` | Per user | What *this* person has seen |
| **Interpretation** | `change_events` | Per user | The same market fact means different things to different users |

The anti-pattern this avoids:

```
BAD    1000 users × their symbols × external API requests
GOOD   provider → shared symbol-level observations → cache/db → many users
```

The LLM is never a source of any of these layers.

---

## Data model

### `market_observations` — global
```
symbol, observed_at, received_at, source, source_timestamp,
price, open, high, low, close, previous_close, volume, change_pct,
benchmark_return_pct, sector_return_pct, quality, is_synthetic, notes[]
```
Unique on `(symbol, source, observed_at)`, which makes ingestion idempotent. TTL 30 days.

### `news_events` — global
```
event_id, symbol, event_type, headline, summary, source, source_url,
published_at, entity_confidence, event_significance, dedupe_key, article_count
```
Unique on `dedupe_key`. `article_count` records how many articles collapsed into one event.

### `user_symbol_state` — per user
```
user_id, symbol, first_added_at, last_viewed_at, last_acknowledged_at,
view_count, interest_score
```
Two timestamps, deliberately. `last_viewed_at` is the "since you last looked" anchor;
`last_acknowledged_at` records an explicit review. They are never set together.

### `change_events` — per user
```
id, user_id, symbol, detected_at, since, change_type, severity,
attention_score, primary_reason, status, metrics{}, breakdown{}, evidence[]
```
Evidence and the score breakdown are embedded, because they are meaningless apart from their
change and are always read together.

### Indexes

Declared in one idempotent module that runs at boot — this project's equivalent of migrations.

```
users(email) unique
watchlists(user_id, name) unique · (user_id, items.symbol)
market_observations(symbol, observed_at desc) · (symbol, source, observed_at) unique · TTL
news_events(symbol, published_at desc) · (dedupe_key) unique · TTL
user_symbol_state(user_id, symbol) unique · (user_id, last_viewed_at desc)
activity_events(user_id, created_at desc) · (user_id, symbol, created_at desc) · TTL
change_events(user_id, detected_at desc) · (user_id, status) · (user_id, attention_score desc)
```

---

## Request flow: loading the dashboard

```
GET /api/dashboard
  │
  ├─ find_one_and_update(users) ──▶ returns the PREVIOUS last_dashboard_view_at
  │     Atomic read-and-stamp. Returning the previous value is the whole point:
  │     it is "when did I last look", and two concurrent loads cannot both claim first.
  │
  ├─ one aggregation ────────────▶ every distinct symbol across the user's watchlists
  │
  ├─ asyncio.gather:
  │     quotes            one batched provider call for all symbols
  │     context           benchmark + every needed sector index, one batch
  │     user states       one query for all symbols
  │     news              cached, refreshed only where stale
  │     baselines         grouped by distinct anchor, not one query per symbol
  │
  ├─ change engine, per symbol (pure, in-memory)
  │
  ├─ merge statuses against stored ──▶ THEN persist
  │     Merging after writing cannot distinguish "was immaterial" from "is immaterial".
  │
  └─ rank by attention, build the catch-up summary
```

An N-symbol watchlist costs a constant number of round trips, not N.

---

## The change engine

Pure and deterministic. Takes a `ChangeInput`, returns a `ChangeEvent`. No I/O, which is why
it is cheap to unit test exhaustively.

```
                     ┌── abnormality        |return| / expected daily move   → 25
                     ├── relative move      divergence from benchmark        → 20
ChangeInput ────────▶├── volume anomaly     current / rolling average        → 15
                     ├── news significance  weighted, deduplicated           → 25
                     │                                    base significance  = 85
                     └── user relevance     bounded, additive                → 15
                                                                 attention   = 100
                            │
                            ├── classify   COMPANY_SPECIFIC | SECTOR_DRIVEN |
                            │              MARKET_DRIVEN | TECHNICAL | NO_MATERIAL_CHANGE
                            └── build evidence, ordered by contribution
```

Two invariants worth stating explicitly, both covered by tests:

1. **Severity is a function of base significance alone.** User interest cannot manufacture a
   HIGH. It reorders the feed; it never changes what the feed says is serious.
2. **No news means no assertion of a company cause.** An unexplained abnormal move is
   `TECHNICAL`. Only a divergence too large for the market or sector to explain overrides
   this — we report what the evidence supports, not what sounds most interesting.

---

## Attention lifecycle

```
NEW ──▶ VIEWED ──▶ ACKNOWLEDGED
 │         │              │
 │         └── user opened the stock
 │                        └── user explicitly said "reviewed"
 └──▶ STALE (after 7 days unreviewed)     └──▶ DISMISSED
```

Rules that took iteration to get right:

- Loading the dashboard advances nothing. Opening a stock moves `NEW → VIEWED`.
- An explicit user decision (`ACKNOWLEDGED` / `DISMISSED`) always survives recomputation.
- A change that was immaterial and becomes material returns to `NEW` — it should ask for
  attention again rather than inherit a stale status.
- `VIEWED` is anchored to the user's real `last_viewed_at`, because the engine also uses it as
  a placeholder for immaterial changes and that placeholder must never make an unopened stock
  look already seen.
- Acknowledging does **not** move `last_viewed_at`. Moving it would reset the comparison
  window, recompute the change as 0%, and make the item the user just reviewed disappear.

---

## Provider strategy

```
        get_quotes(symbols)
               │
     ┌─────────┴─────────┐         demo is NOT consulted here in live mode:
     ▼                   ▼         synthetic prices would disagree with real
  yfinance            jugaad       ones and raise phantom DATA_CONFLICTs
  (batch)          (enrichment)
     └─────────┬─────────┘
               ▼
          resolve()   real > synthetic, then provider priority, then freshness
               │       never averages; marks CONFLICTED beyond tolerance
               ▼
   nothing answered? ──▶ demo fallback, labelled "all live providers unavailable"
```

Synthetic rows are only persisted in demo mode. In live mode they would outrank real
observations on recency and corrupt every user's baseline.

---

## News pipeline

```
Google News RSS ──▶ normalise ──▶ resolve entity ──▶ classify ──▶ cluster ──▶ NewsEvent
   (per symbol)      strip           confidence       word-      by headline
                     publisher       < 0.5 dropped    boundary   similarity, plus
                     suffix                           keywords   same-type/same-day
                                                                 for singular events
```

Deduplication is a correctness requirement, not tidiness: three outlets covering one earnings
release must contribute one event's worth of significance, or widely-syndicated news
mechanically outranks genuinely bigger news. Corroboration across outlets adds a small capped
bonus.

Classification reads the **title only**. Google News summaries are HTML anchor blobs
containing base64 tracking URLs and unrelated headlines; classifying on them tagged routine
price updates as EARNINGS at 0.94 significance. Keywords match on word boundaries, because
substring matching made `ban` match inside `Bank` and labelled every bank headline
REGULATORY.

---

## Copilot

```
question ──▶ dashboard (WITHOUT advancing the anchor) ──▶ identify symbols
   ──▶ build bounded evidence package ──▶ Groq ──▶ grounded answer + evidence
                                          │
                                          └── timeout / 429 / empty completion
                                              ──▶ deterministic evidence cards
```

- The anchor is deliberately not advanced: asking a question must not count as "looking", or
  the next visit would report that nothing changed.
- Evidence is capped and truncated so a large watchlist cannot blow the context window.
- Identical question + evidence is cached briefly, because the free tier is a real constraint.
- Groq is called only for user-requested explanations — never per stock.
- The API key is server-side only and appears in no response, including health output.

---

## Failure behaviour

| Failure | Behaviour |
|---|---|
| yfinance down | jugaad tried, then demo fallback, labelled as such |
| All market providers down | Demo data, explicitly labelled "all live providers unavailable" |
| Providers disagree | Both stored, winner marked `CONFLICTED`, UI says "under verification" |
| News feed down | Change engine runs on market signals alone |
| Groq down / rate-limited | Evidence cards returned instead, with `degraded_reason` |
| MongoDB down | App still boots; `/api/health/providers` reports it rather than crashing opaquely |
| Backend asleep | Frontend reports the server is waking, not a hard error |
| Data older than expected | Labelled `DELAYED` or `STALE`; outside hours, "At Fri 04 Sep close" |

Nothing in this table is a stack trace shown to a user.

---

## Frontend

Next.js App Router, TypeScript, Tailwind v4, no state-management or charting dependencies.

- The token is cached in `localStorage` for convenience only. Every piece of user state lives
  server-side, so another device restores the same view. Losing `localStorage` costs a
  re-login, never data.
- Severity and review state always pair colour with a text label and a glyph.
- Charts are inline SVG.
- Every screen has loading, empty, error and unavailable states.

---

## What was deliberately not built

Kafka, Kubernetes, microservices, a vector database, a background worker, Redis, a charting
library, a state-management library, trading, recommendations, or portfolio optimisation.

Free hosting sleeps, so correctness must not depend on a long-running process. Reads refresh
on demand when the cache is cold, which removes the need for a scheduler entirely.
