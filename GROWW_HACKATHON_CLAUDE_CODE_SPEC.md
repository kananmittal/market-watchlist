# Groww Hackathon --- Time-Aware Market Watchlist

## End-to-End Implementation Specification for Claude Code

**Status:** Implementation-ready master specification\
**Primary goal:** Build, test, commit, push, and deploy a polished,
zero-cost hackathon submission end-to-end.\
**Implementation mode:** Long autonomous Claude Code session. Work
carefully; do not rush.\
**LLM provider:** Groq free tier via `GROQ_API_KEY`.\
**Primary product principle:** Do not build an obvious watchlist. Build
a stateful market-observation system that remembers what the user has
seen and surfaces what meaningfully changed since.

------------------------------------------------------------------------

# 1. Challenge statement

Minimum required capabilities:

-   Create and manage a watchlist
-   View latest market information
-   Return later and see what has changed

The participant decides:

-   What counts as a meaningful change
-   What information to surface
-   How state persists across sessions/devices
-   How stale, delayed, or conflicting data is handled
-   How the system scales to larger watchlists and more users
-   Where to keep things simple versus where to add complexity

The product should therefore demonstrate **product judgment, engineering
judgment, persistence, explainability, resilience, and thoughtful UX**.

------------------------------------------------------------------------

# 2. Product thesis

The product is NOT primarily:

-   an AI chatbot
-   a stock screener
-   a charting application
-   a portfolio optimizer
-   a trading system
-   a generic "AI-powered watchlist"

The product IS:

> **A time-aware watchlist that remembers what the user saw and tells
> them what meaningfully changed since they last looked.**

Core loop:

``` text
USER OPENS APP
      ↓
WHEN DID I LAST LOOK?
      ↓
WHAT CHANGED SINCE?
      ↓
WHICH CHANGES ARE MATERIAL?
      ↓
WHY DO THEY MATTER?
      ↓
HAVE I SEEN THEM?
      ↓
USER REVIEWS / ACKNOWLEDGES
      ↓
SYSTEM REMEMBERS
      ↓
NEXT VISIT
```

This loop is the central product requirement. Every feature must support
it.

------------------------------------------------------------------------

# 3. Product concept

Working concept name should remain undecided. Do NOT invent a generic
fintech name such as "Pulse". Naming is intentionally deferred until the
product is implemented and its personality is clear.

The primary experience should be called conceptually:

**"Since you last looked"**

and the primary catch-up action should be:

**"Catch me up"**

Avoid overusing "AI" in product copy. AI is an explanation layer, not
the product itself.

------------------------------------------------------------------------

# 4. Core architecture

Use a modular monolith, not microservices.

Recommended architecture:

``` text
                         ┌─────────────────────┐
                         │       USER          │
                         └──────────┬──────────┘
                                    │
                                    ▼
                         ┌─────────────────────┐
                         │      FRONTEND       │
                         │                     │
                         │  Home / Watchlist   │
                         │  Stock Detail       │
                         │  Change Feed        │
                         │  Copilot            │
                         └──────────┬──────────┘
                                    │
                                  HTTP
                                    │
                                    ▼
                    ┌────────────────────────────┐
                    │       FASTAPI BACKEND       │
                    └─────────────┬──────────────┘
                                  │
          ┌───────────────────────┼────────────────────────┐
          │                       │                        │
          ▼                       ▼                        ▼
 ┌────────────────┐      ┌────────────────┐      ┌────────────────┐
 │ Watchlist      │      │ User Context   │      │ Market Data    │
 │ Service        │      │ & Activity     │      │ Service        │
 └───────┬────────┘      └───────┬────────┘      └───────┬────────┘
         │                       │                       │
         │                       │              ┌────────┴────────┐
         │                       │              │                 │
         │                       │              ▼                 ▼
         │                       │        Primary provider    Fallback
         │                       │
         │                       ▼
         │                 ┌──────────────┐
         │                 │ User Memory  │
         │                 └──────────────┘
         │
         └──────────────────────────┬───────────────────────────┐
                                    ▼                           ▼
                           ┌────────────────┐           ┌────────────────┐
                           │ Change Engine  │           │ News/Event     │
                           │                │◄──────────│ Engine         │
                           └───────┬────────┘           └────────────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │ Attention Engine │
                          └────────┬─────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │ Evidence Builder │
                          └────────┬─────────┘
                                   │
                          ┌────────┴────────┐
                          ▼                 ▼
                   Deterministic UI     Groq Copilot
```

Logical modules:

``` text
backend/
  api/
  services/
  providers/
  models/
  repositories/
  jobs/
  core/
  tests/
```

Do not introduce Kafka, Kubernetes, microservices, vector databases, or
unnecessary infrastructure.

------------------------------------------------------------------------

# 5. Four layers of truth

Maintain a strict separation between:

## 5.1 Market truth

Facts about what happened:

-   price
-   OHLC
-   volume
-   market index
-   sector index
-   historical baseline
-   trading session
-   source
-   source timestamp
-   freshness
-   quality

