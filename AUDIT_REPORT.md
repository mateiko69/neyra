# NEYRA Production Audit Report

**Date:** 2026-05-02  
**Scope:** Full-stack audit per task list (FastAPI + Next.js).  
**Constraints respected:** No `.env` or secret changes; no DB reset; no destructive git operations.

---

## Initial findings (pre-fix)

### Task 1 — React Rules of Hooks
- **`frontend/app/components/ui.tsx` (`Toast`):** Early `if (!text) return null` runs **before** `useMemo` / `useEffect`, violating Rules of Hooks when `text` toggles between null and non-null.

### Task 2 — AI locale
- **`_resolve_ai_locale_for_request`** already falls back to `"en"` when no header/body locale (no profile `native_language` in this path).
- **`_start_strategy_fallback`:** Forced non-`en|uk|ru` locales to English and returned **one** opener; Gemini prompt used **narrow** `lang_name` (en/uk/ru only).
- **`_revive_fallback`:** Ukrainian-only strings; used from chat-copilot without locale → wrong language for non-UK users.
- **`_coach_advice_text`:** Ukrainian vs English only; other UI locales got English (inconsistent).
- **Quota error detail** in `_gemini_http_error_response`: Ukrainian message regardless of locale.
- **`bg`** locale present in `frontend/public/locales` but missing from `SUPPORTED_APP_LANGUAGES` (normalized to `en`).

### Task 3 — AI quality / safety
- Start-strategy deterministic fallback did not always return **three** openers where the premium path does.
- Copilot revive Gemini system prompt mixed **English rules with Ukrainian examples** in “Types” lines.

### Task 4 — Discover / cache
- Cached discover path computed `swiped` but **never used** (dead code / incomplete logic); cache key already includes `bump_user_cache_version` from swipes — invalidation should occur on swipe; soft-ranking tests expect passed cards may still appear.

### Task 5 — UI “black blocks”
- **`globals.css`:** Several `rgba(0,0,0,…)` overlays and `#000` video placeholder; some can be replaced with `--panel` / glass tokens for a cleaner premium look (verify flow kept readable).

### Task 6 — `.gitignore`
- Already lists `.env*`, `*.db`, `backups/`, `uploads/`, `.pytest_cache/`, `__pycache__/`, `.next/`, `node_modules/`.
- If any secret files are **tracked**, use `git rm --cached <file>` locally (not run by automation).

### Task 7 — Alembic
- **Single head:** `0041_user_trial_ai_usage_fields` (verified via `alembic heads`).

### Task 8 — Tests / build
- To be executed after fixes; results appended below.

---

## Fixes applied

### Task 1 — Toast / Rules of Hooks
- Reordered `Toast` so `useMemo` and `useEffect` run **before** `if (!text) return null`, preserving placement and auto-dismiss behavior.

### Task 2 — AI locale system
- **`_resolve_ai_locale_for_request`** (already correct): transport `X-Locale` / `X-UI-Locale` / query `locale`, then body `locale`, else **`en`** — no profile language fallback.
- **`_start_strategy_fallback`:** Removed forced downgrade of non-en/uk/ru to English; returns **three** typed openers via `opener_typed_fallback` + localized wait line via `start_strategy_wait_reason` (`_START_STRATEGY_WAIT` in `ai_fallback_phrases.py`).
- **Gemini `start-strategy` prompt:** `english_language_name_for_ai_prompt()` maps **all** supported app locales to English language names for strict instructions.
- **Diversity backup path:** Uses `opener_typed_fallback(locale)` instead of en/ru/uk-only strings.
- **`_revive_fallback`:** Uses `timed_revive_triple(locale)`; called with `copilot_locale`.
- **`_coach_advice_text`:** Delegates to `coach_advice_locales.coach_advice_for_move` for **en, uk, ru, fr, de, es, ar, ja, zh, zh-TW** (others fall back to English block — single-language responses).
- **Quota HTTP 429 message:** Neutral **English** API message (no Ukrainian-only string).
- **`app_language`:** Added **`bg`** to `SUPPORTED_APP_LANGUAGES` (matches `frontend/public/locales`).
- **`ai_fallback_phrases`:** Bulgarian (`bg`) rows for timed packs + opener triples; `_START_STRATEGY_WAIT` for strategy fallback.

### Task 3 — AI quality / safety
- Start-strategy deterministic fallback always returns **3** openers.
- Copilot revive Gemini prompt “Types” lines are **English-only** (removed mixed uk examples).

### Task 4 — Discover / cache
- Removed unused **`swiped`** computation in cached-feed filter path (dead code). Cache invalidation continues to rely on **`bump_user_cache_version`** on swipe + version **`v`** in cache key.

