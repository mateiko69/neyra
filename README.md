# NEYRA

This is the largest handoff package in this chat: a serious full-stack starter for an AI-first dating app.

## What's inside
- FastAPI backend
- PostgreSQL + Redis
- Alembic migrations
- JWT auth
- Profiles, swipes, matches, messages
- WebSocket chat
- AI provider abstraction (mock/openai/gemini-ready)
- Local + S3-ready storage abstraction
- Upload endpoint
- Push notifications abstraction
- Payments/subscription skeleton
- Premium feature gating
- Analytics event tracking
- Admin endpoints
- Redis queue + worker starter
- Webhook skeletons
- Next.js frontend
- Expo mobile starter
- Tests
- GitHub Actions CI
- Environment split examples
- Roadmap and integration notes for Cursor/Codex

## Important honesty
This package is **strong starter code**, not a fully audited million-user production deployment.
The live provider integrations are intentionally left as integration points where you will wire in real OpenAI/Gemini, Stripe, S3, Firebase/APNs, and cloud infra.

## Quick start
```bash
cp backend/.env.example backend/.env
cp .env.example .env
cp frontend/.env.example frontend/.env.local
cp mobile/.env.example mobile/.env
docker compose up --build
```

## How to configure Telegram admin bot
- Copy root env file: `cp .env.example .env`
- Set:
  - `TELEGRAM_BOT_TOKEN`: token from @BotFather
  - `ADMIN_TELEGRAM_IDS`: comma-separated Telegram user IDs allowed to use the bot
  - `ENV`: `development` (or `production`)
- The `telegram-bot` service reads these via Docker Compose `${...}` variables.
- The bot validates the token on startup via Telegram `getMe` and exits if invalid (token is masked in logs).

## Dev database safety (important)
- **Safe restart (keeps your Postgres data)**: `docker compose down` then `docker compose up --build`
- **Destructive reset (deletes Postgres volume + all profiles)**: `docker compose down -v`

Never use `-v` unless you *intentionally* want to wipe the dev database.

For convenience (Windows/PowerShell):
- `scripts/dev_restart.ps1`: safe restart (no volume deletion)
- `scripts/dev_reset_db.ps1`: destructive reset (requires typing **RESET NEYRA DB**)

## Services
- Backend (`api`): http://localhost:8000
- Frontend (`neyra-web`): http://localhost:3000
- Swagger docs: http://localhost:8000/docs

## Seed users
- admin@example.com / password123
- taras@example.com / password123
- olena@example.com / password123
- anna@example.com / password123
- mark@example.com / password123

## Suggested next move in Cursor
1. Run the stack
2. Verify auth + discover + matches
3. Replace mock AI provider
4. Replace mock payments
5. Replace mock push + storage
6. Add cloud deployment and secrets management
