# Cursor / Codex Handoff

Use this repository as the base and push it in the following order:

## Phase 1: Make it run cleanly
- run docker compose
- verify Alembic migration
- verify seed data
- test login
- test discover feed
- test swipes and mutual match flow
- test websocket chat
- test worker notifications using mock provider

## Phase 2: Replace mocks
- OpenAI/Gemini provider implementation
- Stripe checkout and webhooks
- S3 upload provider
- Firebase/APNs push provider

## Phase 3: Product hardening
- stronger moderation
- image verification and NSFW checks
- antifraud pipeline
- better ranking with embeddings
- proper async jobs
- structured metrics and tracing

## Phase 4: Release
- mobile auth persistence
- app icons / splash / build configs
- privacy policy / terms / moderation policy
- app store and play store subscription flows