## 5.2 Event truth

What happened around a security:

-   news
-   corporate event
-   earnings
-   regulatory event
-   sector event
-   technical event

## 5.3 User truth

What this user has seen or appears to care about:

-   last viewed
-   recently searched
-   recently added
-   frequency of viewing
-   recent news interactions
-   acknowledged changes
-   copilot interactions

## 5.4 Product interpretation

What deserves attention:

-   meaningful change
-   attention score
-   severity
-   primary reason
-   evidence
-   explanation

Do not allow the LLM to become the source of market truth.

------------------------------------------------------------------------

# 6. Central domain object: ChangeEvent

Implement a normalized `ChangeEvent` domain object.

Example:

``` json
{
  "id": "chg_123",
  "symbol": "TCS",
  "detected_at": "2026-09-07T10:15:00+05:30",
  "change_type": "COMPANY_SPECIFIC",
  "severity": "HIGH",
  "attention_score": 87,
  "since": "2026-09-06T15:30:00+05:30",
  "metrics": {
    "price_change_pct": -4.2,
    "relative_to_nifty_pct": -4.7,
    "volume_multiple": 2.8
  },
  "evidence": [
    "Price fell 4.2%",
    "Volume is 2.8x recent average",
    "NIFTY is up 0.3%",
    "2 company-related news events detected"
  ],
  "primary_reason": "COMPANY_EVENT",
  "status": "NEW"
}
```

The frontend, copilot, and notification-like UI should consume
normalized change events instead of independently calculating
importance.

------------------------------------------------------------------------

# 7. Meaningful-change algorithm

Do NOT define meaningful change as a fixed price threshold such as
"anything above 2%".

Use a weighted model based on:

1.  Absolute movement / abnormality
2.  Relative movement versus benchmark
3.  Volume anomaly
4.  News/event significance
5.  User relevance

Recommended base score:

``` text
Market movement / abnormality    25
Relative movement                20
Volume anomaly                   15
News/event significance          25
User relevance                   15
------------------------------------
TOTAL                            100
```

Important: user relevance must influence prioritization but must NOT
turn an objectively insignificant event into a high-severity event.

Use a base significance plus a bounded user-priority adjustment rather
than naive multiplication.

Example:

``` text
Base significance = 42
User adjustment   = +8
Final attention   = 50
```

but:

``` text
Base significance = 5
User adjustment   = +8
Final attention   = 13
```

------------------------------------------------------------------------

# 8. Abnormal price movement

Do not use only absolute percentage change.

Estimate expected movement using historical data.

Example conceptual metric:

``` text
normalized_move = abs(return) / expected_daily_move
```

Expected movement can initially be derived from rolling historical
volatility or ATR.

Use a lightweight statistical baseline. Do not train a custom ML model
for the initial version.

The `stock-indicators` Python package may be used for technical
calculations such as ATR, standard deviation, historical volatility,
RSI, MACD, etc., provided the implementation remains simple and
defensible.

------------------------------------------------------------------------

# 9. Relative movement

Compare the stock with:

-   NIFTY or another broad benchmark
-   relevant sector benchmark where available

Examples:

``` text
TCS      -4.2%
NIFTY    +0.2%
IT       -0.8%
```

This should strongly increase company-specific significance.

Contrast:

``` text
TCS      -4.2%
NIFTY    -3.8%
IT       -4.0%
```

This is primarily market/sector-driven and should not receive the same
attention.

------------------------------------------------------------------------

# 10. Volume anomaly

Use:

``` text
volume_multiple =
current_volume / rolling_average_volume
```

Suggested interpretation:

``` text
~1.0x      normal
1.5x       noteworthy
2.0x       significant
3.0x+      highly unusual
```

Use configurable thresholds.

Do not hardcode these throughout the codebase.

------------------------------------------------------------------------

# 11. News/event significance

Normalize news into structured events.

Example:

``` json
{
  "event_id": "evt_982",
  "symbol": "TCS",
  "type": "EARNINGS",
  "headline": "...",
  "published_at": "...",
  "source": "...",
  "entity_confidence": 0.96,
  "event_significance": 0.88
}
```

High-significance examples:

-   earnings
-   major acquisition
-   major corporate announcement
-   regulatory event
-   material legal event
-   major management event

Medium:

-   significant sector development
-   analyst/industry event
-   material product/business announcement

Low:

-   generic market commentary
-   duplicate coverage
-   opinion pieces
-   routine articles

Deduplicate multiple articles about the same underlying event where
possible.

Three articles about one event should not automatically count as three
separate events.

------------------------------------------------------------------------

# 12. Existing news engine

The user's existing latest-news engine may be conceptually reused but
must be integrated through a clean adapter.

Do NOT copy confidential DefinEdge code, secrets, APIs, or proprietary
infrastructure.

Create:

``` text
NewsProvider
    ↓
NewsNormalizer
    ↓
EntityResolver
    ↓
EventClassifier
    ↓
NewsEvent
```

The rest of the application should only consume normalized `NewsEvent`
objects.

