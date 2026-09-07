# Instructions to Run

Everything below has been run end to end on a clean macOS machine. Two terminals, about
five minutes. **No market-data account, no API key and no paid service is required** — the
whole product, including the change engine and the copilot's fallback, runs on deterministic
demo data.

---

## TL;DR — the fastest working path

```bash
# terminal 0 — database (skip if you already have MongoDB running)
brew services start mongodb-community        # or: docker run -d -p 27017:27017 mongo:7

# terminal 1 — backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
DEMO_MODE=true uvicorn app.main:app --reload --port 8000

# terminal 2 — frontend
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Open **http://localhost:3000** and follow [the review walkthrough](#5-the-review-walkthrough)
below. API docs are at http://localhost:8000/docs.

---

## 1. Prerequisites

| Need | Version | Check | If missing |
|---|---|---|---|
| Python | **3.11+** | `python3 --version` | macOS ships 3.9 — `brew install python@3.12` and use `python3.12` |
| Node | **20+** | `node --version` | `brew install node` |
| MongoDB | any 6/7 | `mongod --version` | `brew install mongodb-community`, or use Docker, or a free Atlas cluster |

> macOS gotcha: `python3` is often 3.9, which will fail with
> `requires-python >= 3.11`. Create the venv with an explicit `python3.12`.

---

## 2. Get the code and configure

```bash
git clone https://github.com/kananmittal/market-watchlist.git
cd market-watchlist
```

**In demo mode you can skip `.env` entirely** — every setting has a working default
(MongoDB at `localhost:27017`, a development JWT secret, the copilot degrading to evidence
cards). To use real prices or the AI copilot:

```bash
cp .env.example .env
```

and fill in:

| Variable | Needed for | Where to get it |
|---|---|---|
| `GROQ_API_KEY` | AI copilot prose (the app works without it) | free at https://console.groq.com/keys |
| `MONGODB_URI` | non-local database | Atlas free M0, see [DEPLOYMENT.md](DEPLOYMENT.md) |
| `JWT_SECRET` | production only | `openssl rand -hex 32` |

The backend reads the **repository-root `.env`**, so a single file serves the backend and the
tooling. The full list of variables is documented in [`.env.example`](.env.example).

---

## 3. Start MongoDB

Pick one:

```bash
brew services start mongodb-community            # macOS, persistent
docker run -d -p 27017:27017 --name mw-mongo mongo:7   # Docker
# or set MONGODB_URI to an Atlas SRV string in .env — no local install needed
```

Indexes are created automatically at boot; there is no migration step and no seed script.

---

## 4. Start the servers

### Backend

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
DEMO_MODE=true uvicorn app.main:app --reload --port 8000
```

Confirm it is healthy before moving on:

```bash
curl http://localhost:8000/api/health
# {"status":"ok","app_env":"development","demo_mode":true,"version":"0.1.0"}

curl http://localhost:8000/api/health/providers   # per-dependency detail, no secrets
# {"status":"ok","database":{"ok":true,...},"llm":{"ok":false,"configured":false,
#  "note":"GROQ_API_KEY not set - copilot degrades to evidence cards"},...}
```

`"status":"ok"` with `llm.ok:false` is expected and fine without a Groq key — the copilot
falls back to the deterministic evidence, which is the point of the design.

### Frontend

```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

Or put it in `frontend/.env.local` so you can just run `npm run dev`:

```bash
echo 'NEXT_PUBLIC_API_URL=http://localhost:8000' > frontend/.env.local
```

Open http://localhost:3000.

---

## 5. The review walkthrough

The product is about *time passing*, so a static screenshot cannot show it. This sequence
demonstrates the core loop in about two minutes.

**1 — Create an account.** http://localhost:3000 → *Create account*. Any email; password 8+
characters. No email verification.

**2 — Build a watchlist.** *Watchlists* → name a list → add **TCS, RELIANCE, HDFCBANK, INFY**.
(These four give one high-attention fall, one high-attention rise, one sector-driven move and
one quiet stock.)

**3 — Look at the dashboard.** First visit, so there is no "since" yet — this is the baseline.
The demo banner confirms the prices are synthetic.

**4 — Open TCS, then go back.** Opening a stock is what sets *"last looked"*. Loading the
dashboard deliberately does not.

**5 — Make time pass.** There is no UI control for this on purpose; step the scripted scenario
from the browser console on the app tab (the token is the one the app already stored):

```js
await fetch("http://localhost:8000/api/demo/step?step=1", {
  method: "POST",
  headers: { Authorization: `Bearer ${localStorage.getItem("mw.token")}` },
});
```

or from a terminal, see [the curl script](#6-the-same-walkthrough-in-curl) below.

**6 — Reload the dashboard.** This is the product:

```
You were away moments ago. 3 meaningful changes and 1 normal movement.

