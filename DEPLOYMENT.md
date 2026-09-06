# Deployment

Target: a zero-cost stack.

| Layer | Platform | Free tier |
|---|---|---|
| Database | MongoDB Atlas | M0 cluster, 512 MB |
| Backend | Render | Web service, sleeps after ~15 min idle |
| Frontend | Vercel | Hobby |

Total time: about 20 minutes. Nothing below requires a paid plan or a credit card.

---

## 1. MongoDB Atlas

1. Create a free account at <https://www.mongodb.com/cloud/atlas/register>.
2. **Create a cluster** → choose **M0 (Free)**. Pick a region near your backend
   (Render's `singapore` pairs well with Atlas `ap-south-1` / Mumbai).
3. **Database Access** → *Add New Database User*.
   - Authentication: Password.
   - Give it a username and a generated password. **Copy the password now** — Atlas will not
     show it again.
   - Role: *Read and write to any database*.
4. **Network Access** → *Add IP Address* → **Allow access from anywhere** (`0.0.0.0/0`).

   Render's free tier does not offer static outbound IPs, so an allowlist is not possible.
   The database is still protected by username and password over TLS. If you later move to a
   paid Render plan, restrict this to its static IPs.
5. **Connect** → *Drivers* → copy the connection string. It looks like:

   ```
   mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```

   Replace `<username>` and `<password>` with the values from step 3. If the password
   contains `@ : / ? # [ ] %`, percent-encode it (`@` → `%40`, `#` → `%23`).

Keep this string for step 2. **Never commit it.**

---

## 2. Backend on Render

### Option A — Blueprint (recommended)

The repository contains [`render.yaml`](render.yaml), which declares the service, health
check, region and every environment variable.

1. Go to <https://dashboard.render.com> → **New** → **Blueprint**.
2. Connect your GitHub account and select **`kananmittal/market-watchlist`**.
3. Render reads `render.yaml` and prompts for the secrets it marks `sync: false`:

   | Variable | Value |
   |---|---|
   | `MONGODB_URI` | The Atlas string from step 1 |
   | `GROQ_API_KEY` | From <https://console.groq.com/keys> |
   | `CORS_ORIGINS` | Leave blank for now; set in step 4 |

   `JWT_SECRET` is generated automatically by Render.
4. **Apply**. The first build takes 3–6 minutes (pandas and numpy are compiled wheels).

### Option B — Manual web service

If you prefer not to use a Blueprint:

- **New** → **Web Service** → connect the repo.
- Root directory: `backend`
- Runtime: Python 3
- Build command: `pip install --upgrade pip && pip install .`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
- Health check path: `/api/health`
- Add environment variables:

  ```
  PYTHON_VERSION=3.12.7
  APP_ENV=production
  LOG_LEVEL=INFO
  DEMO_MODE=false
  MONGODB_DB=market_watchlist
  MARKET_PROVIDER_ORDER=yfinance,jugaad,demo
  GROQ_MODEL=openai/gpt-oss-120b
  MONGODB_URI=<your Atlas string>
  GROQ_API_KEY=<your Groq key>
  JWT_SECRET=<openssl rand -hex 32>
  CORS_ORIGINS=<your Vercel URL, added in step 4>
  ```

> **The service must bind `0.0.0.0` and Render's `$PORT`.** Binding `127.0.0.1` or a fixed
> port makes the health check fail and the deploy hang.

### Verify the backend

```bash
curl https://<your-service>.onrender.com/api/health
# {"status":"ok","app_env":"production","demo_mode":false,"version":"0.1.0"}

curl https://<your-service>.onrender.com/api/health/providers
# reports database, market providers, news and llm — and contains no credentials
```

The first call after idling takes 30–60 seconds while the service wakes. That is expected.

---

## 3. Frontend on Vercel

1. Go to <https://vercel.com/new> and import **`kananmittal/market-watchlist`**.
2. **Root Directory: `frontend`** — this is the one setting people miss; without it the build
   fails because Vercel looks for `package.json` at the repository root.
3. Framework preset: **Next.js** (detected automatically).
4. Environment Variables → add:

   ```
   NEXT_PUBLIC_API_URL = https://<your-service>.onrender.com
   ```

   No trailing slash. This is a build-time public value and is safe to expose; it is only the
   backend's address. **Never put `GROQ_API_KEY` here** — it would be shipped to the browser.
5. **Deploy.**

---

## 4. Connect the two (do not skip)

Go back to Render → your service → **Environment** and set:

```
CORS_ORIGINS = https://<your-project>.vercel.app
```

Save. Render redeploys automatically.

The backend also permits any `https://*.vercel.app` origin via a regex, so preview deployments
work without further configuration.

---

## 5. Verify the public deployment

Run this against the real URLs, not localhost.

```bash
API=https://<your-service>.onrender.com
WEB=https://<your-project>.vercel.app

# 1. health
curl -s $API/api/health | jq

# 2. register
TOKEN=$(curl -s -X POST $API/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-strong-password","display_name":"You"}' \
  | jq -r .access_token)

# 3. watchlist
WID=$(curl -s -X POST $API/api/watchlists -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"name":"Core"}' | jq -r .id)
for S in TCS RELIANCE INFY; do
  curl -s -X POST $API/api/watchlists/$WID/items -H "Authorization: Bearer $TOKEN" \
    -H 'Content-Type: application/json' -d "{\"symbol\":\"$S\"}" > /dev/null
done

# 4. the core loop
curl -s -X POST $API/api/demo/reset -H "Authorization: Bearer $TOKEN" | jq
curl -s "$API/api/dashboard" -H "Authorization: Bearer $TOKEN" | jq '.catch_up.headline'
curl -s "$API/api/stocks/TCS" -H "Authorization: Bearer $TOKEN" | jq '{last_viewed_at, last_acknowledged_at}'
curl -s -X POST "$API/api/demo/step?step=1" -H "Authorization: Bearer $TOKEN" > /dev/null
curl -s "$API/api/dashboard" -H "Authorization: Bearer $TOKEN" \
  | jq '{headline:.catch_up.headline, changes:[.meaningful_changes[]|{symbol,severity,status}]}'
```

Then in a browser, walk the same path on `$WEB`: sign in → dashboard → open a stock → leave →
advance the demo → return → **Catch Me Up** → inspect evidence → ask the copilot → mark as
reviewed → refresh and confirm the reviewed state persists → sign in from a private window and
confirm the same state appears.

---

## Common failures

| Symptom | Cause | Fix |
|---|---|---|
| Render deploy hangs, health check never passes | Server bound to `127.0.0.1` or a fixed port | Use `--host 0.0.0.0 --port $PORT` |
| `ServerSelectionTimeoutError` in logs | Atlas network access not open | Add `0.0.0.0/0` under Network Access |
| `Authentication failed` against Atlas | Special characters in the password | Percent-encode them (`@` → `%40`) |
| Browser console: blocked by CORS | `CORS_ORIGINS` not set to the Vercel URL | Set it on Render (step 4), exactly, no trailing slash |
| Vercel build: `No package.json found` | Root directory not set | Set Root Directory to `frontend` |
| Frontend loads but every call fails | `NEXT_PUBLIC_API_URL` wrong or has a trailing slash | Fix it and **redeploy** — it is baked in at build time |
| First request takes ~60s | Render free tier cold start | Expected. The UI reports the server is waking |
| Copilot returns evidence instead of prose | Groq key missing, rate-limited, or the model is unavailable on your account | Check `/api/health/providers`; the product is designed to keep working this way |
| `model_not_found` from Groq | `GROQ_MODEL` is not enabled for your account | List available models at <https://console.groq.com/docs/models> and set `GROQ_MODEL` |

---

## Operational notes

- **Cold starts.** Render free services sleep after ~15 minutes idle. Correctness never
  depends on a running process: when the cache is cold a request refreshes and persists on
  demand. Optionally keep it warm with an external uptime pinger on `/api/health`.
- **Ephemeral disk.** Nothing is written to local disk. All state is in Atlas. Never switch to
  SQLite here.
- **Atlas free tier pauses** after extended inactivity; open the Atlas dashboard to resume.
- **Index creation is idempotent** and runs at every boot, so no migration step is needed.
- **Rotating a secret:** update it in the Render dashboard and redeploy. Rotating `JWT_SECRET`
  signs every existing session out, which is the intended behaviour.
- **Retention.** Market observations and news expire after 30 days via TTL indexes, activity
  after 180 days. This keeps the M0 tier's 512 MB comfortable.

---

## Secrets checklist

- [ ] `.env` is gitignored and was never committed
- [ ] `.env.example` contains placeholders only
- [ ] `GROQ_API_KEY` is set only on Render, never in Vercel or any `NEXT_PUBLIC_*` variable
- [ ] `JWT_SECRET` is 32+ random characters, not the development default
- [ ] Atlas user has a generated password, not a reused one
- [ ] `/api/health/providers` output contains no credentials (there is a test asserting this)