The application must remain independent of DefinEdge.

Use public/free news sources or RSS where possible. Do not require a
paid news API.

If no reliable news API is available, the application must still
function using market-only signals.

------------------------------------------------------------------------

# 13. Change categories

Every meaningful change should be classified as one of:

``` text
COMPANY_SPECIFIC
SECTOR_DRIVEN
MARKET_DRIVEN
TECHNICAL
NO_MATERIAL_CHANGE
```

Examples:

### COMPANY_SPECIFIC

Large stock move + weak benchmark movement + company-specific event.

### SECTOR_DRIVEN

Stock movement broadly aligned with sector.

### MARKET_DRIVEN

Stock movement broadly aligned with the market.

### TECHNICAL

No significant news, but abnormal volume/volatility/price behavior.

### NO_MATERIAL_CHANGE

No meaningful signal.

------------------------------------------------------------------------

# 14. User memory model

Do NOT duplicate full market snapshots per user.

Global market observations are shared.

User-specific state is separate.

Use:

``` text
market_observations
  symbol
  timestamp
  price
  volume
  benchmark data
  source
  quality

user_symbol_state
  user_id
  symbol
  first_added_at
  last_viewed_at
  last_acknowledged_at
  interest_score
```

This is essential for scale.

------------------------------------------------------------------------

# 15. Last-viewed semantics

Maintain two timestamps:

## `last_viewed_at`

When the user actually inspected the security.

## `last_acknowledged_at`

When the user explicitly reviewed/acknowledged the important change.

Do not automatically acknowledge an important event just because the
dashboard loaded.

Example:

User opens dashboard but never opens TCS.

TCS should remain unreviewed.

User opens TCS:

``` text
last_viewed_at = now
```

User clicks "Mark as reviewed":

``` text
last_acknowledged_at = now
```

------------------------------------------------------------------------

# 16. Activity logging

Implement a generic activity/event log.

Events:

``` text
WATCHLIST_CREATED
STOCK_ADDED
STOCK_REMOVED
STOCK_VIEWED
STOCK_SEARCHED
CHART_VIEWED
NEWS_VIEWED
CHANGE_VIEWED
CHANGE_ACKNOWLEDGED
CHANGE_DISMISSED
COPILOT_QUERY
```

Example:

``` json
{
  "user_id": "u1",
  "event_type": "STOCK_VIEWED",
  "symbol": "TCS",
  "timestamp": "...",
  "metadata": {
    "source": "watchlist"
  }
}
```

Activity is not only analytics. It feeds user relevance and change
state.

------------------------------------------------------------------------

# 17. Attention lifecycle

Implement:

``` text
NEW
  ↓
IMPORTANT
  ↓
VIEWED
  ↓
ACKNOWLEDGED
  ↓
STALE
```

Do not keep an old event permanently red.

A newly detected event is different from an event already reviewed.

------------------------------------------------------------------------

# 18. Catch Me Up experience

This is the hero feature.

When a user returns:

``` text
Last checked: Sep 6, 4:18 PM

You were away for 17 hours.

3 meaningful changes
2 normal movements
```

Then:

``` text
TCS
-4.2%
Company-specific event
2.8x normal volume

Reliance
+3.7%
Outperformed sector

Zomato
+2.1%
Unusual volume
```

Use the phrase:

**Since you last looked**

rather than only "today" or "last 24 hours".

------------------------------------------------------------------------

# 19. Dashboard

Build a polished dashboard with:

## Header

-   app/product identity
-   market status
-   user/account control
-   last checked time

## Hero section

"While you were away"

-   count of meaningful changes
-   high/medium attention changes
-   Catch Me Up action

## Change feed

Each change card shows:

-   symbol
-   price
-   movement
-   severity
-   primary reason
-   2--4 evidence items
-   reviewed/unreviewed state

## Watchlist

Columns:

-   stock
-   current price
-   change
-   attention
-   last viewed
-   reason

## Copilot

Contextual input:

-   "Why is TCS highlighted?"
-   "What changed in my watchlist?"
-   "Explain Reliance"
-   "Which stock deserves attention?"

Do not make the copilot the first thing the user sees.

------------------------------------------------------------------------

# 20. Stock detail page

A stock page must answer:

1.  What happened?
2.  Is it unusual?
3.  Is it company/sector/market driven?
4.  What evidence supports that?
5.  Has the user reviewed it?

Example:

``` text
TCS

₹3,021
-4.2% since you last looked

Why it matters

- 2.8x recent average volume
- NIFTY +0.2%
- IT sector -0.8%
- 2 relevant company events
- Normal daily movement: ±1.6%
- Observed movement: -4.2%

Primary driver:
Company-specific

[Explain this]
[Mark as reviewed]
```

------------------------------------------------------------------------

# 21. Evidence-first UX

Every attention result must expose its evidence.

Never show:

``` text
Attention: 87
```

without explaining why.

Show:

``` text
HIGH ATTENTION

✓ -4.2% since last check
✓ 2.8x normal volume
✓ Underperforming NIFTY by 4.4%
✓ 2 relevant company events
```

