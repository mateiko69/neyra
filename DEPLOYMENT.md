# NEYRA production deployment (Vercel + Railway)

This repo is wired for:

- **Frontend:** Vercel (Next.js app in [`frontend/`](frontend/)).
- **Backend:** Railway (Docker image [`backend/Dockerfile.prod`](backend/Dockerfile.prod)).
- **Background worker:** Railway (same image, override start command).
- **Telegram admin bot:** Railway long‑running process (same image, override start command).

Do **not** commit `.env`, tokens, API keys, or database URLs. Examples live in [`backend/.env.example`](backend/.env.example) and [`frontend/.env.production.example`](frontend/.env.production.example).

### Uploads: Railway disk is ephemeral; production photos need S3 / R2

**Railway (and most PaaS) container filesystems are not durable.** The default **local** storage under **`UPLOAD_DIR`** (see [`backend/app/services/storage/local_provider.py`](backend/app/services/storage/local_provider.py)) is fine for **development** only. After a **redeploy or restart**, files that were never written to object storage are **gone**; the database can still point at old **`/uploads/...`** paths. The API does **not** clear those URLs when a file 404s; the Next.js app uses **`SafeImg`** to show a **placeholder** when an image cannot be loaded (so the UI does not show a broken icon while the user re-uploads).

**Production** must use **S3-compatible** object storage (AWS S3, **Cloudflare R2**, MinIO, etc.):

| Variable | Purpose |
|----------|--------|
| `ENV` | `production` (or `prod`) so the API **never** falls back to local disk for user media when S3 is not fully configured. |
| `STORAGE_PROVIDER` | Set to **`s3`** in production to match your intent; the API also requires the S3 fields below. |
| `S3_BUCKET` | Target bucket. |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | API credentials. |
| `S3_PUBLIC_BASE_URL` | **Public** origin for objects (R2 public URL, R2 custom domain, or CloudFront). **No trailing slash.** Browsers use this in returned image URLs. |
| `S3_ENDPOINT_URL` | For **Cloudflare R2**, set the R2 S3 API endpoint (for example `https://<accountid>.r2.cloudflarestorage.com`). Optional for AWS (default endpoint). |
| `S3_REGION` | For R2, **`auto`** is common; for AWS, your bucket region. |

If required S3 variables are **missing in production**, the service logs a **clear warning** and user uploads return **503** with a storage-unavailable error (it does **not** silently write to ephemeral disk). When S3 is configured, upload endpoints return **durable public URLs** under `S3_PUBLIC_BASE_URL`.

**Demo / seed avatars** use static files under [`frontend/public/demo-profiles/`](frontend/public/demo-profiles/) in the monorepo. The same files are **copied into** [`backend/static/demo-profiles/`](backend/static/demo-profiles/) so the **Railway** image (build context `backend/`) still mounts `/demo-profiles/...` from the API. Public URLs look like `/demo-profiles/shared/avatar-01.jpg` (served by the backend, not ephemeral upload disk).

---

## 1. Railway — PostgreSQL (required for the backend API)

The NEYRA **backend API and Alembic migrations require PostgreSQL**. Railway’s web service alone is not sufficient: provision the **PostgreSQL** add-on or service and expose its connection URL to your API.

1. In Railway → **New** → **Database** → **PostgreSQL**.
2. Open the Postgres service → **Variables** → find **`DATABASE_URL`** (Railway sets this automatically; it normally looks like `postgresql://...@...railway.internal:5432/railway` or a pooled URL).
3. **Link/reference** Postgres to your backend service so **`DATABASE_URL`** is present on the API service environment. If `DATABASE_URL` is missing, empty, or malformed, the container will refuse to boot (startup and Alembic print clear messages; values are never logged).
4. Optional: older tools emit `postgres://` — the app accepts that and converts it to `postgresql://` for SQLAlchemy.

Do **not** rely on SQLite in production: with `ENV=production`, SQLite is **not** used unless you deliberately set **`DATABASE_URL`** to a SQLite URL (not recommended).

---

## 2. Railway — Redis (recommended if you use queues / caches)

If the app relies on **`REDIS_URL`**, provision **Redis** on Railway and copy `REDIS_URL` into the **API** service (and optionally the **worker** service).

---

## 3. Railway — Web API (`backend`)

1. **New project** → **Deploy from GitHub** → pick this repo.
2. Service settings:
   - **Root Directory:** `backend`
   - **Dockerfile:** `Dockerfile.prod` (see [`backend/railway.toml`](backend/railway.toml))
   - Railway injects **`PORT`**; [`backend/scripts/start_web_production.sh`](backend/scripts/start_web_production.sh) binds **`0.0.0.0`** and uses **`${PORT:-8000}`**.
   - **PostgreSQL**: add the Railway Postgres service (or compatible provider) and ensure **`DATABASE_URL`** on **this** service points at it (typically by referencing Railway’s Postgres `DATABASE_URL` variable).
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

4. Deploy and confirm **`GET https://<your-api>/health`** returns **200** with `{"status":"ok"}` and **`GET …/health/ready`** returns **200** with `{"status":"ready"}`.
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
