# Architecture

## Backend (Clean Architecture)

The backend is organized into four layers. Existing code is preserved, while new
packages provide clear seams so future features don’t mix concerns.

### Domain (`backend/app/domain`)
- Entities and business rules (today: SQLAlchemy models are the primary entities)

### Application (`backend/app/application`)
- Use-cases and orchestration
- AI system modules:
  - `application/ai/match_engine.py` (compatibility scoring)
  - `application/ai/conversation_ai.py` (message suggestions)
  - `application/ai/profile_ai.py` (profile analysis)
  - `application/ai/ranking_engine.py` (future ML ranking seam)

### Infrastructure (`backend/app/infrastructure`)
- DB, external services, provider implementations (AI, payments, storage, push)

### Interfaces (`backend/app/interfaces`)
- HTTP / WebSocket adapters
- `interfaces/http/router.py` is the stable router entrypoint used by `app.main`

## Services
- ai providers
- storage providers
- push providers
- payments providers
- analytics tracker
- event publisher
- redis queue
- notification fanout
- premium access rules

## Frontend
- Next.js App Router
- login
- discover
- profile
- matches
- subscription
- admin

## Mobile
- Expo starter
- login
- discover
- premium tab

## Worker
- consumes queued events from Redis
- sends mock push notifications
- ready to grow into Celery / RQ / Dramatiq / custom workers