The AI explanation must be grounded in this evidence.

------------------------------------------------------------------------

# 22. Copilot architecture

Groq is the only required LLM provider.

Environment variable:

``` text
GROQ_API_KEY
```

Use a server-side Groq client. Never expose the API key to the frontend.

Recommended configuration:

``` text
GROQ_API_KEY=...
GROQ_MODEL=<configurable>
```

Do not hardcode a model name if it can be configured through an
environment variable.

The copilot receives structured context from the backend.

It must NOT independently search the internet or invent market facts.

Backend flow:

``` text
User question
    ↓
Identify relevant symbol/context
    ↓
Fetch current market context
    ↓
Fetch user's last-seen state
    ↓
Fetch ChangeEvent
    ↓
Fetch relevant news/events
    ↓
Build evidence package
    ↓
Groq
    ↓
Grounded explanation
```

Useful backend tools/functions:

``` text
get_stock_context(symbol)
get_recent_changes(user_id, symbol)
get_relevant_news(symbol, since)
compare_with_benchmark(symbol)
get_user_activity(user_id, symbol)
```

The model should be instructed:

-   use only supplied evidence
-   clearly distinguish facts from interpretation
-   never fabricate prices/news
-   never claim a source was consulted if it wasn't
-   do not give buy/sell instructions
-   say when evidence is insufficient

------------------------------------------------------------------------

# 23. Groq rate-limit resilience

Treat the free LLM tier as constrained.

Do not call the LLM for every stock.

Only use it for:

-   user-requested explanations
-   Catch Me Up narrative generation if useful
-   selected high-attention summaries

The deterministic change engine must work without Groq.

Implement:

-   request timeout
-   retry with exponential backoff for transient failures
-   429 handling
-   graceful fallback
-   bounded prompt size
-   no repeated identical requests where avoidable

If Groq fails:

``` text
The evidence cards still work.
```

The product must remain functional.

------------------------------------------------------------------------

# 24. Market data provider abstraction

Create:

``` python
class MarketDataProvider:
    async def get_quote(self, symbol): ...
    async def get_history(self, symbol, period): ...
    async def get_batch_quotes(self, symbols): ...
```

Implement providers separately.

Potential provider strategy:

1.  Upstox if valid credentials are available
2.  yfinance/public historical data fallback
3.  deterministic demo/mock provider

Do not make the entire product depend on Upstox.

Upstox authentication is OAuth-based and may require user/application
credentials. Treat it as optional.

No DefinEdge APIs or credentials may be used.

------------------------------------------------------------------------

# 25. Demo provider

Build a deterministic demo mode.

This is mandatory.

Demo mode should allow a controlled sequence:

``` text
previous state
     ↓
simulated market update
     ↓
change engine
     ↓
Catch Me Up
```

Seed a demo user/watchlist with several securities and known events.

Recommended demo symbols can include:

``` text
TCS
RELIANCE
HDFCBANK
INFY
ZOMATO
```

Use realistic but clearly demo/test data if necessary.

Never present synthetic data as real live data.

Label demo mode internally and ensure it can be disabled.

------------------------------------------------------------------------

# 26. Stale data

Every observation must include:

``` text
observed_at
received_at
source
source_timestamp
quality
```

Calculate age:

``` text
data_age = now - observed_at
```

UI states:

``` text
Live / Updated recently
Delayed / Updated X minutes ago
Stale / Last known X
Unavailable
```

Never silently label stale data as live.

------------------------------------------------------------------------

# 27. Conflicting data

If multiple providers disagree:

Store both observations.

Do not blindly average.

Use a configurable tolerance.

If conflict exceeds tolerance:

``` text
DATA_CONFLICT
```

The UI should show that the value is under verification.

Do not produce strong causal conclusions from conflicting data.

Prefer:

1.  fresher observation
2.  higher-quality provider
3.  exchange-direct source where available

Make provider priority configurable.

------------------------------------------------------------------------

# 28. Market session awareness

The application must understand market open/close states.

Do not treat overnight/weekend periods as continuous trading.

Use market-session-aware comparisons.

Example:

``` text
Friday close → Monday open
```

should be described as the period across closed sessions, not as
continuous trading.

After market close, show:

``` text
Market closed
Latest completed session: ...
```

Do not overengineer exchange calendars. Implement the common
Indian-market schedule needed for the demo and keep the market-calendar
module replaceable.

------------------------------------------------------------------------

# 29. Scaling architecture

At larger scale:

BAD:

``` text
1000 users
×
their watchlist symbols
×
external API requests
```

GOOD:

``` text
provider
   ↓
shared symbol-level market observations
   ↓
cache/database
   ↓
many users
```

Global data:

``` text
market_observations
news_events
```

User-specific:

``` text
user_symbol_state
activity_events
change_events
acknowledgements
```

Use batched quote requests.

Cache shared market data.

Refresh popular/in-demand symbols more frequently.

Do not fetch the same market symbol separately for every user.