TCS       HIGH    63.9   down 4.3% since you last looked - company-specific
RELIANCE  HIGH    57.7   up 4.1% since you last looked - company-specific
HDFCBANK  NORMAL  22.0   down 1.7% since you last looked - moving with its sector
INFY                     (normal movement)
```

**7 — Check the reasoning, which is the part worth reviewing.**
- Expand **Why it matters** — the raw evidence: move size, how many times a normal day it is
  for *that* stock, benchmark and sector comparison, volume multiple.
- **How was this scored?** — the component breakdown, and the proof that personal interest
  ranks but never promotes severity.
- HDFCBANK is `SECTOR_DRIVEN`, not company-specific, because the whole bank index moved with
  it. That attribution is the point.

**8 — Confirm viewing ≠ acknowledging.** *Mark as reviewed* on TCS, then reload. It stays
visible and is now marked reviewed — acknowledging does not reset your comparison window.

**9 — Ask the copilot** (sidebar): *"What changed in TCS?"* With `GROQ_API_KEY` set you get
prose grounded in that evidence; without one you get the evidence itself, clearly labelled.

**10 — Replay from scratch** any time with `POST /api/demo/reset` (see below).

---

## 6. The same walkthrough in curl

Copy-paste; it creates its own account and prints the dashboard.

```bash
API=http://localhost:8000
TOKEN=$(curl -s -X POST $API/api/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"reviewer@example.com","password":"reviewer123","display_name":"Reviewer"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
H="Authorization: Bearer $TOKEN"

WID=$(curl -s -X POST $API/api/watchlists -H "$H" -H 'Content-Type: application/json' \
  -d '{"name":"My List"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')
for S in TCS RELIANCE HDFCBANK INFY; do
  curl -s -o /dev/null -X POST $API/api/watchlists/$WID/items -H "$H" \
    -H 'Content-Type: application/json' -d "{\"symbol\":\"$S\"}"
done

curl -s -X POST $API/api/demo/reset -H "$H"        # clean slate
curl -s -o /dev/null $API/api/dashboard -H "$H"     # baseline visit
for S in TCS RELIANCE HDFCBANK INFY; do             # "I looked at these"
  curl -s -o /dev/null $API/api/stocks/$S -H "$H"
done
curl -s -X POST "$API/api/demo/step?step=1" -H "$H" # the market moves

curl -s $API/api/dashboard -H "$H" | python3 -m json.tool | head -40
```

`reset` exists because synthetic observations accumulate as the scenario is stepped; without
it a second run baselines against the previous step and correctly reports that nothing
changed. It clears only synthetic rows — real observations are never touched.

---

## 7. Running against real market data

```bash
DEMO_MODE=false uvicorn app.main:app --reload --port 8000
```

Prices then come from yfinance (no key needed), enriched by NSE via jugaad-data where it
responds, falling back to demo data if every provider fails. Outside NSE trading hours the UI
says *"At Fri 04 Sep close"* rather than calling normal last-session data stale. Real market
moves are usually small, so the "since you last looked" story is far easier to see in demo
mode — which is why demo mode exists.

---

## 8. Tests

```bash
cd backend
pytest                     # 118 unit + integration tests (~40s)
ruff check app/ tests/     # lint
mypy app/                  # type check
```

Browser end-to-end tests are a separate suite (Playwright's sync API installs its own event
loop, which would stop pytest-asyncio creating one for async tests collected after it). They
need Playwright and both servers on their own ports:

```bash
pip install playwright && playwright install chromium

# terminal 1
DEMO_MODE=true uvicorn app.main:app --port 8899
# terminal 2
cd frontend && NEXT_PUBLIC_API_URL=http://127.0.0.1:8899 npm run dev -- --port 3111
# terminal 3
cd backend && pytest -m e2e     # 3 browser tests
```

Override `E2E_API_URL` / `E2E_WEB_URL` to use different ports. If the servers are not up, the
suite skips rather than fails.

Frontend checks:

```bash
cd frontend
npx tsc --noEmit && npx eslint src && npm run build
```

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `requires-python >= 3.11` on install | venv built with macOS system Python 3.9 | `rm -rf .venv && python3.12 -m venv .venv` |
| `[Errno 48] Address already in use` | port 8000 or 3000 taken | `--port 8001` / `npm run dev -- --port 3001`, and point `NEXT_PUBLIC_API_URL` at the new API port |
| `startup_database_failed` in the logs, health says `degraded` | MongoDB not running or wrong URI | start MongoDB, or fix `MONGODB_URI`. The app deliberately still boots so `/api/health` can report the problem |
| Frontend loads, every request fails | `NEXT_PUBLIC_API_URL` missing or stale | it is inlined at build time — restart `npm run dev` after changing it |
| Copilot replies with evidence, not prose | no `GROQ_API_KEY` | expected fallback; add a key to `.env` and restart the backend |
| Groq 404 / model not found | key has no access to that model | set `GROQ_MODEL` to one your account lists at https://console.groq.com/docs/models |
| Dashboard says nothing changed | second run without a reset, or you never opened a stock | `POST /api/demo/reset`, load the dashboard, open a stock, then step |
| Prices look flat / uninteresting | `DEMO_MODE=false` during a quiet session | use `DEMO_MODE=true` for the walkthrough |

---

## What to look at if you only have five minutes

1. **The evidence panel** on a HIGH change — every number the score is made of.
2. **HDFCBANK classified `SECTOR_DRIVEN`** while TCS is `COMPANY_SPECIFIC` on a similar-sized
   move — attribution, not just detection.
3. **`GET /api/health/providers`** — honest per-dependency state, with no secrets in the output.
4. **`backend/app/services/change_engine.py`** — the scoring, and the bounded user adjustment
   that ranks but cannot promote severity.
