# NEYRA production deployment (Vercel + Railway)

This repo is wired for:

- **Frontend:** Vercel (Next.js app in [`frontend/`](frontend/)).
- **Backend:** Railway (Docker image [`backend/Dockerfile.prod`](backend/Dockerfile.prod)).
- **Background worker:** Railway (same image, override start command).
- **Telegram admin bot:** Railway long‑running process (same image, override start command).

Do **not** commit `.env`, tokens, API keys, or database URLs. Examples live in [`backend/.env.example`](backend/.env.example) and [`frontend/.env.production.example`](frontend/.env.production.example).

---

## 1. Railway — PostgreSQL

1. In Railway → **New** → **Database** → **PostgreSQL**.
2. Copy **`DATABASE_URL`** from the Postgres service variables.
3. Attach the DB to your API service (Railway prompts to add `DATABASE_URL`).

---

## 2. Railway — Redis (recommended if you use queues / caches)

If the app relies on **`REDIS_URL`**, provision **Redis** on Railway and copy `REDIS_URL` into the **API** service (and optionally the **worker** service).

---

## 3. Railway — Web API (`backend`)

1. **New project** → **Deploy from GitHub** → pick this repo.
2. Service settings:
   - **Root Directory:** `backend`
   - **Dockerfile:** `Dockerfile.prod` (see [`backend/railway.toml`](backend/railway.toml))
   - Railway injects **`PORT`**; [`backend/scripts/start_web_production.sh`](backend/scripts/start_web_production.sh) binds **`0.0.0.0`** and uses **`$PORT`**.
3. Required environment variables (names only):

| Variable | Notes |
|---------|------|
| `ENV` | `production` |
| `DATABASE_URL` | From Postgres |
| `REDIS_URL` | If using Redis |
| `SECRET_KEY` | Strong secret (JWT/signing); min length enforced in prod warning |
| `PUBLIC_BACKEND_URL` | Public HTTPS URL of **this API** (e.g. Railway URL or `https://api.getneyra.app`) |
| `APP_PUBLIC_URL` **or** `FRONTEND_URL` | **`https://getneyra.app`** — browser SPA origin (OAuth redirects, CORS) |
| `CORS_ORIGINS` | **`https://getneyra.app,https://www.getneyra.app`** (extras merged; prod also auto-includes those two) |
| `CORS_ALLOW_VERCEL_PREVIEWS` | Default `true` — allows preview URLs matching `*.vercel.app` |
| `GEMINI_API_KEY` | Gemini (server-side only) |
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | Same values as **Google Cloud OAuth “Client ID”** and **“Client secret”** (not `GOOGLE_CLIENT_*` env names in this repo). |
| `GOOGLE_OAUTH_REDIRECT_URI` | Must be `{PUBLIC_BACKEND_URL}/api/v1/auth/social/google/callback` |
| `ENABLE_GOOGLE_OAUTH` | `true` in prod if using Google |
| `PADDLE_WEBHOOK_SECRET` | Paddle notifications HMAC |

4. Deploy and confirm **`GET https://<your-api>/health/ready`** returns **200**.
5. Your **canonical API URL** becomes the Railway-generated domain or custom domain attached to this service — use that for Vercel `NEXT_PUBLIC_API_BASE_URL` below.

### Start-command reference (`backend/Procfile`)

- **Web:** `sh /app/scripts/start_web_production.sh` 
- **Worker:** `python worker.py`
- **Telegram:** `python scripts/telegram_admin_bot.py`

---

## 4. Railway — Background worker (`worker.py`)

Duplicate the **same** backend Docker service (or create a blank service pointing at the repo with root `backend`):

- **Start command:** `python worker.py`
- **Env:** Same `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, etc. as the API unless you consciously trim unused vars.

---

## 5. Railway — Telegram admin bot worker

Separate service, same Dockerfile / root **`backend`**:

| Variable | Purpose |
|---------|---------|
| `TELEGRAM_BOT_TOKEN` | Botfather token (**secret**) |
| `ADMIN_TELEGRAM_IDS` **or** `TELEGRAM_ADMIN_IDS` | Comma-separated numeric Telegram user IDs |
| `ADMIN_BOT_SERVICE_TOKEN` | Long random secret (must match backend) |
| `BACKEND_BASE_URL` | **`PUBLIC_BACKEND_URL` of API** (`https://...` **no trailing slash**) |
| `ENV` | `production` |