------------------------------------------------------------------------

# 30. Database schema

Use PostgreSQL.

Recommended tables:

``` text
users
watchlists
watchlist_items

market_observations

news_events

user_symbol_state
activity_events

change_events
change_evidence
```

Suggested structure:

## users

``` text
id
email
display_name
created_at
last_active_at
```

## watchlists

``` text
id
user_id
name
created_at
updated_at
```

## watchlist_items

``` text
id
watchlist_id
symbol
display_name
added_at
sort_order
```

## market_observations

``` text
id
symbol
timestamp
price
open
high
low
close
volume
benchmark_return
sector_return
source
source_timestamp
quality
created_at
```

## news_events

``` text
id
symbol
event_type
headline
source
source_url
published_at
relevance
significance
dedupe_key
created_at
```

## user_symbol_state

``` text
user_id
symbol
first_added_at
last_viewed_at
last_acknowledged_at
interest_score
```

## activity_events

``` text
id
user_id
event_type
symbol
metadata_json
created_at
```

## change_events

``` text
id
user_id
symbol
detected_at
since
change_type
severity
attention_score
primary_reason
status
created_at
```

## change_evidence

``` text
id
change_event_id
evidence_type
label
value
source_ref
metadata_json
created_at
```

Use indexes for:

``` text
market_observations(symbol, timestamp)
news_events(symbol, published_at)
user_symbol_state(user_id, symbol)
activity_events(user_id, created_at)
change_events(user_id, detected_at)
change_events(user_id, status)
watchlist_items(watchlist_id, symbol)
```

Add uniqueness constraints where appropriate.

------------------------------------------------------------------------

# 31. Authentication

Use a simple secure authentication implementation.

Options:

-   Supabase Auth
-   application-managed JWT/session

Prefer the simplest reliable option.

The important requirement is:

``` text
same account
     ↓
same user_id
     ↓
same watchlist
     ↓
same activity
     ↓
same last-seen state
```

across devices.

Do not use browser localStorage as the authoritative persistence layer.

Local storage can be used for UI preferences only.

------------------------------------------------------------------------

# 32. Recommended zero-cost deployment architecture

Preferred:

``` text
Frontend
  ↓
Vercel Hobby / equivalent free static-capable deployment

Backend
  ↓
Render free Web Service

Database
  ↓
Supabase Free PostgreSQL
```

Supabase's current free plan provides PostgreSQL, 500 MB database size,
5 GB egress, and a limited number of active free projects; free projects
pause after inactivity.

Render's free web service can host FastAPI/Python, but it spins down
after 15 minutes without inbound traffic and has ephemeral local
storage. Therefore **do not use local SQLite or local files as
authoritative production data**.

Use Supabase PostgreSQL for persistence.

The backend must listen on:

``` text
0.0.0.0:$PORT
```

for Render deployment.

Do not use Render free Postgres as the primary database for this project
because its current free database has a 30-day expiration. Use Supabase
PostgreSQL instead.

------------------------------------------------------------------------

# 33. Required environment variables

At minimum:

``` text
GROQ_API_KEY=
DATABASE_URL=
```

For frontend deployment:

``` text
NEXT_PUBLIC_API_URL=
```

Potential optional market provider:

``` text
UPSTOX_CLIENT_ID=
UPSTOX_CLIENT_SECRET=
UPSTOX_REDIRECT_URI=
UPSTOX_ACCESS_TOKEN=
```

Only require these if the Upstox provider is enabled.

Optional:

``` text
GROQ_MODEL=
APP_ENV=
CORS_ORIGINS=
DEMO_MODE=
LOG_LEVEL=
```

Do not require unnecessary API keys.

News should have a no-key fallback wherever feasible.

Never commit `.env`.

Create:

``` text
.env.example
```

with placeholders only.

------------------------------------------------------------------------

# 34. Secrets policy

NEVER:

-   commit `.env`
-   print API keys in logs
-   expose Groq keys to the frontend
-   put credentials in source code
-   use DefinEdge credentials
-   use proprietary DefinEdge APIs
-   copy confidential DefinEdge code

Add `.env` to `.gitignore`.

Search the repository before every major commit for accidental secrets.

------------------------------------------------------------------------

# 35. Frontend requirements

Use:

-   Next.js
-   TypeScript
-   Tailwind
-   accessible components
-   responsive layout
-   clean financial-product visual language
-   desktop-first but mobile usable

Do not create an overdecorated "AI dashboard".

Prioritize:

-   hierarchy
-   readability
-   evidence
-   state
-   change
-   attention

Use consistent severity states:

``` text
HIGH
MEDIUM
NORMAL
REVIEWED
STALE
```

Do not rely on color alone; include text/icons.

------------------------------------------------------------------------

# 36. Required screens

## Screen 1 --- Login / onboarding

-   sign in
-   create account
-   initial watchlist setup

## Screen 2 --- Main dashboard

-   market status
-   last checked
-   While You Were Away
-   meaningful changes
-   watchlist
-   Catch Me Up
-   copilot