### Task 5 — UI styling
- **`globals.css`:** Introduced `--overlay-scrim`, `--surface-video`; replaced pure **`#000`** video holder and harsh fullscreen overlay with tokens.

### Task 6 — `.gitignore`
- Verified patterns already cover `.env*`, `*.db`, `backups/`, `uploads/`, `.pytest_cache/`, `__pycache__/`, `.next/`, `node_modules/`.
- **Not run:** `git rm --cached` — if any secret file is tracked, run manually (see below).

### Task 7 — DB / migrations / dev SQLite
- **Alembic:** single head `0041_user_trial_ai_usage_fields`.
- **`session.py` (SQLite autopatch):** Added `trial_active`, `trial_expires_at`, `ai_free_used_count`, `ai_last_used_at` on `users` when missing (aligns with migration 0041 for dev DBs that only use `create_all`).
- **`main.py`:** For **SQLite**, Alembic revision mismatch logs a **warning** instead of failing startup when `alembic_version` is unstamped (local `create_all` + autopatch). Postgres and other DBs still enforce revision match.

### Task 8 — Tests & build
- Backend: **522 passed** (`python -m pytest -q`) after AI reliability layer (see section below).
- Frontend: **`npm run type-check`**, **`npm run test:i18n`**, **`npm run build`** — all succeeded.

---

## Files changed

| Area | Files |
|------|--------|
| Frontend UI | `frontend/app/components/ui.tsx`, `frontend/app/globals.css` |
| AI locale / coach | `backend/app/api/v1/endpoints/ai.py`, `backend/app/services/ai/locale_prompt_language_names.py`, `backend/app/services/ai/coach_advice_locales.py`, `backend/app/services/ai/ai_fallback_phrases.py` |
| App languages | `backend/app/services/app_language.py` |
| Discover | `backend/app/api/v1/endpoints/discover.py` |
| SQLite / startup | `backend/app/db/session.py`, `backend/app/main.py` |
| Tests | `backend/tests/test_ai_locale_force.py` |
| Report | `AUDIT_REPORT.md` |

---

## Tests executed

| Command | Result |
|---------|--------|
| `cd backend && python -m pytest -q` | **522 passed** |
| `cd frontend && npm run type-check` | **OK** |
| `cd frontend && npm run test:i18n` | **OK** |
| `cd frontend && npm run build` | **OK** |

## Tests skipped

- None configured as skipped in these runs.

---

## Sensitive / git hygiene (manual)

If `git ls-files` shows any `.env` or secret artifact tracked:

```bash
git rm --cached path/to/file
```

Do not commit secrets. **This audit did not run** `git rm --cached`.

---

## Remaining risks before production

1. **Postgres** deployments must run **`alembic upgrade head`**; SQLite-only shortcuts do not replace migrations in production.
2. **Coach advice** for locales outside the explicit map (e.g. `pt`, `pl`) still uses the **English** advice block — consistent single language, but not yet localized for every public locale.
3. **`globals.css`** still uses soft black shadows elsewhere; only the worst **flat black** hotspots called out in the audit were tokenized.
4. **Rules of Hooks:** Full-repo scan was not exhaustive beyond the reported **`Toast`** issue; CI should keep **`eslint-plugin-react-hooks`** enabled on the frontend.
5. **Gemini outages:** Existing fallbacks + filters remain; monitor 503/429 handling in production dashboards.

---

## AI reliability layer (2026-05-02 follow-up)

### Objectives
- Route provider failures through `safe_ai_generate_async` / `safe_ai_generate_sync` with structured logging: `ai_fallback_triggered` (`endpoint`, `locale`, `provider`, `reason`, `error_message`).
- User-facing AI routes return **HTTP 200** with deterministic fallbacks when Gemini is down, misconfigured, times out, or returns invalid payloads — **without changing successful JSON shapes**.
- Admin diagnostics report failures in-band (**no crash**).

### Finalize checklist (2026-05-02)

- **User-facing AI endpoints protected:** listed in **Protected HTTP endpoints** (meeting-options, interest-stage, timing-engine, chat-copilot, timed-replies, coach, chat-brain suggestions, admin ai-debug).
- **Intentionally excluded internal / non–HTTP-200-forcing flows:** **Intentionally excluded from “always 200”** — wingman analyze use-case (no duplicate `ai_fallback_triggered`; `GeminiClient` warnings), engagement + A/B (`ai_fallback_triggered` once per failed call).
- **OpenAI `locale_rewrite` logging:** `locale_rewrite/strict_openai` and `locale_rewrite/batch_openai` emit `ai_fallback_triggered` with `provider=openai` when the OpenAI Responses path fails (after Gemini `safe_ai` path when enabled).
- **Final test run:** `cd backend && python -m pytest -q` → **522 passed**.