**Start command:** `python scripts/telegram_admin_bot.py`

Ensure `ADMIN_BOT_SERVICE_TOKEN` matches whatever the backend API expects for internal bot routes.

---

## 6. Vercel — Frontend (`frontend`)

Create a **Vercel project** rooted at **`frontend/`** with **Framework Preset:** Next.js (or attach [`frontend/vercel.json`](frontend/vercel.json)).

### Required Production / Preview vars

| Variable | Value |
|---------|-------|
| `NEXT_PUBLIC_API_BASE_URL` | **HTTPS origin of Railway API**, e.g. `https://xxxxx.up.railway.app` or `https://api.getneyra.app` — **no** `/api/v1` |
| `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN` | From Paddle (client-side token) |
| `NEXT_PUBLIC_NEYRA_PREMIUM_PRICE_ID` | Paddle price IDs |
| `NEXT_PUBLIC_NEYRA_PREMIUM_PLUS_PRICE_ID` | Optional tier |

Equivalent legacy name: **`NEXT_PUBLIC_BACKEND_URL`** (same semantics as `NEXT_PUBLIC_API_BASE_URL`; both work).

Preview deployments (`*.vercel.app`) stay allowed by backend CORS when **`CORS_ALLOW_VERCEL_PREVIEWS`** is **`true`** (default).

---

## 7. Google OAuth (current NEYRA web flow)

Production uses **backend** routes under `/api/v1/auth/social/google/...`; the browser uses **GIS** with **`GOOGLE_OAUTH_CLIENT_ID`**.

Configure in **Google Cloud Console** (OAuth 2 Web client):

1. **Authorized JavaScript origins**
   - `https://getneyra.app`
   - `https://www.getneyra.app`
   - `https://<your-deployment>.vercel.app` as needed for QA
2. **Authorized redirect URI** → backend callback
   - `https://YOUR_API_ORIGIN/api/v1/auth/social/google/callback`
3. Backend env **`GOOGLE_OAUTH_REDIRECT_URI`** must match that exact URL.

### Optional Auth.js / NextAuth (not in this repo)

If you add Auth.js later, standard env is:

```
NEXTAUTH_URL=https://getneyra.app
NEXTAUTH_SECRET=<openssl rand -base64 32>
```

Keep Google client secrets server-side (`GOOGLE_*` on backend, not exposed as `NEXT_PUBLIC_*` unless it is intentionally a client ID).

---

## 8. Sanity checks locally

Backend (imports app):

```bash
cd backend
python -c "from app.main import app; print('ok')"
```

Frontend:

```bash
cd frontend
npm run type-check
npm run build
```

---

## 9. What to run next after deploy

**Railway (API)**

- Add custom domain **`api.getneyra.app`** (optional).
- Attach SSL (Railway default).
- Re-point **`PUBLIC_BACKEND_URL`**, Paddle webhooks if needed.

**Railway (Postgres)**

- Enable backups if available.

**Railway (Worker / Telegram)**

- Point **`BACKEND_BASE_URL`** / tokens to prod API secrets.

**Vercel**

- Add env groups for Preview vs Production.
- Add domain **`getneyra.app`** / **`www.getneyra.app`**.
- **`NEXT_PUBLIC_API_BASE_URL`** = public API URL (**HTTPS**, no path).

**Google Cloud**

- Match redirect + JS origins to prod.

**Paddle**

- Webhook URL points to `{PUBLIC_BACKEND_URL}/api/v1/...` (see backend routes for exact path).

---

## 10. Support files

- [`backend/Dockerfile.prod`](backend/Dockerfile.prod) — production image.
- [`backend/scripts/start_web_production.sh`](backend/scripts/start_web_production.sh) — Railway web entry.
- [`backend/Procfile`](backend/Procfile) — process command reference.
- [`backend/railway.toml`](backend/railway.toml) — Railway config when service root is `backend/`.