## Screen 3 --- Stock detail

-   price
-   change
-   chart
-   since-last-look comparison
-   benchmark comparison
-   evidence
-   news/events
-   activity timeline
-   review state
-   copilot

## Screen 4 --- Watchlist management

-   create watchlist
-   rename
-   add stock
-   remove stock
-   reorder
-   search

## Screen 5 --- Change history

-   reviewed
-   unreviewed
-   stale
-   filters by severity/type

## Screen 6 --- Copilot panel

-   contextual questions
-   grounded responses
-   loading/error state

------------------------------------------------------------------------

# 37. API contract

Implement clean REST endpoints.

Suggested:

``` text
POST   /api/auth/register
POST   /api/auth/login
GET    /api/me

GET    /api/watchlists
POST   /api/watchlists
PATCH  /api/watchlists/{id}
DELETE /api/watchlists/{id}

POST   /api/watchlists/{id}/items
DELETE /api/watchlists/{id}/items/{symbol}

GET    /api/market/quote/{symbol}
GET    /api/market/history/{symbol}

GET    /api/dashboard
GET    /api/changes
GET    /api/changes/{id}
POST   /api/changes/{id}/acknowledge
POST   /api/changes/{id}/dismiss

GET    /api/stocks/{symbol}
GET    /api/stocks/{symbol}/activity

POST   /api/copilot/chat

GET    /api/health
GET    /api/health/providers
```

The exact endpoint structure may be adjusted if a better coherent design
emerges, but maintain clear separation.

Use Pydantic schemas.

Return consistent error structures.

------------------------------------------------------------------------

# 38. Health checks

Implement:

``` text
GET /api/health
```

and:

``` text
GET /api/health/providers
```

Provider health should show:

``` text
market provider
database
news provider
Groq
```

without exposing secrets.

This is useful during deployment and debugging.

------------------------------------------------------------------------

# 39. Error handling

Backend:

-   structured exceptions
-   proper HTTP status codes
-   validation
-   provider timeouts
-   retry where appropriate
-   graceful fallbacks

Frontend:

-   loading skeletons
-   empty states
-   error states
-   stale-state messaging
-   retry actions

Do not show raw stack traces to users.

------------------------------------------------------------------------

# 40. Caching

Recommended conceptual TTLs:

``` text
live quote: short
news: several minutes
fundamentals: hours/day
historical data: long-lived
```

Do not overcomplicate caching before correctness.

If Redis is unavailable, the application should still work with
PostgreSQL/application memory where reasonable.

------------------------------------------------------------------------

# 41. Background jobs

Implement lightweight background refresh mechanisms.

Do not require a paid scheduler.

Options:

-   FastAPI lifespan/background tasks
-   periodic async loop
-   Render-compatible scheduled approach only if available
-   on-demand refresh with cache

The core application must not require a continuously running paid
worker.

Because free Render services can sleep, design the system so that
correctness does not depend on a continuously running process.

When a user requests data:

``` text
check cache freshness
    ↓
refresh if needed
    ↓
persist
    ↓
return
```

------------------------------------------------------------------------

# 42. Demo mode architecture

Provide:

``` text
DEMO_MODE=true
```

when needed.

Demo mode should:

-   use deterministic data
-   not call external market providers unless explicitly enabled
-   not require market credentials
-   still exercise the real change engine
-   still exercise persistence
-   still exercise UI
-   optionally exercise Groq for explanation

This lets the entire core product be demonstrated even if an external
market provider is unavailable.

------------------------------------------------------------------------

# 43. Tests

Minimum test coverage:

## Unit tests

-   percentage calculations
-   normalized movement
-   volume anomaly
-   benchmark comparison
-   attention score
-   change classification
-   stale data detection
-   conflict detection
-   user relevance
-   event deduplication

## Integration tests

-   create watchlist
-   add/remove stock
-   persist state
-   generate change event
-   acknowledge event
-   retrieve dashboard
-   copilot context assembly

## E2E tests

At minimum:

``` text
create account
→ create watchlist
→ add stock
→ view stock
→ simulate later return
→ see meaningful change
→ open change
→ acknowledge
```

------------------------------------------------------------------------

# 44. Acceptance criteria

The implementation is not complete until all are true:

### Watchlist

-   [ ] User can create watchlist
-   [ ] User can rename/delete watchlist
-   [ ] User can add/remove symbols
-   [ ] Watchlist persists across refresh/device

### Market

-   [ ] Current quote displayed
-   [ ] Historical chart/data displayed
-   [ ] Timestamp displayed
-   [ ] Source/quality state handled

### Time intelligence

-   [ ] Last viewed state persists
-   [ ] Changes calculated relative to last user state
-   [ ] Meaningful changes ranked
-   [ ] Evidence displayed
-   [ ] Reviewed/unreviewed state persists

### News/events

-   [ ] News can be attached to symbols
-   [ ] Duplicate events handled reasonably
-   [ ] News failure does not break core product

### AI

-   [ ] Groq integration works
-   [ ] API key stays server-side
-   [ ] Responses are grounded
-   [ ] AI failure does not break core product