### Protected HTTP endpoints (provider wrapped or failure logged centrally)

| Endpoint | Mechanism |
|----------|-----------|
| `POST /ai/meeting-options` | `safe_ai_generate_async` → `_meeting_options_fallback` |
| `POST /ai/interest-stage` | `safe_ai_generate_async` → `_interest_stage_fallback` |
| `POST /ai/timing-engine` | `safe_ai_generate_async` → `_timing_engine_fallback` |
| `POST /ai/chat-copilot` | Existing finalize + provider failure dict (prior work) |
| `POST /ai/timed-replies` | `_log_ai_fallback` → `log_ai_fallback_triggered` + i18n fallback rows |
| `POST /ai/coach` | `safe_ai_generate_async` → `coach_intervention` |
| `POST /ai/chat-brain/suggestions` | Gemini internals + HTTP 200 when `ENABLE_AI_SUGGESTIONS` is false (fallback pack) |
| `POST /admin/ai-debug/test-gemini` | `log_ai_fallback_triggered` on Gemini/admin failures (response shape unchanged) |

### Internal modules (wrapped)

| Module | Notes |
|--------|--------|
| `app/services/ai/orchestrator.py` — `run_improve_reply_core` (Gemini path) | `safe_ai_generate_async` → `improve_draft_locally` |
| `app/application/use_cases/ai/wingman_next_step.py` — `suggest_next_step` | `safe_ai_generate_async` → `EscalationAdvisor.suggest_next_step` |
| `app/services/ai/locale_rewrite.py` | `safe_ai_generate_async` for Gemini; OpenAI fallback calls `log_ai_fallback_triggered` (`locale_rewrite/strict_openai`, `locale_rewrite/batch_openai`, `provider=openai`) — no duplicate with Gemini `safe_ai` logs (different provider / step) |
| `app/services/ai/chat_brain_suggestions.py` — `_gemini_tone_pack`, `_gemini_one_line` | `safe_ai_generate_async` with `None` fallback |
| `app/services/engagement/agent.py` — `_call_gemini_for_actions`, tone pack, single message | Admin-only; on Gemini failure: single `ai_fallback_triggered` (`engagement/actions`, `engagement/tone_pack`, `engagement/single_message`) then rule fallbacks — **no HTTP contract change** |
| `app/services/ab_engine.py` — `generate_variants_with_ai` | Internal A/B helper; on failure: `ai_fallback_triggered` (`ab_engine/variants`) then `_fallback_ai_variants` — **no forced HTTP 200** at this layer |

### Intentionally excluded from “always 200” reliability wrapping

These flows are **not** user-critical HTTP surfaces in the same sense as chat/copilot; they keep existing status/body behavior and only add **single** structured fallback logs where we touch them:

| Flow | Role | Failure handling |
|------|------|------------------|
| `app/application/use_cases/ai/wingman_analyze.py` — `analyze_conversation` | Used by `POST /ai/...` wingman analyze; provider failure → deterministic `ConversationAnalyzer` | **No extra `ai_fallback_triggered` here** — `GeminiClient` / transport already emits warnings; adding another event would duplicate observability for the same failure. |
| Engagement agent + A/B engine | Admin / experiments | `ai_fallback_triggered` once per failed Gemini call (see table above); deterministic fallbacks unchanged. |

### Endpoints intentionally not calling Gemini (deterministic only — no provider wrap)

| Endpoint | Reason |
|----------|--------|
| `POST /ai/meeting-readiness` | Heuristic scoring only |
| `POST /ai/recovery` | `recovery_intervention` rules |
| `POST /ai/next-step` (minimal body) | Fixed localized triple |
| `POST /ai/escalation-readiness`, `/ai/readiness-score`, `/ai/conversation-quality` | Local scoring |

### `safe_ai` behavior

- **`reraise`:** Optional; when true, logs then re-raises (for future choke-points).
- **Async fallbacks:** If `fallback_fn()` returns an awaitable, it is awaited (`inspect.isawaitable`).

### Tests

| Command | Result |
|---------|--------|
| `cd backend && python -m pytest -q` | **522 passed** |

New / updated: `tests/test_ai_reliability_layer.py`, `tests/test_chat_brain_suggestions_endpoint.py` (disabled AI → 200 + fallback), existing copilot tests.

### Remaining production risks

1. **`GeminiProvider._generate_json`** is still the low-level caller inside many flows; HTTP-level `safe_ai` + orchestrator covers user-visible surfaces — duplicate `ai_fallback_triggered` is possible if both layers log the same failure chain.
2. **Wingman analyze** uses provider `analyze_conversation` + heuristic fallback; rely on **`GeminiClient` warnings** for transport failures rather than a second `ai_fallback_triggered` at the use-case layer.