### Resilience

-   [ ] Stale data shown explicitly
-   [ ] Provider failures handled
-   [ ] Demo mode works
-   [ ] No hard dependency on one external provider

### Deployment

-   [ ] Frontend deployed
-   [ ] Backend deployed
-   [ ] PostgreSQL deployed
-   [ ] Environment variables documented
-   [ ] HTTPS available
-   [ ] Production build succeeds
-   [ ] Health endpoint works
-   [ ] Public URL tested

------------------------------------------------------------------------

# 45. Git discipline

Claude Code must work directly in the connected repository and current
project directory.

Rules:

1.  Inspect repository before changing anything.
2.  Do not delete existing user work blindly.
3.  Preserve useful existing code where appropriate.
4.  Never commit `.env`.
5.  Never commit secrets.
6.  Commit frequently.
7.  Use descriptive commits.
8.  Push after meaningful milestones.
9.  Before pushing, run tests/build/lint appropriate to the project.
10. If a push fails, diagnose and retry safely.
11. Do not rewrite history unless absolutely necessary.
12. Keep the repository in a runnable state after each major milestone.

Suggested commit sequence:

``` text
chore: establish application architecture
feat: add authentication and persistence
feat: add watchlist management
feat: add market data provider abstraction
feat: add market snapshots and historical data
feat: implement meaningful change engine
feat: add attention ranking and evidence
feat: add news event normalization
feat: add catch-up dashboard
feat: add stock detail and activity timeline
feat: add grounded Groq copilot
feat: add demo mode and fallback providers
test: add change engine and API coverage
fix: harden stale and conflicting data handling
chore: prepare production deployment
docs: add setup and deployment instructions
```

Commit more frequently if the changes are large.

Push to the connected remote after meaningful stable milestones.

------------------------------------------------------------------------

# 46. Long-session instructions for Claude Code

This is an overnight implementation session.

Do not rush.

Do not stop after producing a scaffold.

Do not stop after making the UI look good.

Do not stop after the backend works locally.

The definition of done is:

``` text
IMPLEMENT
→ TEST
→ INTEGRATE
→ POLISH
→ DOCUMENT
→ COMMIT
→ PUSH
→ DEPLOY
→ VERIFY PUBLIC DEPLOYMENT
→ FINAL HANDOFF
```

At every major phase:

1.  inspect current state
2.  implement
3.  run tests
4.  fix failures
5.  inspect the actual result
6.  commit
7.  push
8.  continue

Do not ask the user unnecessary questions during the overnight run.

If a nonessential provider credential is unavailable, implement a
graceful fallback and continue.

Only stop for a credential if the credential is genuinely required for
deployment or functionality and there is no viable free fallback.

------------------------------------------------------------------------

# 47. Development phases

## Phase 0 --- Repository reconnaissance

-   inspect repository
-   inspect existing application
-   inspect package managers
-   inspect existing frontend/backend
-   inspect git status/remotes
-   inspect existing environment conventions
-   identify reusable non-confidential code
-   do not delete anything prematurely

Commit only if appropriate.

## Phase 1 --- Foundation

-   establish frontend/backend structure
-   configure TypeScript/Python
-   database connection
-   migrations
-   authentication
-   environment configuration
-   health checks
-   linting/testing

Commit and push.

## Phase 2 --- Watchlist

-   watchlists
-   items
-   search
-   add/remove
-   persistence

Commit and push.

## Phase 3 --- Market layer

-   provider interface
-   primary provider
-   fallback provider
-   market observations
-   caching
-   timestamps
-   stale/conflict handling

Commit and push.

## Phase 4 --- Change engine

-   snapshots
-   last viewed semantics
-   abnormality calculation
-   benchmark comparison
-   volume anomaly
-   classification
-   attention scoring
-   evidence

This is the most important backend phase.

Commit and push.

## Phase 5 --- News/event layer

-   normalize news
-   entity mapping
-   event classification
-   deduplication
-   connect to change engine

Commit and push.

## Phase 6 --- Main UX

-   dashboard
-   While You Were Away
-   Catch Me Up
-   watchlist
-   change cards
-   market status

Commit and push.

## Phase 7 --- Stock detail

-   detail page
-   chart
-   evidence
-   news
-   activity
-   acknowledgement
-   state transitions

Commit and push.

## Phase 8 --- Groq Copilot

-   server-side Groq client
-   context builder
-   grounded prompt
-   error handling
-   rate limiting
-   fallback

Commit and push.

## Phase 9 --- Demo mode

-   deterministic data
-   demo user
-   controlled state transitions
-   reliable Catch Me Up flow

Commit and push.

## Phase 10 --- Quality

-   unit tests
-   integration tests
-   E2E test
-   responsive UI
-   accessibility
-   error states
-   loading states
-   empty states
-   performance pass

Commit and push.

## Phase 11 --- Deployment

-   production build
-   deploy database
-   deploy backend
-   deploy frontend
-   configure environment variables
-   verify CORS
-   verify authentication
-   verify database
-   verify Groq
-   verify market provider/fallback
-   verify public URLs

Commit and push deployment documentation.

## Phase 12 --- Final verification

Use the actual public deployment.

Test:

``` text
signup/login
→ create watchlist
→ add stocks
→ inspect stock
→ leave
→ simulate/observe changed data
→ return
→ Catch Me Up
→ inspect evidence
→ ask Copilot
→ acknowledge
→ refresh
→ verify state persists
```

Do not declare deployment complete until this works against the public
deployment.

------------------------------------------------------------------------

# 48. Final documentation

Create/update:

``` text
README.md
ARCHITECTURE.md
DEPLOYMENT.md
.env.example
```

README must explain:

-   product thesis
-   key features
-   architecture
-   setup
-   demo mode
-   environment variables
-   testing
-   deployment
-   design decisions
-   meaningful-change algorithm
-   data-source limitations

DEPLOYMENT.md must contain exact steps for:

-   database setup
-   backend deployment
-   frontend deployment
-   environment variables
-   migrations
-   health checks
-   common failures

------------------------------------------------------------------------

# 49. Final README product explanation

The README should prominently communicate:

> Traditional watchlists show users what the market looks like now. This
> system remembers what the user has already seen and identifies what
> has meaningfully changed since then.

Explain that meaningful change combines:

-   abnormal movement
-   benchmark-relative movement
-   volume anomalies
-   relevant events
-   user relevance

Explain that AI is an explanation layer over structured evidence.

------------------------------------------------------------------------

# 50. Security checklist

Before final push:

``` text
grep/search for:
GROQ_API_KEY
UPSTOX_CLIENT_SECRET
password=
secret=
token=
Authorization:
Bearer
```

Inspect:

-   git diff
-   git status
-   tracked files
-   `.gitignore`

Make sure `.env` is untracked and ignored.

Never include actual secret values in README, docs, tests, screenshots,
seed data, or commits.

------------------------------------------------------------------------

# 51. Performance checklist

Avoid:

-   N+1 database queries
-   one market API request per watchlist item when batching is possible
-   LLM request per stock
-   repeated news fetches
-   expensive calculations on every page render

Prefer:

-   batch market requests
-   shared market observations
-   cached news
-   precomputed change events
-   indexed queries
-   bounded LLM context
-   lazy loading for detailed content

------------------------------------------------------------------------

# 52. UX quality bar

The UI should feel like a serious financial product.

Avoid:

-   excessive gradients
-   generic AI robot imagery
-   meaningless animations
-   giant "AI" labels
-   cluttered dashboards
-   dozens of metrics
-   unexplained scores

Prioritize:

-   whitespace
-   hierarchy
-   strong typography
-   clear market state
-   obvious change state
-   evidence
-   timestamps
-   review state

The most important visual element is:

**What changed?**

------------------------------------------------------------------------

# 53. What not to build

Explicitly avoid unless required by an unforeseen constraint:

-   automated trading
-   buy/sell recommendations
-   portfolio optimization
-   social trading
-   20+ indicators
-   complex ML training
-   vector database/RAG infrastructure
-   Kafka
-   Kubernetes
-   microservices
-   paid APIs
-   proprietary DefinEdge integrations

Do not optimize for architecture complexity.

Optimize for product clarity.

------------------------------------------------------------------------

# 54. Final demo narrative

The demo should tell this story:

1.  User creates a watchlist.
2.  User views TCS and Reliance.
3.  User leaves.
4.  Market/events change.
5.  User returns.
6.  App says:

> **You were away for 17 hours. 3 things changed materially.**

7.  TCS is highlighted.
8.  Evidence explains why.
9.  User asks:

> "Why is TCS highlighted?"

10. Groq explains the evidence.
11. User marks it reviewed.
12. Refresh.
13. The reviewed state persists.
14. Login from another device/browser.
15. Same state appears.

The product story ends with:

> **It doesn't just remember your stocks. It remembers where you left
> off.**

------------------------------------------------------------------------

# 55. Definition of done

Do not stop at "the app runs."

The project is done only when:

``` text
[✓] Product thesis is clear
[✓] Watchlist works
[✓] Persistence works
[✓] Market data works
[✓] Meaningful-change engine works
[✓] Evidence works
[✓] News/events work or gracefully degrade
[✓] User activity works
[✓] Review state works
[✓] Groq copilot works
[✓] Demo mode works
[✓] Tests pass
[✓] Production builds pass
[✓] Frontend deployed
[✓] Backend deployed
[✓] Database deployed
[✓] Environment configured
[✓] Public URL tested
[✓] README complete
[✓] Deployment guide complete
[✓] No secrets committed
[✓] Git commits pushed
```

The final response to the user should contain:

1.  Git branch used
2.  Latest commit hash
3.  Frontend public URL
4.  Backend public URL
5.  Health endpoint
6.  Database/deployment status
7.  Test status
8.  Known limitations
9.  Required secrets that remain local
10. Exact steps for any remaining manual action
