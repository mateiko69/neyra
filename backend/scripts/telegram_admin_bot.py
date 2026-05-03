from __future__ import annotations

import json
import os
import time
import traceback
import atexit
import errno
from dataclasses import dataclass
from html import escape
from typing import Any

import requests


# -----------------------------
# Config
# -----------------------------

TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
_IDS_RAW = (
    (os.getenv("ADMIN_TELEGRAM_IDS") or os.getenv("TELEGRAM_ADMIN_IDS") or "").strip()
)
ADMIN_TELEGRAM_IDS = {int(x.strip()) for x in _IDS_RAW.split(",") if x.strip().isdigit()}

BACKEND_BASE_URL = (os.getenv("BACKEND_BASE_URL") or "http://localhost:8000").strip().rstrip("/")
ADMIN_BOT_SERVICE_TOKEN = (os.getenv("ADMIN_BOT_SERVICE_TOKEN") or "").strip()

POLL_TIMEOUT_S = 25


def _log(msg: str) -> None:
    # Never print secrets; keep logs minimal and safe.
    try:
        print(msg, flush=True)
    except Exception:
        pass


def _mask_token(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    if len(t) <= 10:
        return t[:3] + "***"
    return t[:6] + "***" + t[-3:]


def _validate_telegram_token() -> None:
    if not TELEGRAM_BOT_TOKEN:
        _log("ERROR: TELEGRAM_BOT_TOKEN is missing. Exiting.")
        raise SystemExit(1)
    # Verify via getMe (no secret printed)
    try:
        url = TG_API.format(token=TELEGRAM_BOT_TOKEN, method="getMe")
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        if not data.get("ok"):
            _log("ERROR: Invalid Telegram token (getMe returned not ok). Exiting.")
            raise SystemExit(1)
        _log(f"Telegram token OK ({_mask_token(TELEGRAM_BOT_TOKEN)})")
    except SystemExit:
        raise
    except Exception:
        _log("ERROR: Invalid Telegram token (getMe failed). Exiting.")
        raise SystemExit(1)


def _acquire_single_instance_lock() -> None:
    """
    Best-effort single-instance lock inside container.
    Prevents accidental double execution if compose restarts quickly.
    """
    lock_path = os.getenv("TELEGRAM_BOT_LOCK_PATH") or "/tmp/telegram_admin_bot.lock"
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.close(fd)
    except OSError as e:
        if e.errno == errno.EEXIST:
            raise SystemExit("Another telegram bot instance appears to be running (lock exists).")
        raise

    def _cleanup() -> None:
        try:
            os.unlink(lock_path)
        except Exception:
            pass

    atexit.register(_cleanup)


def _wait_for_backend_ready(max_seconds: int = 60) -> None:
    """
    Wait until backend is reachable (no auth required).
    Uses /health/ready to avoid leaking credentials.
    """
    url = f"{BACKEND_BASE_URL}/health/ready"
    deadline = time.time() + float(max_seconds)
    _log("Waiting for backend...")
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=4)
            if r.status_code == 200:
                _log("Connected to backend")
                return
        except Exception:
            pass
        time.sleep(2.5)
    raise SystemExit("Backend not ready after waiting 60 seconds.")


def _must_configure() -> None:
    missing = []
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not ADMIN_TELEGRAM_IDS:
        missing.append("ADMIN_TELEGRAM_IDS (or TELEGRAM_ADMIN_IDS)")
    if not ADMIN_BOT_SERVICE_TOKEN:
        missing.append("ADMIN_BOT_SERVICE_TOKEN")
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)}")


# -----------------------------
# Telegram API client
# -----------------------------

TG_API = "https://api.telegram.org/bot{token}/{method}"


def tg_call(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = TG_API.format(token=TELEGRAM_BOT_TOKEN, method=method)
    res = requests.post(url, json=payload, timeout=45)
    res.raise_for_status()
    data = res.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data


def tg_send(chat_id: int, text: str, keyboard: list[list[dict[str, str]]] | None = None) -> int | None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard is not None:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    data = tg_call("sendMessage", payload)
    res = data.get("result")
    if isinstance(res, dict):
        mid = res.get("message_id")
        if isinstance(mid, int):
            return mid
    return None


def tg_edit(chat_id: int, message_id: int, text: str, keyboard: list[list[dict[str, str]]] | None = None) -> None:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if keyboard is not None:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    tg_call("editMessageText", payload)


def tg_answer_callback(callback_query_id: str, text: str = "", *, show_alert: bool = False) -> None:
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
        payload["show_alert"] = bool(show_alert)
    tg_call("answerCallbackQuery", payload)


def tg_send_document(chat_id: int, filename: str, content: bytes, caption: str = "") -> None:
    url = TG_API.format(token=TELEGRAM_BOT_TOKEN, method="sendDocument")
    data: dict[str, Any] = {"chat_id": chat_id, "parse_mode": "HTML"}
    if caption:
        data["caption"] = caption
    res = requests.post(url, data=data, files={"document": (filename, content)}, timeout=90)
    res.raise_for_status()
    payload = res.json()
    if not payload.get("ok"):
        raise RuntimeError(f"Telegram API error: {payload}")


# -----------------------------
# Backend admin client (JWT)
# -----------------------------


@dataclass
class BackendSession:
    service_token: str = ""

    def request(self, method: str, path: str, json_body: dict | None = None) -> Any:
        if not self.service_token:
            raise RuntimeError("Missing ADMIN_BOT_SERVICE_TOKEN")
        url = f"{BACKEND_BASE_URL}{path}"
        headers = {"X-Admin-Service-Token": self.service_token}
        r = requests.request(method, url, headers=headers, json=json_body, timeout=45)
        r.raise_for_status()
        try:
            return r.json()
        except Exception:
            return r.text

    def download(self, path: str) -> tuple[str, bytes]:
        token = self.ensure_token()
        url = f"{BACKEND_BASE_URL}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        r = requests.get(url, headers=headers, timeout=60)
        if r.status_code == 401:
            self.token = ""
            token = self.ensure_token()
            headers = {"Authorization": f"Bearer {token}"}
            r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        filename = "neyra_backup.sqlite"
        disposition = str(r.headers.get("content-disposition") or "")
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip().strip('"') or filename
        return filename, r.content


backend = BackendSession(service_token=ADMIN_BOT_SERVICE_TOKEN)
BACKUP_RESTORE_PHRASE = "RESTORE NEYRA BACKUP"

# -----------------------------
# Admin bot language (MVP in-memory)
# -----------------------------

# Keyed by telegram_user_id
admin_lang: dict[int, str] = {}
sent_alert_dedupe: dict[str, float] = {}
active_alerts_cache: list[dict[str, Any]] = []
alerts_muted_until: float = 0.0
_alerts_last_poll_at: float = 0.0
_ALERT_NOTIFY_TTL_S = 24 * 60 * 60

STRINGS: dict[str, dict[str, str]] = {
    "uk": {
        "main_title": "🧠 NEYRA AI Control Center",
        "command_center": "🧠 NEYRA Command Center",
        "command_center_more": "Більше…",
        "menu_ai": "🧠 AI Assistant",
        "menu_orders": "🛒 Orders",
        "menu_shipments": "📦 Shipments",
        "menu_analytics": "📊 Analytics",
        "menu_settings": "⚙️ Settings",
        "menu_diagnostics": "🧪 System Diagnostics",
        "product_home_hint": "Оберіть розділ. Повна карта адмінки — у «Більше…».",
        "ai_hub_title": "🧠 AI Assistant",
        "ai_hub_intro": "Задайте <b>viewer</b> (акаунт, від імені якого йде AI) та <b>partner</b> (співрозмовник з матчу). Текст береться з реального чату в БД.",
        "ai_set_viewer": "👤 Viewer ID",
        "ai_set_partner": "💬 Partner ID",
        "ai_get_suggestions": "💡 Три відповіді",
        "ai_new_suggestions": "🔄 Нові підказки",
        "ai_improve": "✏️ Покращити текст",
        "ai_meeting_check": "📅 Meeting ready",
        "ai_start_strategy_btn": "🚀 Стартова стратегія",
        "ai_timed_now": "⏱ Timed: now",
        "ai_timed_reengage": "⏱ Timed: reengage",
        "ai_closer_hot": "🔥 Розмова йде добре",
        "ai_keep_chatting": "💬 Лише чат",
        "ai_pick_option": "Обрано варіант {idx}. Скопіюй у застосунок.",
        "ai_prompt_viewer": "<b>Viewer user ID</b>\n\nНадішліть число (ID користувача NEYRA).",
        "ai_prompt_partner": "<b>Partner user ID</b>\n\nНадішліть число (другий користувач у парі).",
        "ai_prompt_improve": "<b>Покращити текст</b>\n\nНадішліть чернетку одним повідомленням.",
        "ai_need_pair": "Спочатку задайте viewer та partner.",
        "orders_hub_title": "🛒 Orders & монетизація",
        "orders_hub_intro": "Підписки, промокоди та premium-операції.",
        "shipments_hub_title": "📦 Shipments & доставка",
        "shipments_hub_intro": "Матчі, залучення та «доставка» уваги в чатах.",
        "analytics_hub_title": "📊 Analytics",
        "analytics_hub_intro": "Знімки метрик продукту.",
        "settings_hub_title": "⚙️ Settings",
        "settings_hub_intro": "Мова бота та системні інструменти.",
        "diag_hub_title": "🧪 Product diagnostics",
        "diag_refresh": "🔄 Оновити",
        "alerts": "🚨 Алерти",
        "alerts_active": "Активні алерти",
        "alerts_mute_1h": "Вимкнути на 1 год",
        "alerts_unmute": "Увімкнути",
        "backup_center": "🗄 Центр резервних копій",
        "backup_create": "Створити резервну копію",
        "backup_list": "Список копій",
        "backup_export_latest": "Експорт останньої копії",
        "backup_restore": "Відновити з копії",
        "backup_status_creating": "⏳ Створюємо резервну копію…",
        "backup_status_created": "✅ Резервну копію створено",
        "backup_status_failed": "❌ Не вдалося створити резервну копію",
        "backup_field_file": "Файл",
        "backup_field_size": "Розмір",
        "backup_field_duration": "Тривалість",
        "audit_log": "🧾 Журнал аудиту",
        "audit_last": "Останні дії",
        "audit_premium": "Дії Premium",
        "audit_user": "Дії користувачів",
        "audit_system": "Системні дії",
        "audit_safety": "Дії безпеки",
        "release_manager": "🚀 Керування релізами",
        "release_readiness": "Готовність",
        "release_blockers": "Блокери",
        "release_warnings": "Попередження",
        "release_mark": "Позначити реліз",
        "statistics": "📊 Статистика",
        "users": "👥 Користувачі",
        "safety": "🛡 Безпека",
        "system": "⚙️ Система",
        "premium": "💎 Premium",
        "match_quality": "❤️ Якість матчів",
        "conversation_quality": "💬 Якість розмов",
        "engagement": "💬 Залучення",
        "growth": "📈 Зростання",
        "product_manager": "🧭 Продуктовий менеджер",
        "cto": "🧑‍💻 AI CTO",
        "menu_qa": "🧪 QA меню",
        "e2e_qa": "🧪 E2E QA",
        "qa_agent": "🧪 QA Agent / Test Pilot",
        "full_product_qa": "🧪 Full Product QA",
        "full_product_qa_title": "🧪 Full Product QA",
        "full_product_qa_intro": "One button → full system + UX + AI + product analysis.\n\nPress Run and you'll get a short, prioritized report.",
        "full_product_qa_run": "🧪 Run Full Product QA",
        "full_product_qa_fix_top": "🔧 Fix Top Issues",
        "qa_agent_title": "🧪 QA Agent / Test Pilot",
        "qa_agent_intro": "Двохетапна перевірка: спочатку <b>ідеальна англійська UX</b>, потім <b>локалізація</b>.\n\nРекомендовано: 🇺🇸 English UX QA.",
        "qa_en": "🇺🇸 English UX QA",
        "qa_l10n": "🌍 Localization QA",
        "qa_chat": "💬 Chat QA",
        "qa_menu": "🧭 Menu QA",
        "qa_bot2bot": "🤖 Bot-to-bot QA",
        "qa_last": "📊 Last QA report",
        "qa_mode_summary": "📋 Summary",
        "qa_mode_fixes": "🔧 Fixes only",
        "qa_mode_deep": "🧠 Deep analysis",
        "qa_running": "⏳ Запускаю QA…",
        "qa_disabled": "QA Agent вимкнено. Увімкни env: QA_AGENT_ENABLED=true",
        "qa_after_l10n": "⚠️ Запускай Localization QA лише <b>після</b> Gemini локалізації.",
        "founder": "👑 Режим засновника",
        "founder_daily_plan": "План на сьогодні",
        "founder_alerts": "Алерти",
        "founder_focus": "Фокус дня",
        "autopilot": "🤖 Автопілот",
        "autopilot_suggestions": "Пропозиції",
        "autopilot_run_action": "Виконати дію",
        "autopilot_empty": "Немає активних пропозицій.",
        "autopilot_are_you_sure": "Ви впевнені?",
        "back": "🔙 Назад",
        "language": "🌐 Language / Мова",
        "choose_language": "<b>Оберіть мову адмін-бота</b>\n\nВи можете змінити її пізніше через 🌐 Language / Мова.",
        "lang_uk": "🇺🇦 Українська",
        "lang_en": "🇬🇧 English",
        "refresh": "🔄 Оновити",
        "cancel": "❌ Скасувати",
        "confirm": "✅ Підтвердити",
        "access_denied": "Доступ заборонено.",
        "unknown_action": "Невідома дія.",
        "unknown_command": "Команда не розпізнана. Використай /menu.",
        "pick_section": "<b>NEYRA — адмінський AI Control Center</b>\n\nОберіть розділ:",
        "full_system_analysis": "🧠 Повний аналіз",
        "full_system_analysis_subtitle": "Fast DB/API/runtime metrics — not full browser QA.",
        "analysis_overall": "Загальний стан",
        "analysis_score": "Оцінка",
        "analysis_owner_summary": "Резюме для власника",
        "analysis_top_issues": "Топ проблем",
        "analysis_top_recs": "Топ рекомендацій",
        "analysis_next_actions": "Наступні дії",
        "analysis_sections": "Ключові розділи",
        "ai_help": "🤖 AI Допомога",
        "full_analysis_create_backup": "📦 Створити резервну копію зараз",
        "menu_ai_quality": "🤖 Якість AI",
        "menu_localization_geo": "🌍 Локалізація / гео",
        "menu_quick_stats": "📊 Статистика",
        "menu_quick_founder": "👑 Засновник",
        "menu_quick_system": "⚙️ Система",
        "status_critical": "🚨 Критично",
        "status_warning": "⚠️ Увага",
        "status_healthy": "✅ Добре",
        "cc_status_label": "Статус",
        "cc_today": "Сьогодні",
        "cc_users_line": "👥 користувачі",
        "cc_active": "активні",
        "cc_new": "нові",
        "cc_matches": "❤️ матчі",
        "cc_messages": "💬 повідомлення",
        "cc_ai_calls": "🤖 AI виклики",
        "cc_premium": "💎 premium",
        "cc_reports": "🛡 скарги",
        "cc_top_priority": "🔥 Топ-пріоритет",
        "cc_default_rec_title": "Зростання щоденних активних розмов",
        "cc_default_rec_reason": "Критичних агрегованих проблем не виявлено.",
        "cc_default_rec_action": "Відкрийте щоденний план режиму засновника.",
        "alerts_push_title": "NEYRA Алерт",
        "alerts_default_title": "Алерт",
        "alerts_source": "Джерело",
        "alerts_action": "Дія",
        "alerts_status_label": "Статус",
        "alerts_status_active": "Увімкнено",
        "alerts_status_muted": "Вимкнено",
        "alerts_none_active": "Активних алертів немає.",
        "backup_choose_action": "Оберіть дію:",
        "backup_no_backups": "Резервних копій не знайдено.",
        "backup_select_file": "Оберіть файл для відновлення:",
        "backup_restore_warn_intro": "⚠️ Це замінить поточну базу даних із резервної копії:",
        "backup_restore_type_phrase": "Введіть точно:",
        "audit_choose_view": "Оберіть журнал:",
        "audit_no_entries": "Записів немає.",
        "ai_help_title_prefix": "🤖 AI Допомога",
        "ai_help_what_is": "Що це:",
        "ai_help_watch": "На що звернути увагу:",
        "ai_help_do": "Що зробити:",
        "ai_help_risks": "Ризики:",
        "ai_help_next": "Наступний крок:",
        "ai_help_bullet_empty": "• —",
        "ai_help_analysis_title": "🤖 AI аналіз",
        "ai_help_screen_shows": "Що показує екран",
        "ai_help_issues_block": "Що може бути не так",
        "ai_help_next_steps": "Що робити далі",
        "ai_help_no_issues": "За правилами критичних проблем не виявлено; усе одно переглянь сигнали вище.",
        "render_error_generic": "Не вдалося відобразити екран. Спробуйте оновити або поверніться назад.",
        "label_run_scan": "Запустити скан",
        "label_show_critical": "Критичні",
        "label_warnings": "Попередження",
        "label_missing_translations": "Відсутні переклади",
        "label_critical_issues": "Критичні проблеми",
        "label_last_report": "Останній звіт",
        "menu_qa_intro": "Перевірка меню адмін-бота (лише читання).",
        "menu_qa_scan_line": "Меню: {menus} · Кнопки: {buttons} · Колбеки: {callbacks}",
        "menu_qa_metrics_line": "Немає обробників: {mh} · Немає перекладів: {mt} · Небезпечні: {unsafe} · Помилки рендеру: {rend}",
        "e2e_qa_intro": "Перевірка критичних сценаріїв (лише читання за замовчуванням).",
        "e2e_flows_line": "Потоки: {flows} · Успішно: {passed} · Попередження: {warn} · Помилки: {failed}",
        "e2e_top_issues": "Топ проблем:",
        "period_today": "Сьогодні",
        "period_7d": "7 днів",
        "period_30d": "30 днів",
        "label_issues": "Проблеми",
        "label_recommendations": "Рекомендації",
        "growth_issues_heading": "Проблеми (7 днів):",
        "growth_recs_heading": "Рекомендації (топ 5):",
        "growth_choose_period": "Оберіть період:",
        "pm_choose_brief": "Оберіть бриф:",
        "pm_daily_brief": "Денний бриф",
        "pm_weekly_digest": "Тижневий дайджест",
        "label_risks": "Ризики",
        "label_next_actions": "Наступні дії",
        "pm_top_priority": "Топ-пріоритет:",
        "pm_why": "Чому:",
        "pm_action": "Дія:",
        "pm_top3": "Топ-3 пріоритети:",
        "pm_risks_heading": "Ризики:",
        "pm_next_heading": "Далі:",
        "pm_health_score": "Оцінка здоров’я продукту: {score}/100\n\n",
        "pm_brief_7d": "Бриф 7 д",
        "pm_brief_30d": "Бриф 30 д",
        "cto_choose_roadmap": "Оберіть період планування:",
        "cto_tech_risks": "Технічні ризики",
        "cto_next_dev": "Наступні dev дії",
        "cto_top_eng": "Топ інженерний пріоритет:",
        "cto_reason": "Причина:",
        "cto_action": "Дія:",
        "cto_top3": "Топ-3 пріоритети:",
        "cto_debt": "Техборг:",
        "cto_risks_heading": "Ризики:",
        "cto_next_heading": "Далі:",
        "cto_next_actions_heading": "Наступні dev дії:",
        "cto_risks_page_heading": "Технічні ризики:",
        "json_truncated": "…(скорочено)",
        "backup_api_invalid_response": "Некоректна або порожня відповідь API резервного копіювання",
        "backup_create_confirm_html": "<b>🗄 Резервні копії</b>\n\nСтворити нову резервну копію бази даних?",
        "release_mark_html": "<b>🚀 Позначити реліз</b>\n\nНадішліть одним повідомленням:\n<pre>ВЕРСІЯ | НОТАТКИ</pre>\nПриклад:\n<pre>0.1.0 | Початковий бета-реліз</pre>",
        "confirm_l10n_fix_html": "<b>Підтвердження</b>\n\nЗапустити безпечне авто-виправлення локалізації? Можуть з’явитися нові порожні файли локалей.\n\nПродовжити?",
        "confirm_lagent_fix_html": "<b>Підтвердження</b>\n\nЗапустити безпечне авто-виправлення <b>Localization Agent</b>? (лише dev/staging; заповнює ключі з en, виправляє сирі ключі та латинські назви міст у uk.json)\n\nПродовжити?",
        "confirm_backup_db_html": "<b>Підтвердження</b>\n\nЗробити резервну копію БД? (dev/non-prod)\n\nПродовжити?",
        "confirm_clear_cache_html": "<b>Підтвердження</b>\n\nОчистити кеш (Redis flushdb)? (dev/non-prod)\n\nПродовжити?",
        "confirm_run_migrations_html": "<b>Підтвердження</b>\n\nЗапустити міграції Alembic? (dev/non-prod)\n\nПродовжити?",
        "confirm_grant_premium_html": "<b>Підтвердження</b>\n\nНадати Premium на {days} дн. користувачу {uid}?",
        "confirm_revoke_premium_html": "<b>Підтвердження</b>\n\nСкасувати Premium для користувача {uid}?",
        "confirm_memreset_html": "<b>Підтвердження</b>\n\nСкинути AI-пам’ять для користувача {uid}?",
        "ban_request_html": "<b>🚫 Бан користувача {uid}</b>\n\nНадішліть причину бану одним повідомленням.",
        "confirm_rep_dismiss_html": "<b>Підтвердження</b>\n\nЗакрити скаргу #{rid}?",
        "confirm_rep_ban_html": "<b>Підтвердження</b>\n\nЗакрити скаргу #{rid} з дією ban (користувач {uid})?",
        "confirm_premium_grant_all_html": "<b>Підтвердження</b>\n\nНадати Premium усім dev-користувачам (example.com) на 30 днів? (non-prod)\n\nПродовжити?",
        "confirm_match_recompute_html": "<b>Підтвердження</b>\n\nЗапустити перерахунок сумісності (best-effort, без приватних чатів)?",
        "confirm_unban_html": "<b>Підтвердження</b>\n\nРозблокувати користувача {uid}?",
        "toast_muted_1h": "Вимкнено на 1 год",
        "toast_unmuted": "Увімкнено знову",
        "toast_ok": "Готово",
        "toast_confirm_expired_retry": "Підтвердження прострочене. Спробуйте ще раз.",
        "toast_confirm_expired_short": "Підтвердження прострочене.",
        "toast_executing": "Виконання…",
        "toast_confirmation_expired_en": "Підтвердження прострочене.",
        "toast_no_backups": "Немає резервних копій",
        "toast_exporting": "Експорт…",
        "toast_restoring": "Відновлення…",
        "toast_marking_release": "Позначення релізу…",
        "toast_loading": "Завантаження…",
        "toast_scan_running": "Запуск скану…",
        "toast_lagent_fix": "Запуск безпечного виправлення…",
        "toast_scan_short": "Скан…",
        "toast_safe_fix": "Безпечне виправлення…",
        "toast_backup_db": "Резервна копія БД…",
        "toast_clearing_cache": "Очищення кешу…",
        "toast_running_migrations": "Запуск міграцій…",
        "toast_not_wired": "Ще не підключено (потрібен ендпоінт).",
        "toast_grant_premium": "Надання Premium…",
        "toast_revoke_premium": "Скасування Premium…",
        "toast_reset_ai_memory": "Скидання AI-пам’яті…",
        "toast_unbanning": "Розблокування…",
        "toast_banning": "Блокування…",
        "toast_dismissing": "Закриття…",
        "toast_resolving_banning": "Закриття + ban…",
        "toast_granting": "Надання…",
        "toast_creating": "Створення…",
        "toast_recomputing": "Перерахунок…",
        "l10n_fix_suggestions_title": "<b>📊 Пропозиції виправлень</b>",
        "l10n_agent_missing_title": "<b>🌍 Localization Agent</b>\n\n<b>Відсутні ключі</b>",
        "unban_confirm_title": "<b>Підтвердження</b>\n\nРозблокувати користувача {uid}?",
        "backup_center_title_plain": "<b>🗄 Резервні копії</b>\n\nСтворити нову резервну копію БД? Дозволено поза production.",
        "alerts_menu_line": "Статус: {status}",
        "active_alert_line": "{idx}. {icon} <b>{title}</b>\n{message}\n{source_line}",
        "active_alert_source_line": "Джерело: {source}",
        "backup_list_bytes": "{n} байт",
        "period_7d_short": "7 д",
        "period_30d_short": "30 д",
        "word_none": "Немає",
        "release_menu_intro": "Перевірки та позначки релізу без деплою.",
        "release_readiness_heading": "🚀 Готовність до релізу",
        "release_score_line": "Оцінка: {score}/100",
        "release_status_line": "Статус: {status}",
        "release_environment_line": "Середовище: {env}",
        "release_recommended_actions": "Рекомендовані дії",
        "release_checks": "Перевірки",
        "release_ready": "Готово",
        "release_not_ready": "Не готово",
        "stats_title": "📊 NEYRA — {period}",
        "stats_users_line": "👥 Користувачі: {total} / нові {new_u} / активні {active}",
        "stats_profiles_line": "✅ Профілі: заповнено {done} · верифіковано {verified}",
        "stats_dating_line": "❤️ Знайомства: лайки {likes} · матчі {matches}",
        "stats_messages_line": "💬 Повідомлення: {messages} · активні чати {active_chats} · мертві чати {dead_chats}",
        "stats_ai_line": "🤖 AI: виклики {calls} · помилки {errors} · частка відповідей {reply_rate}",
        "stats_ai_partner_line": "↩️ Відповідь партнера після AI: {partner_reply} · fallback {fallback}",
        "stats_premium_line": "💎 Premium: пробні {trials} · premium {premium} · конверсія {conversion}",
        "stats_safety_line": "🛡 Скарги: відкриті {open_r} · нові {new_r} · забанені {banned}",
        "system_doctor_title": "⚙️ System Doctor",
        "system_errors_24h": "⚠️ помилки за 24 год: {n}",
        "system_fallback_24h": "⚠️ fallback за 24 год: {n}",
        "system_last_errors_title": "📄 Останні помилки",
        "system_backup_db_title": "<b>🗄 Резервна копія БД</b>",
        "system_clear_cache_title": "<b>🧹 Очистити кеш</b>",
        "system_run_migrations_title": "<b>🧬 Запустити міграції</b>",
        "system_backup_db_btn": "🗄 Резервна копія БД",
        "system_clear_cache_btn": "🧹 Очистити кеш",
        "system_run_migrations_btn": "🧬 Запустити міграції",
        "ai_quality_title": "🤖 Якість AI",
        "ai_cache_clear": "🧹 Очистити кеш AI",
        "l10n_geo_title": "🌍 Локалізація / гео",
        "l10n_coverage_title": "📊 Покриття локалізації",
        "l10n_coverage_no_rows": "<i>Немає рядків локалей</i>",
        "l10n_coverage_row": "{flag} <b>{label}</b> — унікальні {unique}% · наявні {present}%",
        "l10n_coverage_catalog": "\n\n<b>Каталог (не-EN):</b> відсутні={missing}, сирі={raw}, EN-фолбек={fallback}",
        "l10n_btn_coverage": "📊 Покриття",
        "l10n_btn_agent": "🌍 Localization Agent",
        "l10n_agent_intro": (
            "<b>🌍 Localization Agent</b>\n\n"
            "Контроль якості i18n для <code>frontend/locales/*.json</code>. "
            "Скан лише для читання. Безпечне виправлення заповнює відсутні ключі з англійської та виправляє типові плейсхолдери "
            "(лише dev/staging)."
        ),
        "l10n_agent_run_scan": "🔍 Запустити скан",
        "l10n_agent_safe_fix_btn": "🛠 Безпечне авто-виправлення",
        "l10n_agent_missing_btn": "🔑 Відсутні ключі",
        "l10n_agent_cities_btn": "🏙 Проблемні назви міст",
        "l10n_cov_top_missing": "🔑 Топ відсутніх",
        "l10n_cov_fix_suggestions": "🛠 Пропозиції виправлень",
        "l10n_report_title": "<b>Звіт локалізації</b>",
        "l10n_top_missing_title": "<b>📊 Топ відсутніх ключів</b> (за missing+empty)",
        "l10n_fix_suggestions_still_en": "<b>📊 Пропозиції виправлень</b> (досі англійською)",
        "l10n_agent_scan_result": "<b>🌍 Localization Agent</b>\n\n<b>Скан</b>\n",
        "l10n_agent_bad_cities_title": "<b>🌍 Localization Agent</b>\n\n<b>Проблемні міста</b>\n",
        "l10n_agent_safe_fix_title": "<b>🌍 Localization Agent</b>\n\n<b>Безпечне виправлення</b>\n",
        "result_backup_restored": "<b>🗄 Відновлено з резервної копії</b>",
        "result_release_marked": "<b>🚀 Реліз позначено</b>",
        "result_premium_granted": "<b>💎 Premium надано</b>",
        "result_premium_revoked": "<b>❌ Premium скасовано</b>",
        "result_ai_memory_reset": "<b>🧠 AI-пам’ять скинуто</b>",
        "result_unbanned": "<b>✅ Розблоковано</b>",
        "result_banned": "<b>🚫 Заблоковано</b>",
        "result_dismissed": "<b>✅ Скаргу закрито</b>",
        "result_banned_resolved": "<b>🚫 Заблоковано та закрито</b>",
        "result_grant_all_dev": "<b>💎 Надано всім dev</b>",
        "result_promo_created": "<b>🎟 Промокод створено</b>",
        "result_recompute_done": "<b>❤️ Перерахунок виконано</b>",
        "mq_recompute_failed": "<b>❤️ Помилка перерахунку</b>\n\nНе вдалося виконати запит до сервера.",
        "safety_menu_intro": "Оберіть розділ:",
        "safety_open_reports": "Відкриті скарги",
        "safety_resolved_reports": "Закриті скарги",
        "premium_menu_intro": "Оберіть дію:",
        "premium_overview_title": "💎 Огляд Premium",
        "premium_expiring_title": "⏳ Закінчення пробних (3 дн.)",
        "premium_grant_all_dev": "Надати Premium усім dev",
        "premium_create_promo": "Створити промокод",
        "reports_title": "🛡 Скарги",
        "reports_status": "Статус",
        "reports_count": "Кількість",
        "report_detail_title": "🛡 Деталі скарги",
        "report_open_reported": "👤 Відкрити повідомленого",
        "report_dismiss": "✅ Закрити",
        "report_ban_user": "🚫 Заблокувати",
        "mq_menu_intro": "Оберіть дію:",
        "mq_overview": "Огляд",
        "mq_weak_matches": "Слабкі матчі",
        "mq_dead_chats": "Мертві чати",
        "mq_recompute": "Перерахунок сумісності",
        "mq_weak_title": "🩶 Слабкі матчі (30 дн.)",
        "mq_dead_title": "💤 Мертві чати (без повідомлень, 3+ дн.)",
        "users_section_title": "👥 Користувачі",
        "users_search_prompt": "Надішліть пошуковий запит (email / ім’я / id).",
        "users_query": "Запит: {q}",
        "users_found": "Знайдено: {n}",
        "users_new_search": "🔎 Новий пошук",
        "user_card_title": "👤 Користувач",
        "user_grant_premium_7d": "💎 Надати Premium 7 дн.",
        "user_grant_premium_30d": "💎 Надати Premium 30 дн.",
        "user_revoke_premium": "❌ Скасувати Premium",
        "user_reset_ai_memory": "🧠 Скинути AI-пам’ять",
        "user_ban": "🚫 Бан",
        "user_unban": "✅ Розбан",
        "promo_create_title": "Створити промокод",
        "promo_create_instructions": (
            "<b>Створити промокод</b>\n\nНадішліть одним повідомленням:\n<pre>CODE DAYS MAX_USES</pre>\nНапр.: <pre>NEYRA_TEST 7 100</pre>"
        ),
        "section_stub": "<b>Розділ</b>: {key}\n\n(ще не підключено)",
        "founder_north_star": "📈 <b>North Star:</b>\n{metric}: {value} ({trend})",
        "founder_today_heading": "🔥 <b>Сьогодні:</b>",
        "founder_no_priorities": "Немає пріоритетів.",
        "founder_alerts_heading": "⚠️ <b>Алерти:</b>",
        "founder_no_alerts": "Алертів немає.",
        "founder_ns_default_metric": "Щоденні активні розмови",
        "founder_ns_default_trend": "без змін",
        "founder_focus_heading": "🎯 <b>Фокус:</b>\n",
        "founder_default_focus": "Зростання щоденних активних розмов",
        "cq_choose_period": "Оберіть період:",
        "cq_issues_heading": "Проблеми (7 днів):",
        "cq_overview_ai_options": "Варіанти AI: показано {shown} / обрано {selected}",
        "cq_overview_selection": "Обрання: {sel} · Редагування: {edited}",
        "cq_overview_partner_reply": "Частка відповіді партнера: {rate}",
        "cq_overview_stalled": "Застійні чати: {stall} · Використано revive: {revive}",
        "cq_overview_meeting": "Зустріч: запропоновано {suggested} / відхилено {rejected}",
        "cq_best_worst_style": "\nНайкращий стиль: {best} · Найгірший стиль: {worst}",
        "cq_issues_prefix": "\n\nПроблеми: ",
        "growth_overview_new_active": "Нові користувачі: {new_u} · Активні: {active}",
        "growth_overview_profile": "Заповнення профілю: {prof} · Фото додано: {photo}",
        "growth_overview_first": "Перший матч: {match} · Перше повідомлення: {msg}",
        "growth_overview_premium": "Конверсія Premium: {conv} · Перегляди paywall: {views}",
        "growth_overview_referral_rewards": "Реферальні нагороди: нарахування Premium {grants} · сигнали зловживань {flags}",
        "premium_overview_referral_line": "Реферальні нагороди (30 дн.): {grants} нарахувань · {days} днів Premium · сигнали зловживань: {flags}",
        "growth_overview_locales": "Топ локалі: {locales}",
        "growth_overview_countries": "Топ країни: {countries}",
        "growth_overview_top_recs": "\nТоп рекомендації: {recs}",
        "menu_qa_status": "Статус:",
        "e2e_intro_alt": "Перевірка критичних сценаріїв (лише читання за замовчуванням).",
        "confirm_title_plain": "<b>Підтвердження</b>",
        "autopilot_action_clear_cache": "Очистити кеш Redis",
        "autopilot_action_run_migrations": "Запустити міграції БД",
        "autopilot_action_recompute_matches": "Перерахувати сумісність матчів",
        "autopilot_action_localization_scan": "Запустити скан локалізації",
        "autopilot_tool_prefix": "🔧 ",
        "audit_total_code": "total={total}",
        "word_unknown": "невідомо",
        "word_alert": "Алерт",
        "word_priority": "Пріоритет",
        "cto_health_score": "Оцінка технічного здоров’я: {score}/100",
        "mq_overview_matches": "Матчі: {total} · сьогодні {today}",
        "mq_overview_counts": "Слабкі: {weak} · мертві чати {dead} · активні чати {active}",
        "mq_overview_rates": "Частка відповідей: {reply} · взаємні лайки: {mutual}",
        "mq_overview_ai": "Покриття AI-матчів: {cov} · середній бал: {score}",
        "mq_overview_top_issues": "\nТоп проблем: {issues}",
        "match_quality_title_plain": "❤️ Якість матчів",
        "conversation_issues_label": "Проблеми:",
        "l10n_coverage_generated_at": "\n\n<code>generated_at</code>: {value}",
        "system_api_label": "API",
        "system_db_label": "БД",
        "system_redis_label": "Redis",
        "system_gemini_label": "Gemini",
        "engagement_menu_intro": "Підказки для першого повідомлення та оживлення чатів. Лише агрегати та згенерований текст — без вмісту приватних повідомлень.",
        "engagement_btn_overview": "Огляд",
        "engagement_btn_suggested": "Запропоновані дії",
        "engagement_btn_revive": "Оживити чати",
        "engagement_btn_first_boost": "Буст першого повідомлення",
        "engagement_btn_ai_suggestions": "🤖 AI підказки",
        "engagement_first_rate": "Частка з першим повідомленням: {pct}",
        "engagement_reply_rate": "Частка взаємних відповідей: {pct}",
        "engagement_dead_chats": "Мертві чати (3+ дн., без повідомлень): {n}",
        "engagement_chats_no_msg": "Матчі без жодного повідомлення: {n}",
        "engagement_stale_sample": "Застійні у вибірці (тиша 3+ дн.): {n}",
        "engagement_avg_first": "Середній час до 1-го повідомлення: {hours} год",
        "engagement_revive_success": "Успіх revive (30 дн., аналітика): {pct}",
        "engagement_issues_header": "⚠️ Проблеми:",
        "engagement_no_issues": "Критичних агрегованих проблем не виявлено.",
        "engagement_issue_line_no_msg": "• {n} чат(ів) без повідомлень",
        "engagement_issue_line_stale": "• {n} застійних чат(ів) (тиша 3+ дн.)",
        "engagement_actions_title": "🔥 Запропоновані дії:",
        "engagement_actions_empty": "Зараз немає запропонованих дій.",
        "engagement_action_opener_nudge": "{i}. Підказка opener (користувач {uid}, матч {mid})",
        "engagement_action_opener_suggestions": "{i}. Три тони opener для матчу {mid}",
        "engagement_action_revive": "{i}. Revive для матчу {mid}",
        "engagement_action_weak": "{i}. Слабкий матч — перерахунок сумісності (матч {mid})",
        "engagement_action_generic": "{i}. {atype} · матч {mid}",
        "engagement_safety_note": "<i>Лише підказки — адмін-бот нічого не надсилає користувачам.</i>",
        "engagement_ai_screen_intro": (
            "🤖 <b>AI</b>\n"
            "Обери пару нижче — отримаєш три лінії: light / flirty / deep (згенеровані AI, без тексту приватних чатів)."
        ),
        "engagement_targets_no_first": "Без повідомлень: {n} (показуємо {shown} цілей)",
        "engagement_targets_stale": "Застійні (тиша 3+ дн.): {n} (показуємо {shown})",
        "engagement_targets_snapshot": "Поточні цілі (імена)",
        "engagement_pair_line": "• {a} ↔ {b} · m{mid}",
        "engagement_last_active": "Остання активність: {when}",
        "engagement_btn_tones_short": "🎨 Тони",
        "engagement_btn_opener_short": "✨ Opener",
        "engagement_btn_revive_short": "💬 Revive",
        "engagement_btn_regenerate": "🔄 Ще варіант",
        "engagement_label_light": "<b>Light</b>",
        "engagement_label_flirty": "<b>Flirty</b>",
        "engagement_label_deep": "<b>Deep</b>",
        "engagement_tone_intro": "Три тони · m{mid} · {pair}",
        "engagement_opener_intro": "Opener · m{mid} · {pair}",
        "engagement_revive_intro": "Revive · m{mid} · {pair}",
        "engagement_ai_used": "Джерело: {src}",
        "engagement_ai_src_ai": "Gemini",
        "engagement_ai_src_template": "шаблон (fallback)",
        "engagement_generate_failed": "Не вдалося згенерувати. Спробуй ще раз.",
        "engagement_note_no_private": "Без вмісту приватних повідомлень — лише імена та час.",
        "engagement_btn_style_learning": "🧠 Стиль Chat Brain",
        "engagement_style_learning_title": "Навчання стилю Chat Brain",
        "engagement_style_learning_intro": "Лише агрегати: події та розподіли тонів (light / flirty / deep). Без тексту приватних повідомлень.",
        "engagement_style_period_line": "Період: {label}",
        "engagement_style_reply_rate": "Частка відповіді після підказки AI: {pct}",
        "engagement_style_sends": "Відправок з Brain: {n}",
        "engagement_style_replies": "Відповідей після Brain (спостереж.): {n}",
        "engagement_style_top_pick": "Найчастіший обраний стиль: {style}",
        "engagement_style_top_pick_none": "Найчастіший обраний стиль: —",
        "engagement_style_top_success": "Найуспішніший стиль (відповіді): {style}",
        "engagement_style_top_success_none": "Найуспішніший стиль: —",
        "engagement_style_dist_picks": "Розподіл обрань",
        "engagement_style_dist_replies": "Розподіл відповідей (оцінка стилю)",
        "engagement_style_aggregate_note": "Агреговані лічильники; без вмісту чатів.",
        "engagement_style_period_today": "Сьогодні",
        "engagement_style_period_7d": "7 дн.",
        "engagement_style_period_30d": "30 дн.",
        "telegram.demo.title": "🎭 Демо-режим",
        "telegram.demo.intro": "Чесний демо-режим: штучні профілі та симульовані чати. Вони не підміняють реальних людей і не мають потрапляти в «живі» метрики.",
        "telegram.demo.statusOn": "увімкнено",
        "telegram.demo.statusOff": "вимкнено",
        "telegram.demo.statusBody": "Статус: {on}\nДемо-профілі: {profiles}\nДемо-діалоги: {conversations}",
        "telegram.demo.enable": "Увімкнути демо-режим",
        "telegram.demo.disable": "Вимкнути демо-режим",
        "telegram.demo.regenerateProfiles": "Перегенерувати демо-профілі",
        "telegram.demo.clearConversations": "Очистити демо-переписки",
        "telegram.demo.back": "🔙 Назад",
        "telegram.demo.metrics": "Метрики",
        "telegram.demo.metricsTitle": "Метрики демо-режиму",
        "telegram.demo.liveStatusLine": "Жива поведінка (активна зараз): {on}",
        "telegram.demo.confirmEnable_html": "<b>🎭 Демо-режим</b>\n\nУвімкнути демо та показувати демо-профілі у стрічці? Це лише для демонстрації продукту.",
        "telegram.demo.confirmDisable_html": "<b>🎭 Демо-режим</b>\n\nВимкнути демо? Демо-профілі зникнуть зі стрічки для користувачів.",
        "telegram.demo.confirmRegenerate_html": "<b>🎭 Демо-режим</b>\n\nПерегенерувати демо-профілі? Існуючі демо-облікові записи будуть оновлені.",
        "telegram.demo.confirmClear_html": "<b>🎭 Демо-режим</b>\n\nОчистити демо-переписки (повідомлення, свайпи, матчі лише для демо-користувачів)?",
        "telegram.demo.behavior": "Жива поведінка демо",
        "telegram.demo.behaviorTitle": "Жива поведінка демо",
        "telegram.demo.behaviorIntro": "Імітація активності в чатах (затримки, інколи ігнор). Лише коли увімкнено демо-режим. Не ховаємо, що це симуляція.",
        "telegram.demo.behaviorBody": "Жива симуляція: {live}\nШвидкість відповіді: {speed}\nЙмовірність ігнору: {ignore}\nDEMO_LIVE_BEHAVIOR (env): {runner}\nЕфективно увімкнено: {effective}",
        "telegram.demo.liveOn": "Увімкнути живу симуляцію",
        "telegram.demo.liveOff": "Вимкнути живу симуляцію",
        "telegram.demo.speedFast": "Швидкість: швидко",
        "telegram.demo.speedNormal": "Швидкість: норма",
        "telegram.demo.speedSlow": "Швидкість: повільно",
        "telegram.demo.ignoreDown": "Ігнор −",
        "telegram.demo.ignoreUp": "Ігнор +",
        "telegram.demo.regenPersonalities": "Нові особистості демо",
        "telegram.demo.live.section": "Живий демо-режим",
        "telegram.demo.live.title": "Живий демо-режим",
        "telegram.demo.live.subtitle": "Імітація активності в чатах (затримки, інколи ігнор). Лише коли увімкнено демо-режим. Ми не приховуємо, що це симуляція.",
        "telegram.demo.live.status": "Жива симуляція: {live}\nШвидкість відповіді: {speed}\nЙмовірність ігнору: {ignore}\nDEMO_LIVE_BEHAVIOR (env): {runner}\nЕфективно увімкнено: {effective}",
        "telegram.demo.live.enabled": "увімкнено",
        "telegram.demo.live.disabled": "вимкнено",
        "telegram.demo.live.replySpeed": "Швидкість відповіді",
        "telegram.demo.live.ignoreRate": "Ймовірність ігнору",
        "telegram.demo.live.personalities": "Особистості демо",
        "telegram.demo.live.regeneratePersonalities": "Перегенерувати особистості",
        "telegram.demo.live.clearChats": "Очистити демо-чати",
        "telegram.demo.live.enable": "Увімкнути живу симуляцію",
        "telegram.demo.live.disable": "Вимкнути живу симуляцію",
        "telegram.demo.live.speedFast": "Швидкість: швидко",
        "telegram.demo.live.speedNormal": "Швидкість: норма",
        "telegram.demo.live.speedSlow": "Швидкість: повільно",
        "telegram.demo.live.ignoreDown": "Ігнор −",
        "telegram.demo.live.ignoreUp": "Ігнор +",
        "telegram.demo.live.metrics": "Метрики",
        "telegram.demo.live.back": "🔙 Назад",
        "telegram.demo.confirmLiveOn_html": "<b>🎭 Жива демо-поведінка</b>\n\nУвімкнути відкладені відповіді та фонову активність демо-профілів? Користувачі все одно бачать, що це симуляція.",
        "telegram.demo.confirmLiveOff_html": "<b>🎭 Жива демо-поведінка</b>\n\nВимкнути? Відповіді знову будуть миттєві (старий демо-чат), якщо писати демо-профілю.",
        "telegram.demo.confirmRegenPersonalities_html": "<b>🎭 Демо-профілі</b>\n\nПерегенерувати особистості (характер, швидкість, залученість) для всіх демо-профілів?",
        "telegram.route.ban_reason_too_short": "Причина занадто коротка. Надішли ще раз.",
        "telegram.route.ban_confirm_html": "<b>Підтвердження</b>\n\nЗабанити користувача {uid} з причиною:\n<pre>{reason}</pre>\nПродовжити?",
        "telegram.route.backup_phrase_mismatch_html": "Фраза не збігається. Введи точно:\n<code>{phrase}</code>",
        "telegram.route.backup_restore_confirm_html": "<b>🗄 Відновлення бекапу</b>\n\nФразу прийнято для:\n<code>{filename}</code>\n\nПідтвердити відновлення?",
        "telegram.route.release_version_required_html": "Потрібна версія. Формат:\n<pre>VERSION | NOTES</pre>",
        "telegram.route.release_mark_confirm_html": "<b>🚀 Позначити реліз</b>\n\nВерсія: <code>{version}</code>\nНотатки: {notes}\n\nЦе лише маркер у журналі. Підтвердити?",
        "telegram.route.promo_format_invalid": "Формат: CODE DAYS MAX_USES. Спробуй ще раз.",
        "telegram.route.promo_numbers_invalid": "DAYS і MAX_USES мають бути числами. Спробуй ще раз.",
        "telegram.route.promo_create_confirm_html": "<b>Підтвердження</b>\n\nСтворити промокод?\n<pre>{code} {days} {max_uses}</pre>",
        "no_data_available": "Немає даних.",
    },
    "en": {
        "main_title": "🧠 NEYRA AI Control Center",
        "command_center": "🧠 NEYRA Command Center",
        "command_center_more": "More…",
        "menu_ai": "🧠 AI Assistant",
        "menu_orders": "🛒 Orders",
        "menu_shipments": "📦 Shipments",
        "menu_analytics": "📊 Analytics",
        "menu_settings": "⚙️ Settings",
        "menu_diagnostics": "🧪 System Diagnostics",
        "product_home_hint": "Pick a section. The full admin map stays under <i>More…</i>.",
        "ai_hub_title": "🧠 AI Assistant",
        "ai_hub_intro": "Set <b>viewer</b> (NEYRA account that requests AI) and <b>partner</b> (matched user). Copy uses the real thread in the database.",
        "ai_set_viewer": "👤 Viewer ID",
        "ai_set_partner": "💬 Partner ID",
        "ai_get_suggestions": "💡 3 suggestions",
        "ai_new_suggestions": "🔄 New suggestions",
        "ai_improve": "✏️ Improve my text",
        "ai_meeting_check": "📅 Meeting ready",
        "ai_start_strategy_btn": "🚀 Start strategy",
        "ai_timed_now": "⏱ Timed: now",
        "ai_timed_reengage": "⏱ Timed: reengage",
        "ai_closer_hot": "🔥 This conversation is going well",
        "ai_keep_chatting": "💬 Keep chatting",
        "ai_pick_option": "Option {idx} selected — paste it in the app.",
        "ai_prompt_viewer": "<b>Viewer user ID</b>\n\nSend a numeric NEYRA user id.",
        "ai_prompt_partner": "<b>Partner user ID</b>\n\nSend the other user id in the pair.",
        "ai_prompt_improve": "<b>Improve text</b>\n\nSend your draft in one message.",
        "ai_need_pair": "Set viewer and partner first.",
        "orders_hub_title": "🛒 Orders & monetization",
        "orders_hub_intro": "Subscriptions, promos, and premium operations.",
        "shipments_hub_title": "📦 Shipments & delivery",
        "shipments_hub_intro": "Matches, engagement, and chat momentum.",
        "analytics_hub_title": "📊 Analytics",
        "analytics_hub_intro": "Product metric snapshots.",
        "settings_hub_title": "⚙️ Settings",
        "settings_hub_intro": "Bot language and system tools.",
        "diag_hub_title": "🧪 Product diagnostics",
        "diag_refresh": "🔄 Refresh",
        "alerts": "🚨 Alerts",
        "alerts_active": "Active alerts",
        "alerts_mute_1h": "Mute 1h",
        "alerts_unmute": "Unmute",
        "backup_center": "🗄 Backup Center",
        "backup_create": "Create backup",
        "backup_list": "List backups",
        "backup_export_latest": "Export latest backup",
        "backup_restore": "Restore backup",
        "backup_status_creating": "⏳ Creating backup...",
        "backup_status_created": "✅ Backup created",
        "backup_status_failed": "❌ Backup failed",
        "backup_field_file": "File",
        "backup_field_size": "Size",
        "backup_field_duration": "Duration",
        "audit_log": "🧾 Audit Log",
        "audit_last": "Last actions",
        "audit_premium": "Premium actions",
        "audit_user": "User actions",
        "audit_system": "System actions",
        "audit_safety": "Safety actions",
        "release_manager": "🚀 Release Manager",
        "release_readiness": "Readiness",
        "release_blockers": "Blockers",
        "release_warnings": "Warnings",
        "release_mark": "Mark release",
        "statistics": "📊 Statistics",
        "users": "👥 Users",
        "safety": "🛡 Safety",
        "system": "⚙️ System",
        "premium": "💎 Premium",
        "match_quality": "❤️ Match Quality",
        "conversation_quality": "💬 Conversation Quality",
        "engagement": "💬 Engagement",
        "growth": "📈 Growth",
        "product_manager": "🧭 Product Manager",
        "cto": "🧑‍💻 AI CTO",
        "menu_qa": "🧪 Menu QA",
        "e2e_qa": "🧪 E2E QA",
        "qa_agent": "🧪 QA Agent / Test Pilot",
        "full_product_qa": "🧪 Full Product QA",
        "full_product_qa_title": "🧪 Full Product QA",
        "full_product_qa_intro": "Одна кнопка → повна QA перевірка: система + UX + AI + продукт.\n\nНатисніть Run і отримаєте короткий пріоритезований звіт.",
        "full_product_qa_run": "🧪 Запустити Full Product QA",
        "full_product_qa_fix_top": "🔧 Fix Top Issues",
        "qa_agent_title": "🧪 QA Agent / Test Pilot",
        "qa_agent_intro": "Two-stage QA: first <b>perfect English UX</b>, then <b>full localization QA</b>.\n\nRecommended: 🇺🇸 English UX QA.",
        "qa_en": "🇺🇸 English UX QA",
        "qa_l10n": "🌍 Localization QA",
        "qa_chat": "💬 Chat QA",
        "qa_menu": "🧭 Menu QA",
        "qa_bot2bot": "🤖 Bot-to-bot QA",
        "qa_last": "📊 Last QA report",
        "qa_mode_summary": "📋 Summary",
        "qa_mode_fixes": "🔧 Fixes only",
        "qa_mode_deep": "🧠 Deep analysis",
        "qa_running": "⏳ Running QA…",
        "qa_disabled": "QA Agent is disabled. Set env: QA_AGENT_ENABLED=true",
        "qa_after_l10n": "⚠️ Run Localization QA only <b>after</b> Gemini localization.",
        "founder": "👑 Founder Mode",
        "founder_daily_plan": "Daily plan",
        "founder_alerts": "Alerts",
        "founder_focus": "Focus",
        "autopilot": "🤖 Autopilot",
        "autopilot_suggestions": "Suggestions",
        "autopilot_run_action": "Run action",
        "autopilot_empty": "No active suggestions.",
        "autopilot_are_you_sure": "Are you sure?",
        "back": "🔙 Back",
        "language": "🌐 Language / Мова",
        "choose_language": "<b>Choose admin bot language</b>\n\nYou can change it later via 🌐 Language / Мова.",
        "lang_uk": "🇺🇦 Українська",
        "lang_en": "🇬🇧 English",
        "refresh": "🔄 Refresh",
        "cancel": "❌ Cancel",
        "confirm": "✅ Confirm",
        "access_denied": "Access denied.",
        "unknown_action": "Unknown action.",
        "unknown_command": "Command not recognized. Use /menu.",
        "pick_section": "<b>NEYRA Admin AI Control Center</b>\n\nChoose a section:",
        "full_system_analysis": "🧠 Full System Analysis",
        "full_system_analysis_subtitle": "Fast DB/API/runtime metrics — not full browser QA.",
        "analysis_overall": "Overall status",
        "analysis_score": "Score",
        "analysis_owner_summary": "Owner summary",
        "analysis_top_issues": "Top issues",
        "analysis_top_recs": "Top recommendations",
        "analysis_next_actions": "Next best actions",
        "analysis_sections": "Section highlights",
        "ai_help": "🤖 AI Help",
        "full_analysis_create_backup": "📦 Create backup now",
        "menu_ai_quality": "🤖 AI Quality",
        "menu_localization_geo": "🌍 Localization / Geo",
        "menu_quick_stats": "📊 Statistics",
        "menu_quick_founder": "👑 Founder",
        "menu_quick_system": "⚙️ System",
        "status_critical": "🚨 Critical",
        "status_warning": "⚠️ Warning",
        "status_healthy": "✅ Healthy",
        "cc_status_label": "Status",
        "cc_today": "Today",
        "cc_users_line": "👥 users",
        "cc_active": "active",
        "cc_new": "new",
        "cc_matches": "❤️ matches",
        "cc_messages": "💬 messages",
        "cc_ai_calls": "🤖 AI calls",
        "cc_premium": "💎 premium",
        "cc_reports": "🛡 reports",
        "cc_top_priority": "🔥 Top priority",
        "cc_default_rec_title": "Grow daily active conversations",
        "cc_default_rec_reason": "No critical aggregate issues detected.",
        "cc_default_rec_action": "Open Founder Mode daily plan.",
        "alerts_push_title": "NEYRA Alert",
        "alerts_default_title": "Alert",
        "alerts_source": "Source",
        "alerts_action": "Action",
        "alerts_status_label": "Status",
        "alerts_status_active": "Active",
        "alerts_status_muted": "Muted",
        "alerts_none_active": "No active alerts.",
        "alerts_menu_line": "Status: {status}",
        "active_alert_line": "{idx}. {icon} <b>{title}</b>\n{message}\n{source_line}",
        "active_alert_source_line": "Source: {source}",
        "backup_choose_action": "Choose an action:",
        "backup_no_backups": "No backups found.",
        "backup_select_file": "Select a backup to restore:",
        "backup_restore_warn_intro": "⚠️ This will replace the current database from the backup:",
        "backup_restore_type_phrase": "Type exactly:",
        "backup_list_bytes": "{n} bytes",
        "audit_choose_view": "Choose a log view:",
        "audit_no_entries": "No entries.",
        "ai_help_title_prefix": "🤖 AI Help",
        "ai_help_what_is": "What this is:",
        "ai_help_watch": "What to watch:",
        "ai_help_do": "What to do:",
        "ai_help_risks": "Risks:",
        "ai_help_next": "Next best action:",
        "ai_help_bullet_empty": "• —",
        "ai_help_analysis_title": "🤖 AI Analysis",
        "ai_help_screen_shows": "What this screen shows",
        "ai_help_issues_block": "What may be wrong",
        "ai_help_next_steps": "What to do next",
        "ai_help_no_issues": "No critical issues flagged by rules; still review the signals above.",
        "render_error_generic": "This screen could not be loaded. Try refresh or go back.",
        "label_run_scan": "Run scan",
        "label_show_critical": "Critical",
        "label_warnings": "Warnings",
        "label_missing_translations": "Missing translations",
        "label_critical_issues": "Critical issues",
        "label_last_report": "Last report",
        "menu_qa_intro": "Admin bot menu QA (read-only).",
        "menu_qa_scan_line": "Menus: {menus} · Buttons: {buttons} · Callbacks: {callbacks}",
        "menu_qa_metrics_line": "Missing handlers: {mh} · Missing translations: {mt} · Unsafe: {unsafe} · Render errors: {rend}",
        "e2e_qa_intro": "Critical user flows QA (read-only by default).",
        "e2e_flows_line": "Flows: {flows} · Passed: {passed} · Warnings: {warn} · Failed: {failed}",
        "e2e_top_issues": "Top issues:",
        "period_today": "Today",
        "period_7d": "7 days",
        "period_30d": "30 days",
        "period_7d_short": "7d",
        "period_30d_short": "30d",
        "label_issues": "Issues",
        "label_recommendations": "Recommendations",
        "growth_issues_heading": "Issues (7 days):",
        "growth_recs_heading": "Recommendations (top 5):",
        "growth_choose_period": "Choose a period:",
        "pm_choose_brief": "Choose a brief:",
        "pm_daily_brief": "Daily brief",
        "pm_weekly_digest": "Weekly digest",
        "label_risks": "Risks",
        "label_next_actions": "Next actions",
        "pm_top_priority": "Top priority:",
        "pm_why": "Why:",
        "pm_action": "Action:",
        "pm_top3": "Top 3 priorities:",
        "pm_risks_heading": "Risks:",
        "pm_next_heading": "Next:",
        "pm_health_score": "Health score: {score}/100\n\n",
        "pm_brief_7d": "7d brief",
        "pm_brief_30d": "30d brief",
        "cto_choose_roadmap": "Choose a roadmap:",
        "cto_tech_risks": "Technical risks",
        "cto_next_dev": "Next dev actions",
        "cto_top_eng": "Top engineering priority:",
        "cto_reason": "Reason:",
        "cto_action": "Action:",
        "cto_top3": "Top 3 priorities:",
        "cto_debt": "Tech debt:",
        "cto_risks_heading": "Risks:",
        "cto_next_heading": "Next:",
        "cto_next_actions_heading": "Next dev actions:",
        "cto_risks_page_heading": "Technical risks:",
        "cto_health_score": "Technical health score: {score}/100",
        "json_truncated": "…(truncated)",
        "backup_api_invalid_response": "Invalid or empty backup API response",
        "backup_create_confirm_html": "<b>🗄 Backup Center</b>\n\nCreate a new database backup?",
        "release_mark_html": "<b>🚀 Mark release</b>\n\nSend one message:\n<pre>VERSION | NOTES</pre>\nExample:\n<pre>0.1.0 | Initial beta release</pre>",
        "confirm_l10n_fix_html": "<b>Confirm</b>\n\nRun safe localization auto-fix? This may create new empty locale files.\n\nContinue?",
        "confirm_lagent_fix_html": "<b>Confirm</b>\n\nRun safe <b>Localization Agent</b> auto-fix? (dev/staging only; fills keys from en, fixes raw keys and Latin city names in uk.json)\n\nContinue?",
        "confirm_backup_db_html": "<b>Confirm</b>\n\nCreate a database backup? (dev/non-prod)\n\nContinue?",
        "confirm_clear_cache_html": "<b>Confirm</b>\n\nClear cache (Redis flushdb)? (dev/non-prod)\n\nContinue?",
        "confirm_run_migrations_html": "<b>Confirm</b>\n\nRun Alembic migrations? (dev/non-prod)\n\nContinue?",
        "confirm_grant_premium_html": "<b>Confirm</b>\n\nGrant Premium for {days} days to user {uid}?",
        "confirm_revoke_premium_html": "<b>Confirm</b>\n\nRevoke Premium from user {uid}?",
        "confirm_memreset_html": "<b>Confirm</b>\n\nReset AI memory for user {uid}?",
        "ban_request_html": "<b>🚫 Ban user {uid}</b>\n\nSend the ban reason in one message.",
        "confirm_rep_dismiss_html": "<b>Confirm</b>\n\nDismiss report #{rid}?",
        "confirm_rep_ban_html": "<b>Confirm</b>\n\nResolve report #{rid} with action=ban (user {uid})?",
        "confirm_premium_grant_all_html": "<b>Confirm</b>\n\nGrant Premium to all dev users (example.com) for 30 days? (non-prod)\n\nContinue?",
        "confirm_match_recompute_html": "<b>Confirm</b>\n\nRun compatibility recompute (best-effort, no private chat content)?",
        "confirm_unban_html": "<b>Confirm</b>\n\nUnban user {uid}?",
        "toast_muted_1h": "Muted for 1 hour",
        "toast_unmuted": "Unmuted",
        "toast_ok": "OK",
        "toast_confirm_expired_retry": "Confirmation expired. Try again.",
        "toast_confirm_expired_short": "Confirmation expired.",
        "toast_executing": "Executing…",
        "toast_confirmation_expired_en": "Confirmation expired.",
        "toast_no_backups": "No backups",
        "toast_exporting": "Exporting…",
        "toast_restoring": "Restoring…",
        "toast_marking_release": "Marking release…",
        "toast_loading": "Loading…",
        "toast_scan_running": "Starting scan…",
        "toast_lagent_fix": "Running safe fix…",
        "toast_scan_short": "Scan…",
        "toast_safe_fix": "Safe fix…",
        "toast_backup_db": "Backing up DB…",
        "toast_clearing_cache": "Clearing cache…",
        "toast_running_migrations": "Running migrations…",
        "toast_not_wired": "Not wired yet (endpoint required).",
        "toast_grant_premium": "Granting Premium…",
        "toast_revoke_premium": "Revoking Premium…",
        "toast_reset_ai_memory": "Resetting AI memory…",
        "toast_unbanning": "Unbanning…",
        "toast_banning": "Banning…",
        "toast_dismissing": "Dismissing…",
        "toast_resolving_banning": "Resolving + ban…",
        "toast_granting": "Granting…",
        "toast_creating": "Creating…",
        "toast_recomputing": "Recomputing…",
        "l10n_fix_suggestions_title": "<b>📊 Fix suggestions</b>",
        "l10n_agent_missing_title": "<b>🌍 Localization Agent</b>\n\n<b>Missing keys</b>",
        "unban_confirm_title": "<b>Confirm</b>\n\nUnban user {uid}?",
        "backup_center_title_plain": "<b>🗄 Backup Center</b>\n\nCreate a new database backup? Allowed outside production.",
        "word_none": "None",
        "release_menu_intro": "Safe release checks and markers. No deploys are executed.",
        "release_readiness_heading": "🚀 Release readiness",
        "release_score_line": "Score: {score}/100",
        "release_status_line": "Status: {status}",
        "release_environment_line": "Environment: {env}",
        "release_recommended_actions": "Recommended actions",
        "release_checks": "Checks",
        "stats_title": "📊 NEYRA — {period}",
        "stats_users_line": "👥 Users: {total} / new {new_u} / active {active}",
        "stats_profiles_line": "✅ Profiles: done {done} · verified {verified}",
        "stats_dating_line": "❤️ Dating: likes {likes} · matches {matches}",
        "stats_messages_line": "💬 Messages: {messages} · active chats {active_chats} · dead chats {dead_chats}",
        "stats_ai_line": "🤖 AI: calls {calls} · errors {errors} · reply rate {reply_rate}",
        "stats_ai_partner_line": "↩️ Partner reply after AI: {partner_reply} · fallback {fallback}",
        "stats_premium_line": "💎 Premium: trials {trials} · premium {premium} · conversion {conversion}",
        "stats_safety_line": "🛡 Reports: open {open_r} · new {new_r} · banned {banned}",
        "system_doctor_title": "⚙️ System Doctor",
        "system_errors_24h": "⚠️ errors 24h: {n}",
        "system_fallback_24h": "⚠️ fallback 24h: {n}",
        "system_last_errors_title": "📄 Last errors",
        "ai_quality_title": "🤖 AI Quality",
        "ai_cache_clear": "🧹 Clear AI cache",
        "l10n_geo_title": "🌍 Localization / Geo",
        "l10n_coverage_title": "📊 Localization coverage",
        "l10n_coverage_no_rows": "<i>No locale rows</i>",
        "l10n_coverage_row": "{flag} <b>{label}</b> — unique {unique}% · present {present}%",
        "l10n_coverage_catalog": "\n\n<b>Catalog (non-EN):</b> missing={missing}, raw_leaks={raw}, en_fallback={fallback}",
        "l10n_btn_coverage": "📊 Coverage",
        "l10n_btn_agent": "🌍 Localization Agent",
        "l10n_agent_intro": (
            "<b>🌍 Localization Agent</b>\n\n"
            "Runtime i18n QC over <code>frontend/locales/*.json</code>. "
            "Scan is read-only. Safe fix fills missing keys from English and patches high-confidence placeholders "
            "(dev/staging only)."
        ),
        "l10n_agent_run_scan": "🔍 Run scan",
        "l10n_agent_safe_fix_btn": "🛠 Safe auto-fix",
        "l10n_agent_missing_btn": "🔑 Missing keys",
        "l10n_agent_cities_btn": "🏙 Bad city cases",
        "l10n_cov_top_missing": "🔑 Top missing",
        "l10n_cov_fix_suggestions": "🛠 Fix suggestions",
        "l10n_report_title": "<b>Localization report</b>",
        "l10n_top_missing_title": "<b>📊 Top missing keys</b> (by missing+empty)",
        "l10n_fix_suggestions_still_en": "<b>📊 Fix suggestions</b> (still English)",
        "l10n_agent_scan_result": "<b>🌍 Localization Agent</b>\n\n<b>Scan</b>\n",
        "l10n_agent_bad_cities_title": "<b>🌍 Localization Agent</b>\n\n<b>Bad city cases</b>\n",
        "l10n_agent_safe_fix_title": "<b>🌍 Localization Agent</b>\n\n<b>Safe fix</b>\n",
        "system_backup_db_title": "<b>🗄 Backup DB</b>",
        "system_clear_cache_title": "<b>🧹 Clear cache</b>",
        "system_run_migrations_title": "<b>🧬 Run migrations</b>",
        "system_backup_db_btn": "🗄 Backup DB",
        "system_clear_cache_btn": "🧹 Clear cache",
        "system_run_migrations_btn": "🧬 Run migrations",
        "result_backup_restored": "<b>🗄 Backup restored</b>",
        "result_release_marked": "<b>🚀 Release marked</b>",
        "result_premium_granted": "<b>💎 Premium granted</b>",
        "result_premium_revoked": "<b>❌ Premium revoked</b>",
        "result_ai_memory_reset": "<b>🧠 AI memory reset</b>",
        "result_unbanned": "<b>✅ Unbanned</b>",
        "result_banned": "<b>🚫 Banned</b>",
        "result_dismissed": "<b>✅ Dismissed</b>",
        "result_banned_resolved": "<b>🚫 Banned & resolved</b>",
        "result_grant_all_dev": "<b>💎 Grant all dev</b>",
        "result_promo_created": "<b>🎟 Promo created</b>",
        "result_recompute_done": "<b>❤️ Recompute done</b>",
        "mq_recompute_failed": "<b>❤️ Recompute failed</b>\n\nCould not complete the server request.",
        "safety_menu_intro": "Choose a section:",
        "safety_open_reports": "Open reports",
        "safety_resolved_reports": "Resolved reports",
        "premium_menu_intro": "Choose an action:",
        "premium_overview_title": "💎 Premium overview",
        "premium_expiring_title": "⏳ Expiring trials (3d)",
        "premium_grant_all_dev": "Grant premium all dev",
        "premium_create_promo": "Create promo code",
        "reports_title": "🛡 Reports",
        "reports_status": "Status",
        "reports_count": "Count",
        "report_detail_title": "🛡 Report detail",
        "report_open_reported": "👤 Open reported user",
        "report_dismiss": "✅ Dismiss",
        "report_ban_user": "🚫 Ban user",
        "mq_menu_intro": "Choose an action:",
        "mq_overview": "Overview",
        "mq_weak_matches": "Weak matches",
        "mq_dead_chats": "Dead chats",
        "mq_recompute": "Recompute compatibility",
        "mq_weak_title": "🩶 Weak matches (30d)",
        "mq_dead_title": "💤 Dead chats (no messages, 3d+)",
        "users_section_title": "👥 Users",
        "users_search_prompt": "Send a search query (email / name / id).",
        "users_query": "Query: {q}",
        "users_found": "Found: {n}",
        "users_new_search": "🔎 New search",
        "user_card_title": "👤 User",
        "user_grant_premium_7d": "💎 Grant premium 7d",
        "user_grant_premium_30d": "💎 Grant premium 30d",
        "user_revoke_premium": "❌ Revoke premium",
        "user_reset_ai_memory": "🧠 Reset AI memory",
        "user_ban": "🚫 Ban",
        "user_unban": "✅ Unban",
        "promo_create_title": "Create promo code",
        "promo_create_instructions": (
            "<b>Create promo code</b>\n\nSend one message:\n<pre>CODE DAYS MAX_USES</pre>\nExample: <pre>NEYRA_TEST 7 100</pre>"
        ),
        "section_stub": "<b>Section</b>: {key}\n\n(not connected yet)",
        "founder_north_star": "📈 <b>North Star:</b>\n{metric}: {value} ({trend})",
        "founder_today_heading": "🔥 <b>Today:</b>",
        "founder_no_priorities": "No priorities.",
        "founder_alerts_heading": "⚠️ <b>Alerts:</b>",
        "founder_no_alerts": "No alerts.",
        "founder_ns_default_metric": "Daily active conversations",
        "founder_ns_default_trend": "flat",
        "founder_focus_heading": "🎯 <b>Focus:</b>\n",
        "founder_default_focus": "Grow daily active conversations",
        "cq_choose_period": "Choose a period:",
        "cq_issues_heading": "Issues (7 days):",
        "cq_overview_ai_options": "AI options: {shown} shown / {selected} selected",
        "cq_overview_selection": "Selection: {sel} · Edited: {edited}",
        "cq_overview_partner_reply": "Partner reply rate: {rate}",
        "cq_overview_stalled": "Stalled chats: {stall} · Revive used: {revive}",
        "cq_overview_meeting": "Meeting: {suggested} suggested / {rejected} rejected",
        "cq_best_worst_style": "\nBest style: {best} · Worst style: {worst}",
        "cq_issues_prefix": "\n\nIssues: ",
        "growth_overview_new_active": "New users: {new_u} · Active: {active}",
        "growth_overview_profile": "Profile completion: {prof} · Photo added: {photo}",
        "growth_overview_first": "First match: {match} · First message: {msg}",
        "growth_overview_premium": "Premium conversion: {conv} · Paywall views: {views}",
        "growth_overview_referral_rewards": "Referral rewards: premium grants {grants} · abuse flags {flags}",
        "premium_overview_referral_line": "Referral rewards (30d): {grants} grants · {days} premium-days credited · abuse signals: {flags}",
        "growth_overview_locales": "Top locales: {locales}",
        "growth_overview_countries": "Top countries: {countries}",
        "growth_overview_top_recs": "\nTop recs: {recs}",
        "menu_qa_status": "Status:",
        "e2e_intro_alt": "Critical user flows QA (read-only by default).",
        "confirm_title_plain": "<b>Confirm</b>",
        "autopilot_action_clear_cache": "Clear Redis cache",
        "autopilot_action_run_migrations": "Run database migrations",
        "autopilot_action_recompute_matches": "Recompute match compatibility",
        "autopilot_action_localization_scan": "Run localization scan",
        "autopilot_tool_prefix": "🔧 ",
        "audit_total_code": "total={total}",
        "word_unknown": "unknown",
        "word_alert": "Alert",
        "word_priority": "Priority",
        "mq_overview_matches": "Matches: {total} · today {today}",
        "mq_overview_counts": "Weak: {weak} · dead chats {dead} · active chats {active}",
        "mq_overview_rates": "Reply rate: {reply} · mutual like rate: {mutual}",
        "mq_overview_ai": "AI match coverage: {cov} · avg score: {score}",
        "mq_overview_top_issues": "\nTop issues: {issues}",
        "release_ready": "Ready",
        "release_not_ready": "Not ready",
        "match_quality_title_plain": "❤️ Match Quality",
        "conversation_issues_label": "Issues:",
        "l10n_coverage_generated_at": "\n\n<code>generated_at</code>: {value}",
        "system_api_label": "API",
        "system_db_label": "DB",
        "system_redis_label": "Redis",
        "system_gemini_label": "Gemini",
        "engagement_menu_intro": "First-message and revive suggestions. Aggregate metrics and generated copy only — no private chat text.",
        "engagement_btn_overview": "Overview",
        "engagement_btn_suggested": "Suggested actions",
        "engagement_btn_revive": "Revive chats",
        "engagement_btn_first_boost": "First message boost",
        "engagement_btn_ai_suggestions": "🤖 AI suggestions",
        "engagement_first_rate": "First message rate: {pct}",
        "engagement_reply_rate": "Reply rate: {pct}",
        "engagement_dead_chats": "Dead chats (3d+, no messages): {n}",
        "engagement_chats_no_msg": "Matches with no messages: {n}",
        "engagement_stale_sample": "Stale in sample (3d+ silence): {n}",
        "engagement_avg_first": "Avg time to first message: {hours} h",
        "engagement_revive_success": "Revive success (30d analytics): {pct}",
        "engagement_issues_header": "⚠️ Issues:",
        "engagement_no_issues": "No aggregate issues flagged.",
        "engagement_issue_line_no_msg": "• {n} chat(s) with no messages",
        "engagement_issue_line_stale": "• {n} stale chat(s) (3d+ silence)",
        "engagement_actions_title": "🔥 Suggested actions:",
        "engagement_actions_empty": "No suggested actions right now.",
        "engagement_action_opener_nudge": "{i}. Opener nudge (user {uid}, match {mid})",
        "engagement_action_opener_suggestions": "{i}. Three opener tones for match {mid}",
        "engagement_action_revive": "{i}. Revive match {mid}",
        "engagement_action_weak": "{i}. Weak match — consider compatibility recompute ({mid})",
        "engagement_action_generic": "{i}. {atype} · match {mid}",
        "engagement_safety_note": "<i>Suggestions only — the admin bot never messages users.</i>",
        "engagement_ai_screen_intro": (
            "🤖 <b>AI</b>\n"
            "Pick a pair below — you get three lines: light / flirty / deep (AI-generated; no private chat text)."
        ),
        "engagement_targets_no_first": "No messages yet: {n} (showing {shown} targets)",
        "engagement_targets_stale": "Stale (3d+ silence): {n} (showing {shown})",
        "engagement_targets_snapshot": "Concrete targets (names)",
        "engagement_pair_line": "• {a} ↔ {b} · m{mid}",
        "engagement_last_active": "Last activity: {when}",
        "engagement_btn_tones_short": "🎨 Tones",
        "engagement_btn_opener_short": "✨ Opener",
        "engagement_btn_revive_short": "💬 Revive",
        "engagement_btn_regenerate": "🔄 Regenerate",
        "engagement_label_light": "<b>Light</b>",
        "engagement_label_flirty": "<b>Flirty</b>",
        "engagement_label_deep": "<b>Deep</b>",
        "engagement_tone_intro": "Three tones · m{mid} · {pair}",
        "engagement_opener_intro": "Opener · m{mid} · {pair}",
        "engagement_revive_intro": "Revive · m{mid} · {pair}",
        "engagement_ai_used": "Source: {src}",
        "engagement_ai_src_ai": "Gemini",
        "engagement_ai_src_template": "template fallback",
        "engagement_generate_failed": "Could not generate. Try again.",
        "engagement_note_no_private": "No private message bodies — names and timestamps only.",
        "engagement_btn_style_learning": "🧠 Chat Brain style",
        "engagement_style_learning_title": "Chat Brain style learning",
        "engagement_style_learning_intro": "Aggregate event counts and tone distributions (light / flirty / deep) only. No private message text.",
        "engagement_style_period_line": "Period: {label}",
        "engagement_style_reply_rate": "Reply-after-AI rate: {pct}",
        "engagement_style_sends": "Brain-assisted sends: {n}",
        "engagement_style_replies": "Follow-up replies observed: {n}",
        "engagement_style_top_pick": "Top picked style: {style}",
        "engagement_style_top_pick_none": "Top picked style: —",
        "engagement_style_top_success": "Top successful style (replies): {style}",
        "engagement_style_top_success_none": "Top successful style: —",
        "engagement_style_dist_picks": "Pick distribution",
        "engagement_style_dist_replies": "Reply distribution (inferred style)",
        "engagement_style_aggregate_note": "Aggregate counters only — no chat content.",
        "engagement_style_period_today": "Today",
        "engagement_style_period_7d": "7d",
        "engagement_style_period_30d": "30d",
        "telegram.demo.title": "🎭 Demo Mode",
        "telegram.demo.intro": "Honest demo mode: synthetic profiles and simulated chats. They are not real people and must not be counted as live growth.",
        "telegram.demo.statusOn": "on",
        "telegram.demo.statusOff": "off",
        "telegram.demo.statusBody": "Status: {on}\nDemo profiles: {profiles}\nDemo conversations: {conversations}",
        "telegram.demo.enable": "Enable demo mode",
        "telegram.demo.disable": "Disable demo mode",
        "telegram.demo.regenerateProfiles": "Regenerate demo profiles",
        "telegram.demo.clearConversations": "Clear demo conversations",
        "telegram.demo.back": "🔙 Back",
        "telegram.demo.metrics": "Metrics",
        "telegram.demo.metricsTitle": "Demo mode metrics",
        "telegram.demo.liveStatusLine": "Living behavior (effective now): {on}",
        "telegram.demo.confirmEnable_html": "<b>🎭 Demo Mode</b>\n\nEnable demo mode and show demo profiles in Discover? This is for product walkthroughs only.",
        "telegram.demo.confirmDisable_html": "<b>🎭 Demo Mode</b>\n\nDisable demo mode? Demo cards will stop appearing in user feeds.",
        "telegram.demo.confirmRegenerate_html": "<b>🎭 Demo Mode</b>\n\nRegenerate demo profiles? Existing demo accounts will be refreshed.",
        "telegram.demo.confirmClear_html": "<b>🎭 Demo Mode</b>\n\nClear demo conversations (messages/swipes/matches involving demo users only)?",
        "telegram.demo.behavior": "Living demo behavior",
        "telegram.demo.behaviorTitle": "Living demo behavior",
        "telegram.demo.behaviorIntro": "Simulates chat activity (delays, sometimes no reply). Only when demo mode is on. We never hide that this is a simulation.",
        "telegram.demo.behaviorBody": "Live simulation: {live}\nReply speed: {speed}\nIgnore rate: {ignore}\nDEMO_LIVE_BEHAVIOR (env): {runner}\nEffective (running): {effective}",
        "telegram.demo.liveOn": "Enable live simulation",
        "telegram.demo.liveOff": "Disable live simulation",
        "telegram.demo.speedFast": "Speed: fast",
        "telegram.demo.speedNormal": "Speed: normal",
        "telegram.demo.speedSlow": "Speed: slow",
        "telegram.demo.ignoreDown": "Ignore −",
        "telegram.demo.ignoreUp": "Ignore +",
        "telegram.demo.regenPersonalities": "Regenerate demo personalities",
        "telegram.demo.live.section": "Living demo mode",
        "telegram.demo.live.title": "Living demo mode",
        "telegram.demo.live.subtitle": "Simulates chat activity (delays, sometimes no reply). Only when demo mode is on. We never hide that this is a simulation.",
        "telegram.demo.live.status": "Live simulation: {live}\nReply speed: {speed}\nIgnore rate: {ignore}\nDEMO_LIVE_BEHAVIOR (env): {runner}\nEffective (running): {effective}",
        "telegram.demo.live.enabled": "enabled",
        "telegram.demo.live.disabled": "disabled",
        "telegram.demo.live.replySpeed": "Reply speed",
        "telegram.demo.live.ignoreRate": "Ignore rate",
        "telegram.demo.live.personalities": "Demo personalities",
        "telegram.demo.live.regeneratePersonalities": "Regenerate personalities",
        "telegram.demo.live.clearChats": "Clear demo chats",
        "telegram.demo.live.enable": "Enable live simulation",
        "telegram.demo.live.disable": "Disable live simulation",
        "telegram.demo.live.speedFast": "Speed: fast",
        "telegram.demo.live.speedNormal": "Speed: normal",
        "telegram.demo.live.speedSlow": "Speed: slow",
        "telegram.demo.live.ignoreDown": "Ignore −",
        "telegram.demo.live.ignoreUp": "Ignore +",
        "telegram.demo.live.metrics": "Metrics",
        "telegram.demo.live.back": "🔙 Back",
        "telegram.demo.confirmLiveOn_html": "<b>🎭 Living demo behavior</b>\n\nEnable delayed replies and background demo activity? Users still see clear demo / simulation labels.",
        "telegram.demo.confirmLiveOff_html": "<b>🎭 Living demo behavior</b>\n\nDisable? Replies become instant again (legacy demo chat) when messaging a demo profile.",
        "telegram.demo.confirmRegenPersonalities_html": "<b>🎭 Demo profiles</b>\n\nRegenerate personality traits (tone, speed, engagement) for all demo profiles?",
        "telegram.route.ban_reason_too_short": "Reason is too short. Send it again.",
        "telegram.route.ban_confirm_html": "<b>Confirmation</b>\n\nBan user {uid} with this reason:\n<pre>{reason}</pre>\nContinue?",
        "telegram.route.backup_phrase_mismatch_html": "Phrase mismatch. Type exactly:\n<code>{phrase}</code>",
        "telegram.route.backup_restore_confirm_html": "<b>🗄 Backup restore</b>\n\nTyped phrase accepted for:\n<code>{filename}</code>\n\nConfirm restore?",
        "telegram.route.release_version_required_html": "Version is required. Format:\n<pre>VERSION | NOTES</pre>",
        "telegram.route.release_mark_confirm_html": "<b>🚀 Mark release</b>\n\nVersion: <code>{version}</code>\nNotes: {notes}\n\nThis only logs a release marker. Confirm?",
        "telegram.route.promo_format_invalid": "Format: CODE DAYS MAX_USES. Try again.",
        "telegram.route.promo_numbers_invalid": "DAYS and MAX_USES must be numbers. Try again.",
        "telegram.route.promo_create_confirm_html": "<b>Confirmation</b>\n\nCreate promo code?\n<pre>{code} {days} {max_uses}</pre>",
        "no_data_available": "No data available.",
    },
}


def _get_lang(user_id: int) -> str:
    lang = str(admin_lang.get(int(user_id)) or "").strip().lower()
    if lang not in {"uk", "en"}:
        return "en"
    return lang


_i18n_missing_uk_logged: set[str] = set()
_i18n_missing_key_logged: set[str] = set()


def t(user_id: int, key: str, **kwargs: Any) -> str:
    """Resolve UI string for user locale; fall back to English; log gaps in non-production."""
    lang = _get_lang(user_id)
    en_map = STRINGS.get("en", {})
    loc_map = STRINGS.get(lang, {}) if lang in STRINGS else {}
    s = loc_map.get(key)
    if s is None or (isinstance(s, str) and not str(s).strip() and key in en_map):
        s = en_map.get(key)
        if lang == "uk" and key not in loc_map and key in en_map:
            if key not in _i18n_missing_uk_logged and _is_admin_dev_debug():
                _i18n_missing_uk_logged.add(key)
                _log(f"[i18n] missing uk key, fallback en: {key}")
        if s is None:
            if key not in _i18n_missing_key_logged and _is_admin_dev_debug():
                _i18n_missing_key_logged.add(key)
                _log(f"[i18n] missing key (no en): {key}")
            s = key
    out = str(s)
    if kwargs:
        try:
            out = out.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return out


def _is_admin_dev_debug() -> bool:
    env = str(os.getenv("ENV") or os.getenv("NEYRA_ENV") or os.getenv("APP_ENV") or "").strip().lower()
    return env not in {"production", "prod"}


def _admin_debug_log(msg: str) -> None:
    if _is_admin_dev_debug():
        _log(f"[admin_bot_debug] {msg}")


def _render_context_user_id(args: tuple[Any, ...], kwargs: dict[str, Any]) -> int:
    """Best-effort Telegram user id for localized fallback (avoid treating report_id as user_id)."""
    if kwargs.get("user_id") is not None:
        try:
            return int(kwargs["user_id"])
        except Exception:
            pass
    if args and isinstance(args[0], int) and args[0] >= 100_000_000:
        return int(args[0])
    return 0


def fallback_render_ui(user_id: int, message: str | None, back_callback: str = "m:home") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    msg = (message or "").strip() or t(uid, "no_data_available")
    kb: list[list[dict[str, str]]] = [[{"text": t(uid, "back"), "callback_data": str(back_callback or "m:home")[:64]}]]
    return f"<b>{escape(msg)}</b>", kb


def _ai_help_lang(user_id: int) -> str:
    return _get_lang(user_id) if _get_lang(user_id) in {"uk", "en"} else "en"


# Menu callback key (without m:) -> AI help section slug for POST /api/v1/admin/ai-help
AI_HELP_MENU_TO_SECTION: dict[str, str] = {
    "home": "command_center",
    "command_center": "command_center",
    "more": "more_menu",
    "lang": "command_center",
    "stats": "statistics",
    "stats_today": "statistics",
    "stats_7d": "statistics",
    "stats_30d": "statistics",
    "aiq": "ai_quality",
    "l10n": "localization",
    "l10n_agent": "localization",
    "l10n_coverage": "localization",
    "system": "system",
    "system_doctor": "system",
    "last_errors": "system",
    "users": "users",
    "safety": "safety",
    "reports_open": "safety",
    "reports_resolved": "safety",
    "premium": "premium",
    "premium_overview": "premium",
    "premium_expiring": "premium",
    "match_quality": "match_quality",
    "match_quality_overview": "match_quality",
    "match_quality_weak": "match_quality",
    "match_quality_dead": "match_quality",
    "conversation_quality": "conversation_quality",
    "conversation_quality_today": "conversation_quality",
    "conversation_quality_7d": "conversation_quality",
    "conversation_quality_30d": "conversation_quality",
    "conversation_quality_issues": "conversation_quality",
    "growth": "growth",
    "growth_today": "growth",
    "growth_7d": "growth",
    "growth_30d": "growth",
    "growth_recs": "growth",
    "engagement": "engagement",
    "engagement_overview": "engagement",
    "engagement_actions": "engagement",
    "engagement_revive": "engagement",
    "engagement_first_boost": "engagement",
    "engagement_ai_suggestions": "engagement",
    "engagement_style_learning": "engagement",
    "engagement_style_learning_today": "engagement",
    "engagement_style_learning_7d": "engagement",
    "engagement_style_learning_30d": "engagement",
    "pm": "product_manager",
    "pm_today": "product_manager",
    "pm_7d": "product_manager",
    "pm_30d": "product_manager",
    "pm_risks": "product_manager",
    "pm_next": "product_manager",
    "cto": "cto",
    "cto_today": "cto",
    "cto_7d": "cto",
    "cto_30d": "cto",
    "cto_risks": "cto",
    "cto_next": "cto",
    "menu_qa": "menu_qa",
    "menu_qa_run": "menu_qa",
    "menu_qa_critical": "menu_qa",
    "menu_qa_warnings": "menu_qa",
    "menu_qa_missing_tr": "menu_qa",
    "e2e_qa": "e2e_qa",
    "e2e_qa_run": "e2e_qa",
    "e2e_qa_critical": "e2e_qa",
    "e2e_qa_warnings": "e2e_qa",
    "e2e_qa_last": "e2e_qa",
    "founder": "founder",
    "founder_daily": "founder",
    "founder_alerts": "founder",
    "founder_focus": "founder",
    "demo": "demo_mode",
    "demo_metrics": "demo_mode",
    "demo_behavior": "demo_mode",
    "autopilot": "autopilot",
    "autopilot_suggestions": "autopilot",
    "autopilot_actions": "autopilot",
    "alerts": "alerts",
    "alerts_active": "alerts",
    "backups": "backup",
    "backups_list": "backup",
    "backups_restore": "backup",
    "audit": "audit",
    "audit_last": "audit",
    "audit_premium": "audit",
    "audit_user": "audit",
    "audit_system": "audit",
    "audit_safety": "audit",
    "release": "release",
    "release_readiness": "release",
    "release_blockers": "release",
    "release_warnings": "release",
    "full_analysis": "full_analysis",
}


def _inject_ai_help(kb: list[list[dict[str, str]]] | None, section: str, user_id: int, menu_key: str = "") -> list[list[dict[str, str]]]:
    """Add AI Help button; callback encodes section + menu key for correct back navigation."""
    if kb is None:
        kb = []
    if not isinstance(kb, list):
        return []
    sec = str(section or "").strip().lower()
    if not sec:
        return kb
    uid = int(user_id or 0)
    mk = str(menu_key or "").strip()
    cb = f"ai_help:{sec}~{mk}" if mk else f"ai_help:{sec}"
    if len(cb.encode("utf-8")) > 64:
        cb = f"ai_help:{sec}"
    for row in kb:
        if isinstance(row, list):
            for b in row:
                if isinstance(b, dict) and str(b.get("callback_data") or "").startswith(f"ai_help:{sec}"):
                    return kb
    return kb + [[{"text": t(uid, "ai_help"), "callback_data": cb}]]


def _render_ai_help(user_id: int, section: str, back_cb: str, refresh_callback_data: str) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    lang = _ai_help_lang(uid)
    data = backend.request("POST", "/api/v1/admin/ai-help", json_body={"section": section, "lang": lang})
    title = (data or {}).get("title") if isinstance(data, dict) else ""
    explanation = (data or {}).get("explanation") if isinstance(data, dict) else ""
    issues = (data or {}).get("issues") if isinstance(data, dict) else []
    suggestions = (data or {}).get("suggestions") if isinstance(data, dict) else []

    def bullet_lines(lines: list[Any]) -> str:
        out: list[str] = []
        if isinstance(lines, list):
            for x in lines[:14]:
                out.append(f"• {escape(str(x)[:650])}")
        return "\n".join(out) if out else t(uid, "ai_help_bullet_empty")

    header = escape(t(uid, "ai_help_analysis_title"))
    sub = escape(str(title or "").strip())
    text = f"<b>{header}</b>"
    if sub:
        text += f" — <i>{sub}</i>"
    text += "\n\n"
    text += f"<b>{escape(t(uid, 'ai_help_screen_shows'))}</b>\n{escape(str(explanation or '').strip() or t(uid, 'no_data_available'))}\n\n"
    text += f"<b>{escape(t(uid, 'ai_help_issues_block'))}</b>\n"
    if isinstance(issues, list) and issues:
        text += bullet_lines(issues) + "\n\n"
    else:
        text += escape(t(uid, "ai_help_no_issues")) + "\n\n"
    text += f"<b>{escape(t(uid, 'ai_help_next_steps'))}</b>\n{bullet_lines(suggestions if isinstance(suggestions, list) else [])}"

    refresh_cb = str(refresh_callback_data or "").strip() or (f"ai_help:{section}" if section else "m:home")
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": refresh_cb[:64]}],
        [{"text": t(uid, "back"), "callback_data": str(back_cb or "m:home")[:64]}],
    ]
    return text, kb

# -----------------------------
# UI / Routing
# -----------------------------


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_TELEGRAM_IDS


def main_menu(user_id: int) -> list[list[dict[str, str]]]:
    # callback_data max 64 bytes — keep it short.
    return [
        [{"text": t(user_id, "statistics"), "callback_data": "m:stats"}, {"text": t(user_id, "system"), "callback_data": "m:system"}],
        [{"text": t(user_id, "menu_ai_quality"), "callback_data": "m:aiq"}, {"text": t(user_id, "menu_localization_geo"), "callback_data": "m:l10n"}],
        [{"text": t(user_id, "safety"), "callback_data": "m:safety"}, {"text": t(user_id, "premium"), "callback_data": "m:premium"}],
        [{"text": t(user_id, "users"), "callback_data": "m:users"}, {"text": t(user_id, "growth"), "callback_data": "m:growth"}],
        [{"text": t(user_id, "match_quality"), "callback_data": "m:match_quality"}, {"text": t(user_id, "conversation_quality"), "callback_data": "m:conversation_quality"}],
        [{"text": t(user_id, "engagement"), "callback_data": "m:engagement"}],
        [{"text": t(user_id, "product_manager"), "callback_data": "m:pm"}],
        [{"text": t(user_id, "cto"), "callback_data": "m:cto"}],
        [{"text": t(user_id, "menu_qa"), "callback_data": "m:menu_qa"}],
        [{"text": t(user_id, "e2e_qa"), "callback_data": "m:e2e_qa"}],
        [{"text": t(user_id, "founder"), "callback_data": "m:founder"}],
        [{"text": t(user_id, "telegram.demo.title"), "callback_data": "m:demo"}],
        [{"text": t(user_id, "autopilot"), "callback_data": "m:autopilot"}],
        [{"text": t(user_id, "backup_center"), "callback_data": "m:backups"}],
        [{"text": t(user_id, "audit_log"), "callback_data": "m:audit"}],
        [{"text": t(user_id, "release_manager"), "callback_data": "m:release"}],
        [{"text": t(user_id, "alerts"), "callback_data": "m:alerts"}],
        [{"text": t(user_id, "language"), "callback_data": "m:lang"}],
        [{"text": t(user_id, "full_product_qa"), "callback_data": "m:full_product_qa_run"}],
        [{"text": "🧪 Deep Product QA", "callback_data": "m:deep_product_qa_run"}],
        [{"text": t(user_id, "full_system_analysis"), "callback_data": "m:full_analysis"}],
    ]


def back_btn(user_id: int, target: str = "home") -> list[list[dict[str, str]]]:
    return [[{"text": t(user_id, "back"), "callback_data": f"m:{target}"}]]


def fmt_json_block(user_id: int, obj: Any, max_len: int = 3000) -> str:
    s = json.dumps(obj, ensure_ascii=False, indent=2)
    if len(s) > max_len:
        suf = t(int(user_id or 0), "json_truncated")
        s = s[: max_len - len(suf) - 1] + "\n" + suf
    return f"<pre>{s}</pre>"


def _format_backup_size_bytes(n: Any) -> str:
    try:
        b = int(n)
    except Exception:
        return ""
    if b < 0:
        return ""
    if b < 1024:
        return f"{b} B"
    if b < 1024 * 1024:
        return f"{b / 1024.0:.1f} KB"
    return f"{b / (1024.0 * 1024.0):.1f} MB"


def _format_backup_create_error(exc: BaseException) -> str:
    if isinstance(exc, requests.HTTPError):
        resp = exc.response
        if resp is not None:
            try:
                body = resp.json()
            except Exception:
                return f"HTTP {resp.status_code}"
            if isinstance(body, dict):
                detail = body.get("detail")
                if isinstance(detail, dict):
                    err = detail.get("error") or detail.get("message")
                    sub = detail.get("detail")
                    if err and sub:
                        return f"{err}: {sub}"
                    if err:
                        return str(err)
                    if sub:
                        return str(sub)
                if isinstance(detail, list) and detail:
                    first = detail[0]
                    if isinstance(first, dict):
                        msg = first.get("msg") or first.get("message")
                        if msg:
                            return str(msg)
                    if isinstance(first, str):
                        return first
                if isinstance(detail, str):
                    return detail
            return f"HTTP {resp.status_code}"
    msg = str(exc).strip()
    return msg if msg else type(exc).__name__


def _tg_edit_or_send_fallback(
    chat_id: int,
    status_mid: int | None,
    text: str,
    keyboard: list[list[dict[str, str]]] | None,
) -> None:
    if status_mid is not None:
        try:
            tg_edit(chat_id, status_mid, text, keyboard)
            return
        except Exception:
            pass
    tg_send(chat_id, text, keyboard)


# Matches frontend/lib/i18n/locales.ts (admin coverage dashboard).
LOCALE_COVERAGE_FLAGS: dict[str, str] = {
    "en": "🇺🇸",
    "uk": "🇺🇦",
    "ru": "🇷🇺",
    "es": "🇪🇸",
    "pt": "🇵🇹",
    "fr": "🇫🇷",
    "de": "🇩🇪",
    "it": "🇮🇹",
    "pl": "🇵🇱",
    "tr": "🇹🇷",
    "zh": "🇨🇳",
    "zh-TW": "🇹🇼",
    "ja": "🇯🇵",
    "ko": "🇰🇷",
    "hi": "🇮🇳",
    "id": "🇮🇩",
    "vi": "🇻🇳",
    "th": "🇹🇭",
    "ar": "🇸🇦",
    "he": "🇮🇱",
    "nl": "🇳🇱",
    "sv": "🇸🇪",
    "cs": "🇨🇿",
    "ro": "🇷🇴",
    "hu": "🇭🇺",
    "el": "🇬🇷",
    "da": "🇩🇰",
    "fi": "🇫🇮",
    "no": "🇳🇴",
}


def _coverage_flag(code: str) -> str:
    return LOCALE_COVERAGE_FLAGS.get(code, "🌐")


def _coverage_code_label(code: str) -> str:
    if not code:
        return "??"
    if code == "en":
        return "EN"
    return code.upper()


def render_language_picker(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    text = t(user_id, "choose_language")
    kb = [
        [{"text": t(user_id, "lang_uk"), "callback_data": "x:lang:uk"}],
        [{"text": t(user_id, "lang_en"), "callback_data": "x:lang:en"}],
        [{"text": t(user_id, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def _command_center_status_label(user_id: int, status: str) -> str:
    s = str(status or "").strip().lower()
    if s == "critical":
        return t(user_id, "status_critical")
    if s == "warning":
        return t(user_id, "status_warning")
    return t(user_id, "status_healthy")


def _command_center_quick_menu(user_id: int) -> list[list[dict[str, str]]]:
    return [
        [{"text": t(user_id, "menu_quick_stats"), "callback_data": "m:stats"}, {"text": t(user_id, "menu_quick_founder"), "callback_data": "m:founder"}],
        [{"text": t(user_id, "menu_quick_system"), "callback_data": "m:system"}, {"text": t(user_id, "autopilot"), "callback_data": "m:autopilot"}],
        [{"text": t(user_id, "users"), "callback_data": "m:users"}, {"text": t(user_id, "safety"), "callback_data": "m:safety"}],
        [{"text": t(user_id, "alerts"), "callback_data": "m:alerts"}, {"text": t(user_id, "backup_center"), "callback_data": "m:backups"}],
        [{"text": t(user_id, "audit_log"), "callback_data": "m:audit"}, {"text": t(user_id, "release_manager"), "callback_data": "m:release"}],
        [{"text": t(user_id, "language"), "callback_data": "m:lang"}, {"text": t(user_id, "command_center_more"), "callback_data": "m:more"}],
    ]


def product_root_menu(user_id: int) -> list[list[dict[str, str]]]:
    uid = int(user_id or 0)
    return [
        [{"text": t(uid, "menu_ai"), "callback_data": "m:ai"}, {"text": t(uid, "menu_orders"), "callback_data": "m:orders"}],
        [{"text": t(uid, "menu_shipments"), "callback_data": "m:shipments"}, {"text": t(uid, "menu_analytics"), "callback_data": "m:analytics_hub"}],
        [{"text": t(uid, "menu_settings"), "callback_data": "m:settings_hub"}, {"text": t(uid, "menu_diagnostics"), "callback_data": "m:diag"}],
        [{"text": t(uid, "command_center_more"), "callback_data": "m:more"}],
    ]


def render_command_center_home(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    data = backend.request("GET", "/api/v1/admin/command-center/home")
    if not isinstance(data, dict):
        data = {}
    today = data.get("today") if isinstance(data.get("today"), dict) else {}
    rec = data.get("top_recommendation") if isinstance(data.get("top_recommendation"), dict) else {}
    title = str(rec.get("title") or t(user_id, "cc_default_rec_title"))
    reason = str(rec.get("reason") or t(user_id, "cc_default_rec_reason"))
    action = str(rec.get("action") or t(user_id, "cc_default_rec_action"))

    text = f"<b>{escape(t(user_id, 'command_center'))}</b>\n\n"
    text += f"{t(user_id, 'cc_status_label')}: {_command_center_status_label(user_id, str(data.get('status') or 'healthy'))}\n"
    text += f"{t(user_id, 'cc_today')}:\n"
    text += f"{t(user_id, 'cc_users_line')}: {int(today.get('active_users') or 0)} {t(user_id, 'cc_active')} / {int(today.get('new_users') or 0)} {t(user_id, 'cc_new')}\n"
    text += f"{t(user_id, 'cc_matches')}: {int(today.get('matches') or 0)}\n"
    text += f"{t(user_id, 'cc_messages')}: {int(today.get('messages') or 0)}\n"
    text += f"{t(user_id, 'cc_ai_calls')}: {int(today.get('ai_calls') or 0)}\n"
    text += f"{t(user_id, 'cc_premium')}: {int(today.get('premium_users') or 0)}\n"
    text += f"{t(user_id, 'cc_reports')}: {int(today.get('open_reports') or 0)}\n\n"
    text += f"{t(user_id, 'cc_top_priority')}:\n"
    text += f"<b>{escape(title)}</b>\n"
    text += f"{escape(reason)}\n"
    text += escape(action)
    text += f"\n\n{t(user_id, 'product_home_hint')}"
    return text, product_root_menu(user_id)


def render_more_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    return t(user_id, "pick_section"), main_menu(user_id)


def render_demo_mode_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    try:
        data = backend.request("GET", "/api/v1/admin/demo-mode")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    enabled = bool(data.get("enabled"))
    profiles = int(data.get("demo_profiles") or 0)
    convos = int(data.get("demo_conversations") or 0)
    title = escape(t(uid, "telegram.demo.title"))
    status_word = t(uid, "telegram.demo.statusOn") if enabled else t(uid, "telegram.demo.statusOff")
    intro = escape(t(uid, "telegram.demo.intro"))
    status_body = escape(t(uid, "telegram.demo.statusBody", on=status_word, profiles=profiles, conversations=convos))
    eff_on = bool(data.get("demo_live_effective"))
    live_line = escape(t(uid, "telegram.demo.liveStatusLine", on=t(uid, "telegram.demo.statusOn") if eff_on else t(uid, "telegram.demo.statusOff")))
    text = f"<b>{title}</b>\n\n{intro}\n\n{status_body}\n\n{live_line}"
    kb = [
        [{"text": t(uid, "telegram.demo.enable"), "callback_data": "c:demo_enable"}],
        [{"text": t(uid, "telegram.demo.disable"), "callback_data": "c:demo_disable"}],
        [{"text": t(uid, "telegram.demo.live.section"), "callback_data": "m:demo_behavior"}],
        [{"text": t(uid, "telegram.demo.regenerateProfiles"), "callback_data": "c:demo_regen"}],
        [{"text": t(uid, "telegram.demo.clearConversations"), "callback_data": "c:demo_clear"}],
        [{"text": t(uid, "telegram.demo.metrics"), "callback_data": "m:demo_metrics"}],
        [{"text": t(uid, "telegram.demo.back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_demo_behavior_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    try:
        data = backend.request("GET", "/api/v1/admin/demo-mode")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    lb = data.get("live_behavior") if isinstance(data.get("live_behavior"), dict) else {}
    live_on = bool(lb.get("enabled"))
    speed = str(lb.get("speed") or "normal")
    try:
        ign = float(lb.get("ignore_rate") or 0.3)
    except Exception:
        ign = 0.3
    title = escape(t(uid, "telegram.demo.live.title"))
    intro = escape(t(uid, "telegram.demo.live.subtitle"))
    live_word = t(uid, "telegram.demo.statusOn") if live_on else t(uid, "telegram.demo.statusOff")
    env_on = bool(data.get("demo_live_behavior_env"))
    eff_on = bool(data.get("demo_live_effective"))
    runner_word = t(uid, "telegram.demo.statusOn") if env_on else t(uid, "telegram.demo.statusOff")
    effective_word = t(uid, "telegram.demo.statusOn") if eff_on else t(uid, "telegram.demo.statusOff")
    status_body = escape(
        t(
            uid,
            "telegram.demo.live.status",
            live=live_word,
            speed=speed,
            ignore=f"{ign:.2f}",
            runner=runner_word,
            effective=effective_word,
        )
    )
    text = f"<b>{title}</b>\n\n{intro}\n\n{status_body}"
    kb = [
        [{"text": t(uid, "telegram.demo.live.enable"), "callback_data": "c:demo_live_enable"}],
        [{"text": t(uid, "telegram.demo.live.disable"), "callback_data": "c:demo_live_disable"}],
        [{"text": t(uid, "telegram.demo.live.speedFast"), "callback_data": "c:demo_speed_fast"}],
        [{"text": t(uid, "telegram.demo.live.speedNormal"), "callback_data": "c:demo_speed_normal"}],
        [{"text": t(uid, "telegram.demo.live.speedSlow"), "callback_data": "c:demo_speed_slow"}],
        [{"text": t(uid, "telegram.demo.live.ignoreDown"), "callback_data": "c:demo_ignore_down"}],
        [{"text": t(uid, "telegram.demo.live.ignoreUp"), "callback_data": "c:demo_ignore_up"}],
        [{"text": t(uid, "telegram.demo.live.regeneratePersonalities"), "callback_data": "c:demo_regen_personalities"}],
        [{"text": t(uid, "telegram.demo.live.clearChats"), "callback_data": "c:demo_clear"}],
        [{"text": t(uid, "telegram.demo.live.metrics"), "callback_data": "m:demo_metrics"}],
        [{"text": t(uid, "telegram.demo.live.back"), "callback_data": "m:demo"}],
    ]
    return text, kb


def render_demo_mode_metrics(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    try:
        data = backend.request("GET", "/api/v1/admin/demo-mode")
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    title = escape(t(uid, "telegram.demo.metricsTitle"))
    text = f"<b>{title}</b>\n\n" + fmt_json_block(uid, data, max_len=3500)
    kb = [[{"text": t(uid, "telegram.demo.back"), "callback_data": "m:demo"}]]
    return text, kb


def _full_analysis_status_label(user_id: int, status: str) -> str:
    s = str(status or "").strip().lower()
    if s == "critical":
        return t(user_id, "status_critical")
    if s == "warning":
        return t(user_id, "status_warning")
    return t(user_id, "status_healthy")


def render_full_system_analysis(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    data = backend.request("GET", "/api/v1/admin/system/full-analysis")
    if not isinstance(data, dict):
        data = {}
    title = t(user_id, "full_system_analysis")
    st = str(data.get("status") or "unknown")
    try:
        score_i = int(data.get("score"))
    except Exception:
        score_i = 0
    owner = str(data.get("owner_summary") or "")
    sections = data.get("sections") if isinstance(data.get("sections"), list) else []
    subtitle = str(t(user_id, "full_system_analysis_subtitle") or "").strip()
    lines = [
        f"<b>{escape(title)}</b>",
        escape(subtitle),
        "",
        f"<b>{escape(t(user_id, 'analysis_overall'))}</b>: {escape(_full_analysis_status_label(user_id, st))}",
        f"<b>{escape(t(user_id, 'analysis_score'))}</b>: {score_i}/100",
        "",
        f"<b>{escape(t(user_id, 'analysis_owner_summary'))}</b>",
        escape(owner[:900]),
        "",
        f"<b>{escape(t(user_id, 'analysis_sections'))}</b>",
    ]
    for sec in sections[:11]:
        if not isinstance(sec, dict):
            continue
        sid = str(sec.get("title") or sec.get("id") or "")
        st_sec = str(sec.get("status") or "")
        summ = str(sec.get("summary") or "")[:220]
        lines.append(f"• {escape(sid)} — {escape(st_sec)}: {escape(summ)}")
    lines.append("")
    lines.append(f"<b>{escape(t(user_id, 'analysis_top_issues'))}</b>")
    for it in (data.get("top_issues") or [])[:5]:
        lines.append(f"• {escape(str(it)[:200])}")
    lines.append("")
    lines.append(f"<b>{escape(t(user_id, 'analysis_top_recs'))}</b>")
    for it in (data.get("top_recommendations") or [])[:5]:
        lines.append(f"• {escape(str(it)[:200])}")
    lines.append("")
    lines.append(f"<b>{escape(t(user_id, 'analysis_next_actions'))}</b>")
    for it in (data.get("next_best_actions") or [])[:5]:
        lines.append(f"• {escape(str(it)[:200])}")
    text = "\n".join(lines)
    kb = []
    for qa in data.get("quick_actions") or []:
        if not isinstance(qa, dict):
            continue
        cb = str(qa.get("callback_data") or "").strip()
        if cb == "c:backup_create":
            kb.append([{"text": t(user_id, "full_analysis_create_backup"), "callback_data": "c:backup_create"}])
        elif cb == "m:match_quality_recompute":
            kb.append([{"text": t(user_id, "mq_recompute"), "callback_data": "m:match_quality_recompute"}])
    kb.extend(
        [
            [{"text": t(user_id, "refresh"), "callback_data": "m:full_analysis"}],
            [{"text": t(user_id, "back"), "callback_data": "m:more"}],
        ]
    )
    return text, kb


def render_home(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    return render_command_center_home(user_id)


def _alerts_poll_interval_s() -> int:
    env = str(os.getenv("ENV") or os.getenv("NEYRA_ENV") or os.getenv("APP_ENV") or "").strip().lower()
    return 15 * 60 if env in {"production", "prod"} else 5 * 60


def _alerts_muted(now: float | None = None) -> bool:
    return float(alerts_muted_until or 0.0) > float(now if now is not None else time.time())


def _alert_level_icon(level: str) -> str:
    lvl = str(level or "").strip().lower()
    if lvl == "critical":
        return "🚨"
    if lvl == "warning":
        return "⚠️"
    return "ℹ️"


def _safe_alert_callback(callback: Any) -> str:
    cb = str(callback or "").strip()
    if cb.startswith("m:") and len(cb.encode("utf-8")) <= 64:
        return cb
    return ""


def _fetch_admin_alerts() -> list[dict[str, Any]]:
    data = backend.request("GET", "/api/v1/admin/alerts/poll")
    alerts = data.get("alerts") if isinstance(data, dict) else None
    if not isinstance(alerts, list):
        alerts = []
    return [row for row in alerts if isinstance(row, dict)]


def _format_alert_message(alert: dict[str, Any], recipient_user_id: int) -> str:
    uid = int(recipient_user_id or 0)
    title = str(alert.get("title") or t(uid, "alerts_default_title"))
    message = str(alert.get("message") or "")
    source = str(alert.get("source") or "system").strip().upper()
    action = alert.get("action") if isinstance(alert.get("action"), dict) else {}
    action_label = str((action or {}).get("label") or "")
    text = f"{_alert_level_icon(str(alert.get('level') or 'info'))} <b>{escape(t(uid, 'alerts_push_title'))}</b>\n"
    text += f"{escape(title)}\n"
    if message:
        text += f"{escape(message)}\n"
    text += f"{t(uid, 'alerts_source')}: {escape(source)}"
    if action_label:
        text += f"\n{t(uid, 'alerts_action')}: {escape(action_label)}"
    return text


def render_alerts_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    now = time.time()
    status = t(user_id, "alerts_status_muted" if _alerts_muted(now) else "alerts_status_active")
    text = f"<b>{escape(t(user_id, 'alerts'))}</b>\n\n{t(user_id, 'alerts_menu_line', status=status)}"
    kb = [
        [{"text": t(user_id, "alerts_active"), "callback_data": "m:alerts_active"}],
        [{"text": t(user_id, "alerts_mute_1h"), "callback_data": "x:alerts_mute_1h"}, {"text": t(user_id, "alerts_unmute"), "callback_data": "x:alerts_unmute"}],
        [{"text": t(user_id, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_active_alerts(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    global active_alerts_cache
    rows = _fetch_admin_alerts()
    active_alerts_cache = rows
    title = escape(t(user_id, "alerts"))
    text = f"<b>{title}</b>\n\n"
    if not rows:
        text += t(user_id, "alerts_none_active")
    else:
        parts: list[str] = []
        for idx, alert in enumerate(rows[:10], 1):
            src = str(alert.get("source") or "system").upper()
            parts.append(
                t(
                    user_id,
                    "active_alert_line",
                    idx=idx,
                    icon=_alert_level_icon(str(alert.get("level") or "info")),
                    title=escape(str(alert.get("title") or t(user_id, "alerts_default_title"))),
                    message=escape(str(alert.get("message") or "")),
                    source_line=t(user_id, "active_alert_source_line", source=escape(src)),
                )
            )
        text += "\n\n".join(parts)
    kb: list[list[dict[str, str]]] = []
    for alert in rows[:5]:
        action = alert.get("action") if isinstance(alert.get("action"), dict) else {}
        cb = _safe_alert_callback((action or {}).get("callback"))
        label = str((action or {}).get("label") or "")
        if cb and label:
            kb.append([{"text": label[:48], "callback_data": cb}])
    kb.extend(
        [
            [{"text": t(user_id, "refresh"), "callback_data": "m:alerts_active"}],
            [{"text": t(user_id, "alerts_mute_1h"), "callback_data": "x:alerts_mute_1h"}, {"text": t(user_id, "alerts_unmute"), "callback_data": "x:alerts_unmute"}],
            [{"text": t(user_id, "back"), "callback_data": "m:alerts"}],
        ]
    )
    return text, kb


def poll_alerts_once(force: bool = False) -> list[dict[str, Any]]:
    global _alerts_last_poll_at, active_alerts_cache
    now = time.time()
    if not force and now - float(_alerts_last_poll_at or 0.0) < _alerts_poll_interval_s():
        return []
    _alerts_last_poll_at = now

    rows = _fetch_admin_alerts()
    active_alerts_cache = rows
    if _alerts_muted(now):
        return []

    for key, ts in list(sent_alert_dedupe.items()):
        if now - float(ts or 0.0) > _ALERT_NOTIFY_TTL_S:
            sent_alert_dedupe.pop(key, None)

    sent: list[dict[str, Any]] = []
    for alert in rows:
        key = str(alert.get("dedupe_key") or alert.get("id") or "").strip()
        if not key or key in sent_alert_dedupe:
            continue
        action = alert.get("action") if isinstance(alert.get("action"), dict) else {}
        cb = _safe_alert_callback((action or {}).get("callback"))
        label = str((action or {}).get("label") or "")
        kb = [[{"text": label[:48], "callback_data": cb}]] if cb and label else None
        sent_any = False
        for admin_id in sorted(ADMIN_TELEGRAM_IDS):
            try:
                tg_send(int(admin_id), _format_alert_message(alert, int(admin_id)), kb)
                sent_any = True
            except Exception:
                continue
        if sent_any:
            sent_alert_dedupe[key] = now
            sent.append(alert)
    return sent


def _backup_filename(value: Any) -> str:
    name = str(value or "").strip()
    if not name or "/" in name or "\\" in name or len(name.encode("utf-8")) > 48:
        return ""
    if not (name.endswith(".sqlite") or name.endswith(".db")):
        return ""
    return name


def _backup_rows() -> list[dict[str, Any]]:
    data = backend.request("GET", "/api/v1/admin/backups")
    return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []


def render_backup_center(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    text = f"<b>{escape(t(user_id, 'backup_center'))}</b>\n\n"
    text += t(user_id, "backup_choose_action")
    kb = [
        [{"text": t(user_id, "backup_create"), "callback_data": "c:backup_create"}],
        [{"text": t(user_id, "backup_list"), "callback_data": "m:backups_list"}],
        [{"text": t(user_id, "backup_export_latest"), "callback_data": "x:backup_export_latest"}],
        [{"text": t(user_id, "backup_restore"), "callback_data": "m:backups_restore"}],
        [{"text": t(user_id, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_backup_list(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    rows = _backup_rows()
    text = f"<b>{escape(t(user_id, 'backup_center'))}</b>\n\n"
    if not rows:
        text += t(user_id, "backup_no_backups")
    else:
        parts = []
        for idx, row in enumerate(rows[:10], 1):
            sz = int(row.get("size_bytes") or 0)
            parts.append(
                f"{idx}. <code>{escape(str(row.get('filename') or ''))}</code>\n"
                f"{t(user_id, 'backup_list_bytes', n=sz)} · {escape(str(row.get('created_at') or ''))}"
            )
        text += "\n\n".join(parts)
    return text, [[{"text": t(user_id, "refresh"), "callback_data": "m:backups_list"}], [{"text": t(user_id, "back"), "callback_data": "m:backups"}]]


def render_backup_restore_select(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    rows = _backup_rows()
    text = f"<b>{escape(t(user_id, 'backup_restore'))}</b>\n\n"
    if not rows:
        text += t(user_id, "backup_no_backups")
        return text, [[{"text": t(user_id, "back"), "callback_data": "m:backups"}]]
    text += t(user_id, "backup_select_file")
    kb = []
    for row in rows[:10]:
        name = _backup_filename(row.get("filename"))
        if not name:
            continue
        kb.append([{"text": name[:48], "callback_data": f"c:backup_restore:{name}"}])
    kb.append([{"text": t(user_id, "back"), "callback_data": "m:backups"}])
    return text, kb


def render_backup_restore_warning(user_id: int = 0, filename: str = "") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    safe_name = _backup_filename(filename)
    if not safe_name:
        return fallback_render_ui(uid, t(uid, "backup_no_backups"), "m:backups_restore")
    text = f"<b>{escape(t(uid, 'backup_restore'))}</b>\n\n"
    text += t(uid, "backup_restore_warn_intro") + "\n"
    text += f"<code>{escape(safe_name)}</code>\n\n"
    text += f"{t(uid, 'backup_restore_type_phrase')}\n<code>{BACKUP_RESTORE_PHRASE}</code>"
    return text, [[{"text": t(uid, "cancel"), "callback_data": "m:backups_restore"}]]


def _latest_backup_filename() -> str:
    rows = _backup_rows()
    if not rows:
        return ""
    return _backup_filename(rows[0].get("filename"))


def render_audit_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    text = f"<b>{escape(t(user_id, 'audit_log'))}</b>\n\n"
    text += t(user_id, "audit_choose_view")
    kb = [
        [{"text": t(user_id, "audit_last"), "callback_data": "m:audit_last"}],
        [{"text": t(user_id, "audit_premium"), "callback_data": "m:audit_premium"}, {"text": t(user_id, "audit_user"), "callback_data": "m:audit_user"}],
        [{"text": t(user_id, "audit_system"), "callback_data": "m:audit_system"}, {"text": t(user_id, "audit_safety"), "callback_data": "m:audit_safety"}],
        [{"text": t(user_id, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def _audit_view_filter(view: str) -> str:
    return {"premium": "premium", "user": "user", "system": "system", "safety": "safety"}.get(str(view or "").strip().lower(), "")


def render_audit_log(user_id: int = 0, view: str = "") -> tuple[str, list[list[dict[str, str]]]]:
    action_type = _audit_view_filter(view)
    path = "/api/v1/admin/audit-log?limit=20&offset=0"
    if action_type:
        path += f"&action_type={requests.utils.quote(action_type)}"
    data = backend.request("GET", path)
    rows = data.get("items") if isinstance(data, dict) else []
    items = rows if isinstance(rows, list) else []
    total = int((data or {}).get("total") or 0) if isinstance(data, dict) else 0
    title = t(user_id, "audit_log")
    if action_type:
        title = f"{title} · {action_type}"
    text = f"<b>{escape(title)}</b>\n<code>{t(user_id, 'audit_total_code', total=total)}</code>\n\n"
    if not items:
        text += t(user_id, "audit_no_entries")
    else:
        parts = []
        for row in items[:20]:
            created = str((row or {}).get("created_at") or "")
            short_time = created.replace("T", " ")[:19] if created else ""
            action = str((row or {}).get("action") or t(user_id, "word_unknown"))
            target_type = str((row or {}).get("target_type") or "")
            target_id = str((row or {}).get("target_id") or "")
            target = f"{target_type}:{target_id}" if target_id else target_type
            status = str((row or {}).get("status") or "")
            parts.append(
                f"<code>{escape(short_time)}</code>\n"
                f"{escape(action)}\n"
                f"{escape(target)} · {escape(status)}"
            )
        text += "\n\n".join(parts)
    suffix = f"_{action_type}" if action_type else "_last"
    kb = [
        [{"text": t(user_id, "refresh"), "callback_data": f"m:audit{suffix}"}],
        [{"text": t(user_id, "back"), "callback_data": "m:audit"}],
    ]
    return text, kb


def render_release_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    text = f"<b>{escape(t(user_id, 'release_manager'))}</b>\n\n"
    text += t(user_id, "release_menu_intro")
    kb = [
        [{"text": t(user_id, "release_readiness"), "callback_data": "m:release_readiness"}],
        [{"text": t(user_id, "release_blockers"), "callback_data": "m:release_blockers"}, {"text": t(user_id, "release_warnings"), "callback_data": "m:release_warnings"}],
        [{"text": t(user_id, "release_mark"), "callback_data": "c:release_mark"}],
        [{"text": t(user_id, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def _release_readiness() -> dict[str, Any]:
    data = backend.request("GET", "/api/v1/admin/release/readiness")
    return data if isinstance(data, dict) else {}


def render_release_readiness(user_id: int = 0, view: str = "summary") -> tuple[str, list[list[dict[str, str]]]]:
    data = _release_readiness()
    ready = bool(data.get("ready"))
    score = int(data.get("score") or 0)
    status = t(user_id, "release_ready" if ready else "release_not_ready")
    checks = data.get("checks") if isinstance(data.get("checks"), list) else []
    blockers = data.get("blockers") if isinstance(data.get("blockers"), list) else []
    warnings = data.get("warnings") if isinstance(data.get("warnings"), list) else []
    actions = data.get("recommended_actions") if isinstance(data.get("recommended_actions"), list) else []
    none = t(user_id, "word_none")

    text = f"<b>{escape(t(user_id, 'release_manager'))}</b>\n\n"
    text += f"{t(user_id, 'release_readiness_heading')}\n{t(user_id, 'release_score_line', score=score)}\n{t(user_id, 'release_status_line', status=status)}\n{t(user_id, 'release_environment_line', env=escape(str(data.get('environment') or '')))}\n\n"
    if view == "blockers":
        text += f"<b>{escape(t(user_id, 'release_blockers'))}</b>\n"
        text += "\n".join([f"- {escape(str(x))}" for x in blockers[:10]]) if blockers else none
    elif view == "warnings":
        text += f"<b>{escape(t(user_id, 'release_warnings'))}</b>\n"
        text += "\n".join([f"- {escape(str(x))}" for x in warnings[:10]]) if warnings else none
    else:
        text += f"<b>{escape(t(user_id, 'release_blockers'))}</b>\n"
        text += ("\n".join([f"- {escape(str(x))}" for x in blockers[:5]]) if blockers else none) + "\n\n"
        text += f"<b>{escape(t(user_id, 'release_warnings'))}</b>\n"
        text += ("\n".join([f"- {escape(str(x))}" for x in warnings[:5]]) if warnings else none) + "\n\n"
        text += f"<b>{escape(t(user_id, 'release_recommended_actions'))}</b>\n"
        text += "\n".join([f"- {escape(str(x))}" for x in actions[:5]]) if actions else none
        if checks:
            text += f"\n\n<b>{escape(t(user_id, 'release_checks'))}</b>\n"
            for row in checks[:8]:
                if not isinstance(row, dict):
                    continue
                text += f"{row.get('status', '')}: {escape(str(row.get('title') or ''))}\n"
    cb_view = view if view in {"blockers", "warnings"} else "readiness"
    kb = [
        [{"text": t(user_id, "refresh"), "callback_data": f"m:release_{cb_view}"}],
        [{"text": t(user_id, "release_blockers"), "callback_data": "m:release_blockers"}, {"text": t(user_id, "release_warnings"), "callback_data": "m:release_warnings"}],
        [{"text": t(user_id, "back"), "callback_data": "m:release"}],
    ]
    return text, kb



def render_ai_quality(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    raw = backend.request("GET", "/api/v1/admin/ai-quality")
    data = raw if isinstance(raw, dict) else {}
    summary = data.get("summary") if isinstance(data, dict) else None
    flags = data.get("quality_flags") if isinstance(data, dict) else None
    text = f"<b>{escape(t(uid, 'ai_quality_title'))}</b>\n"
    if summary:
        text += "\n" + fmt_json_block(uid, {"summary": summary, "quality_flags": flags or []})
    else:
        text += "\n" + fmt_json_block(uid, data)
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:aiq"}],
        [{"text": t(uid, "ai_cache_clear"), "callback_data": "x:ai_cache_clear"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_localization(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = backend.request("GET", "/api/v1/admin/localization-quality")
    text = f"<b>{escape(t(uid, 'l10n_geo_title'))}</b>\n"
    text += "\n" + fmt_json_block(uid, data)
    kb = [
        [{"text": t(uid, "l10n_btn_coverage"), "callback_data": "m:l10n_coverage"}],
        [{"text": t(uid, "l10n_btn_agent"), "callback_data": "m:l10n_agent"}],
        [{"text": t(uid, "label_run_scan"), "callback_data": "x:l10n_scan"}],
        [{"text": t(uid, "l10n_agent_safe_fix_btn"), "callback_data": "c:l10n_fix"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_localization_coverage(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    raw = backend.request("GET", "/api/v1/admin/localization/coverage")
    doc = raw if isinstance(raw, dict) else {}
    rows = [x for x in (doc.get("locales") or []) if isinstance(x, dict) and x.get("code") != "en"]
    rows.sort(key=lambda r: (float(r.get("coverage") or 0), str(r.get("code") or "")))
    lines: list[str] = []
    for r in rows:
        code = str(r.get("code") or "")
        flag = _coverage_flag(code)
        lab = _coverage_code_label(code)
        cov = int(r.get("coverage") or 0)
        pres = int(r.get("coverage_present_pct", cov) or 0)
        lines.append(t(uid, "l10n_coverage_row", flag=flag, label=escape(lab), unique=cov, present=pres))
    text = f"<b>{escape(t(uid, 'l10n_coverage_title'))}</b>\n\n"
    text += "\n".join(lines) if lines else t(uid, "l10n_coverage_no_rows")
    summ = doc.get("summary") if isinstance(doc.get("summary"), dict) else {}
    if summ:
        text += t(
            uid,
            "l10n_coverage_catalog",
            missing=int(summ.get("missing_keys_total") or 0),
            raw=int(summ.get("raw_value_leaks_total") or 0),
            fallback=int(summ.get("en_fallback_keys_total") or 0),
        )
    text += t(uid, "l10n_coverage_generated_at", value=escape(str(doc.get("generated_at") or "")))
    kb = [
        [{"text": t(uid, "l10n_cov_top_missing"), "callback_data": "x:l10n_cov_miss"}],
        [{"text": t(uid, "l10n_cov_fix_suggestions"), "callback_data": "x:l10n_cov_fix"}],
        [{"text": t(uid, "back"), "callback_data": "m:l10n"}],
    ]
    return text, kb


def _lagent_filtered_scan(scan: Any, issue_type: str, *, limit: int = 100) -> dict[str, Any]:
    issues = [i for i in (scan.get("issues") or []) if isinstance(i, dict) and i.get("type") == issue_type]
    return {
        "status": scan.get("status"),
        "summary": scan.get("summary"),
        "filter": issue_type,
        "count": len(issues),
        "issues": issues[:limit],
        "truncated": len(issues) > limit,
    }


def render_localization_agent(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = t(uid, "l10n_agent_intro")
    kb = [
        [{"text": t(uid, "l10n_agent_run_scan"), "callback_data": "x:lagent_scan"}],
        [{"text": t(uid, "l10n_agent_safe_fix_btn"), "callback_data": "c:lagent_fix"}],
        [{"text": t(uid, "l10n_agent_missing_btn"), "callback_data": "x:lagent_missing"}],
        [{"text": t(uid, "l10n_agent_cities_btn"), "callback_data": "x:lagent_cities"}],
        [{"text": t(uid, "back"), "callback_data": "m:l10n"}],
    ]
    return text, kb


def render_statistics(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    return render_statistics_period(user_id, "today")


def _period_label(user_id: int, p: str) -> str:
    uid = int(user_id or 0)
    if p == "today":
        return t(uid, "period_today")
    if p == "7d":
        return t(uid, "period_7d")
    return t(uid, "period_30d")


def render_statistics_period(user_id: int = 0, period: str = "today") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    p = period if period in {"today", "7d", "30d"} else "today"
    raw = backend.request("GET", f"/api/v1/admin/stats/overview?period={p}")
    data = raw if isinstance(raw, dict) else {}
    users = (data or {}).get("users") or {}
    dating = (data or {}).get("dating") or {}
    ai = (data or {}).get("ai") or {}
    prem = (data or {}).get("premium") or {}
    safety = (data or {}).get("safety") or {}

    def pct(x: float) -> str:
        return f"{round(float(x) * 100)}%"

    plab = _period_label(uid, p)
    text = f"<b>{escape(t(uid, 'stats_title', period=plab))}</b>\n\n"
    text += t(
        uid,
        "stats_users_line",
        total=users.get("total", 0),
        new_u=users.get("new", 0),
        active=users.get("active", 0),
    )
    text += "\n"
    text += t(uid, "stats_profiles_line", done=pct(users.get("completed_profiles_rate", 0)), verified=pct(users.get("verified_profiles_rate", 0)))
    text += "\n\n"
    text += t(uid, "stats_dating_line", likes=dating.get("likes", 0), matches=dating.get("matches", 0))
    text += "\n"
    text += t(
        uid,
        "stats_messages_line",
        messages=dating.get("messages", 0),
        active_chats=dating.get("active_chats", 0),
        dead_chats=dating.get("dead_chats", 0),
    )
    text += "\n\n"
    text += t(
        uid,
        "stats_ai_line",
        calls=ai.get("ai_calls", 0),
        errors=ai.get("gemini_errors", 0),
        reply_rate=pct(ai.get("reply_selected_rate", 0)),
    )
    text += "\n"
    text += t(
        uid,
        "stats_ai_partner_line",
        partner_reply=pct(ai.get("partner_reply_after_ai_rate", 0)),
        fallback=ai.get("fallback_count", 0),
    )
    text += "\n\n"
    text += t(
        uid,
        "stats_premium_line",
        trials=prem.get("trial_users", 0),
        premium=prem.get("premium_users", 0),
        conversion=pct(prem.get("conversion_rate", 0)),
    )
    text += "\n"
    text += t(
        uid,
        "stats_safety_line",
        open_r=safety.get("open_reports", 0),
        new_r=safety.get("new_reports", 0),
        banned=safety.get("banned_users", 0),
    )
    text += "\n"

    kb = [
        [{"text": t(uid, "period_today"), "callback_data": "m:stats_today"}, {"text": t(uid, "period_7d"), "callback_data": "m:stats_7d"}, {"text": t(uid, "period_30d"), "callback_data": "m:stats_30d"}],
        [{"text": t(uid, "refresh"), "callback_data": f"m:stats_{p}"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_system(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    raw = backend.request("GET", "/api/v1/admin/system-doctor")
    doc = raw if isinstance(raw, dict) else {}
    api_ok = doc.get("api_status") == "ok"
    db_ok = doc.get("database_status") == "ok"
    redis_ok = doc.get("redis_status") == "ok"
    gem_ok = doc.get("gemini_status") == "ok"
    errs24 = int(doc.get("api_errors_24h") or 0)
    fb24 = int(doc.get("ai_fallback_count_24h") or 0)
    ai_op = str(doc.get("ai_operational_status") or "").strip().upper() or "—"
    ai_fb = doc.get("ai_fallback_active")
    ai_fb_eng = doc.get("ai_fallback_engine_verified")
    gem_layer = doc.get("gemini_provider_layer") or "—"
    sug = str(doc.get("system_doctor_suggested_action") or "").strip()
    last_pe = doc.get("last_provider_errors") if isinstance(doc.get("last_provider_errors"), list) else []

    def mark(v: bool) -> str:
        return "✅" if v else "❌"

    text = f"<b>{escape(t(uid, 'system_doctor_title'))}</b>\n\n"
    text += f"{mark(api_ok)} {t(uid, 'system_api_label')}\n{mark(db_ok)} {t(uid, 'system_db_label')}\n{mark(redis_ok)} {t(uid, 'system_redis_label')}\n{mark(gem_ok)} {t(uid, 'system_gemini_label')}\n"
    text += f"\n<b>AI</b>: {escape(ai_op)} · <b>Fallback</b>: {'ACTIVE' if ai_fb else 'OFF'} · <b>Fallback engine</b>: {'OK' if ai_fb_eng else '?'}\n"
    text += f"<b>Provider layer</b>: {escape(str(gem_layer))}\n"
    text += f"\n{t(uid, 'system_errors_24h', n=errs24)}\n{t(uid, 'system_fallback_24h', n=fb24)}\n"
    if sug:
        text += f"\n<b>Suggested</b>: {escape(sug[:900])}\n"
    if last_pe:
        text += "\n<b>Last provider errors</b>\n"
        for row in last_pe[:5]:
            if not isinstance(row, dict):
                continue
            cls = escape(str(row.get('classification') or ''))
            cnt = int(row.get('count') or 0)
            ep = escape(str(row.get('endpoint') or ''))
            msg = escape(str(row.get('message') or '')[:240])
            text += f"• {cls} ({cnt}) {ep}\n<pre>{msg}</pre>\n"
    text += f"\n<pre>{json.dumps({'env': doc.get('environment'), 'uptime_s': doc.get('uptime_seconds'), 'alembic': doc.get('alembic_revision')}, ensure_ascii=False)}</pre>"

    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:system_doctor"}],
        [{"text": t(uid, "system_backup_db_btn"), "callback_data": "c:backup_db"}, {"text": t(uid, "system_clear_cache_btn"), "callback_data": "c:clear_cache"}],
        [{"text": t(uid, "system_run_migrations_btn"), "callback_data": "c:run_migrations"}, {"text": t(uid, "system_last_errors_title"), "callback_data": "m:last_errors"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_last_errors(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    raw = backend.request("GET", "/api/v1/admin/system-doctor")
    doc = raw if isinstance(raw, dict) else {}
    text = f"<b>{escape(t(uid, 'system_last_errors_title'))}</b>\n\n" + fmt_json_block(uid, doc.get("last_10_errors") or [])
    return text, [[{"text": t(uid, "back"), "callback_data": "m:system_doctor"}]]


AUTOPILOT_ACTIONS: dict[str, dict[str, str]] = {
    "clear_cache": {"title_key": "autopilot_action_clear_cache", "impact": "medium", "risk": "low"},
    "run_migrations": {"title_key": "autopilot_action_run_migrations", "impact": "high", "risk": "medium"},
    "recompute_matches": {"title_key": "autopilot_action_recompute_matches", "impact": "high", "risk": "low"},
    "localization_scan": {"title_key": "autopilot_action_localization_scan", "impact": "medium", "risk": "low"},
}


def _autopilot_suggestions() -> list[dict[str, Any]]:
    data = backend.request("GET", "/api/v1/admin/autopilot/suggestions")
    rows = (data or {}).get("suggestions") if isinstance(data, dict) else []
    return rows if isinstance(rows, list) else []


def _autopilot_action_label(user_id: int, action_id: str) -> str:
    meta = AUTOPILOT_ACTIONS.get(action_id) or {}
    key = str(meta.get("title_key") or "").strip()
    if key:
        return t(int(user_id or 0), key)
    return action_id.replace("_", " ").title()


def _autopilot_find_suggestion(action_id: str) -> dict[str, Any]:
    for row in _autopilot_suggestions():
        if isinstance(row, dict) and str(row.get("id") or "") == action_id:
            return row
    return {}


def render_autopilot_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    text = f"<b>{t(user_id, 'autopilot')}</b>"
    kb = [
        [{"text": t(user_id, "autopilot_suggestions"), "callback_data": "m:autopilot_suggestions"}],
        [{"text": t(user_id, "autopilot_run_action"), "callback_data": "m:autopilot_actions"}],
        [{"text": t(user_id, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_autopilot_suggestions(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    rows = _autopilot_suggestions()
    text = f"<b>{t(user_id, 'autopilot')}</b>\n\n"
    kb: list[list[dict[str, str]]] = []
    if not rows:
        text += escape(t(user_id, "autopilot_empty"))
    for row in rows[:10]:
        if not isinstance(row, dict):
            continue
        action_id = str(row.get("id") or "").strip()
        if not action_id:
            continue
        title = str(row.get("title") or _autopilot_action_label(user_id, action_id))
        reason = str(row.get("reason") or "")
        impact = str(row.get("impact") or "")
        risk = str(row.get("risk") or "")
        text += f"🔧 <b>{escape(title)}</b>\n"
        if reason:
            text += f"{escape(reason)}\n"
        text += f"{escape(impact)} / {escape(risk)}\n\n"
        kb.append([{"text": f"🔧 {title[:48]}", "callback_data": f"c:auto:{action_id}"}])
    kb.extend(
        [
            [{"text": t(user_id, "refresh"), "callback_data": "m:autopilot_suggestions"}],
            [{"text": t(user_id, "autopilot_run_action"), "callback_data": "m:autopilot_actions"}],
            [{"text": t(user_id, "back"), "callback_data": "m:autopilot"}],
        ]
    )
    return text, kb


def render_autopilot_actions(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    text = f"<b>{t(user_id, 'autopilot')}</b>\n\n{escape(t(user_id, 'autopilot_run_action'))}:"
    kb = [
        [{"text": f"{t(user_id, 'autopilot_tool_prefix')}{_autopilot_action_label(user_id, action_id)}", "callback_data": f"c:auto:{action_id}"}]
        for action_id, meta in AUTOPILOT_ACTIONS.items()
    ]
    kb.append([{"text": t(user_id, "back"), "callback_data": "m:autopilot"}])
    return text, kb


def render_autopilot_confirm(user_id: int = 0, action_id: str = "") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    action_id = str(action_id or "").strip()
    if not action_id or action_id not in AUTOPILOT_ACTIONS:
        return fallback_render_ui(uid, t(uid, "unknown_action"), "m:autopilot")
    suggestion = _autopilot_find_suggestion(action_id)
    title = str(suggestion.get("title") or _autopilot_action_label(user_id, action_id))
    reason = str(suggestion.get("reason") or "")
    impact = str(suggestion.get("impact") or AUTOPILOT_ACTIONS.get(action_id, {}).get("impact") or "")
    risk = str(suggestion.get("risk") or AUTOPILOT_ACTIONS.get(action_id, {}).get("risk") or "")
    text = f"<b>{t(user_id, 'autopilot')}</b>\n\n{escape(t(user_id, 'autopilot_are_you_sure'))}\n\n"
    text += f"🔧 <b>{escape(title)}</b>\n"
    if reason:
        text += f"{escape(reason)}\n"
    if impact or risk:
        text += f"{escape(impact)} / {escape(risk)}"
    kb = [[{"text": t(user_id, "confirm"), "callback_data": f"x:auto:{action_id}"}, {"text": t(user_id, "cancel"), "callback_data": "m:autopilot"}]]
    return text, kb


def _founder_daily() -> dict[str, Any]:
    data = backend.request("GET", "/api/v1/admin/founder/daily")
    return data if isinstance(data, dict) else {}


def _founder_menu_kb(user_id: int) -> list[list[dict[str, str]]]:
    return [
        [{"text": t(user_id, "founder_daily_plan"), "callback_data": "m:founder_daily"}],
        [{"text": t(user_id, "founder_alerts"), "callback_data": "m:founder_alerts"}, {"text": t(user_id, "founder_focus"), "callback_data": "m:founder_focus"}],
        [{"text": t(user_id, "back"), "callback_data": "m:home"}],
    ]


def render_founder_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    return f"<b>{t(user_id, 'founder')}</b>", _founder_menu_kb(user_id)


def _render_founder_north_star(user_id: int, data: dict[str, Any]) -> str:
    uid = int(user_id or 0)
    ns = data.get("north_star") if isinstance(data, dict) else {}
    metric = escape(str((ns or {}).get("metric") or t(uid, "founder_ns_default_metric")))
    value = escape(str((ns or {}).get("value") or 0))
    trend = escape(str((ns or {}).get("trend") or t(uid, "founder_ns_default_trend")))
    return t(uid, "founder_north_star", metric=metric, value=value, trend=trend)


def render_founder_daily(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = _founder_daily()
    text = f"<b>{t(uid, 'founder')}</b>\n\n{_render_founder_north_star(uid, data)}\n\n"
    plan = data.get("today_plan") if isinstance(data, dict) else []
    text += t(uid, "founder_today_heading") + "\n"
    rows = plan if isinstance(plan, list) else []
    if not rows:
        text += t(uid, "founder_no_priorities") + "\n"
    for row in rows[:5]:
        if not isinstance(row, dict):
            continue
        idx = int(row.get("priority") or (len(rows) + 1))
        title = escape(str(row.get("title") or t(uid, "word_priority")))
        reason = escape(str(row.get("reason") or ""))
        text += f"{idx}. {title}"
        if reason:
            text += f" ({reason[:80]})"
        text += "\n"

    alerts = data.get("alerts") if isinstance(data, dict) else []
    alert_rows = alerts if isinstance(alerts, list) else []
    if alert_rows:
        text += "\n" + t(uid, "founder_alerts_heading") + "\n"
        for alert in alert_rows[:4]:
            if isinstance(alert, dict):
                text += f"- {escape(str(alert.get('message') or t(uid, 'word_alert')))}\n"

    focus = escape(str(data.get("focus") or "")) if isinstance(data, dict) else ""
    if focus:
        text += "\n" + t(uid, "founder_focus_heading") + f"{focus}"

    kb = [
        [{"text": t(user_id, "refresh"), "callback_data": "m:founder_daily"}],
        [{"text": t(user_id, "founder_alerts"), "callback_data": "m:founder_alerts"}, {"text": t(user_id, "founder_focus"), "callback_data": "m:founder_focus"}],
        [{"text": t(user_id, "back"), "callback_data": "m:founder"}],
    ]
    return text, kb


def render_founder_alerts(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = _founder_daily()
    alerts = data.get("alerts") if isinstance(data, dict) else []
    rows = alerts if isinstance(alerts, list) else []
    text = f"<b>{t(uid, 'founder')}</b>\n\n⚠️ <b>{t(uid, 'founder_alerts')}</b>\n\n"
    if not rows:
        text += t(uid, "founder_no_alerts")
    for alert in rows[:8]:
        if not isinstance(alert, dict):
            continue
        level = escape(str(alert.get("level") or "warning"))
        message = escape(str(alert.get("message") or t(uid, "word_alert")))
        fix = escape(str(alert.get("suggested_fix") or ""))
        text += f"- <b>{level}</b>: {message}"
        if fix:
            text += f"\n  {fix}"
        text += "\n"
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:founder_alerts"}],
        [{"text": t(uid, "back"), "callback_data": "m:founder"}],
    ]
    return text, kb


def render_founder_focus(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = _founder_daily()
    focus = escape(str(data.get("focus") or t(uid, "founder_default_focus"))) if isinstance(data, dict) else escape(t(uid, "founder_default_focus"))
    text = f"<b>{t(uid, 'founder')}</b>\n\n🎯 <b>{t(uid, 'founder_focus')}</b>\n\n{focus}\n\n{_render_founder_north_star(uid, data)}"
    kb = [
        [{"text": t(user_id, "refresh"), "callback_data": "m:founder_focus"}],
        [{"text": t(user_id, "back"), "callback_data": "m:founder"}],
    ]
    return text, kb


# Confirmation state (in-memory, owner-only).
pending_confirms: dict[str, dict[str, Any]] = {}
pending_inputs: dict[str, dict[str, Any]] = {}
TG_AI_CTX: dict[str, dict[str, Any]] = {}

# Inline callback error copy (must stay ASCII-safe for Telegram HTML elsewhere).
TG_CALLBACK_FALLBACK_MSG = "⚠️ Something went wrong, try again"


def _safe_app_user_id(val: Any) -> int | None:
    """Finite positive app user id for viewer/partner context; None if missing or invalid."""
    if val is None or isinstance(val, bool):
        return None
    try:
        n = int(val)
    except (TypeError, ValueError, OverflowError):
        return None
    if n < 1 or n > 2_147_483_647:
        return None
    return n


def _log_callback_exception(callback_data: str) -> None:
    _log(f"[telegram_callback] callback_data={callback_data!r}\n{traceback.format_exc()}")


def confirm_key(chat_id: int, user_id: int, action: str) -> str:
    return f"{chat_id}:{user_id}:{action}"


def set_confirm(chat_id: int, user_id: int, action: str, payload: dict[str, Any]) -> None:
    pending_confirms[confirm_key(chat_id, user_id, action)] = {"ts": time.time(), "payload": payload}


def pop_confirm(chat_id: int, user_id: int, action: str) -> dict[str, Any] | None:
    return pending_confirms.pop(confirm_key(chat_id, user_id, action), None)


def input_key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}"


def set_input(chat_id: int, user_id: int, mode: str, payload: dict[str, Any]) -> None:
    pending_inputs[input_key(chat_id, user_id)] = {"mode": mode, "payload": payload, "ts": time.time()}


def pop_input(chat_id: int, user_id: int) -> dict[str, Any] | None:
    return pending_inputs.pop(input_key(chat_id, user_id), None)


def _tg_ctx_key(chat_id: int, user_id: int) -> str:
    return f"{int(chat_id)}:{int(user_id)}"


def ai_ctx_get(chat_id: int, user_id: int) -> dict[str, Any]:
    return TG_AI_CTX.get(_tg_ctx_key(chat_id, user_id)) or {}


def ai_ctx_set(chat_id: int, user_id: int, **kwargs: Any) -> None:
    k = _tg_ctx_key(chat_id, user_id)
    cur = dict(TG_AI_CTX.get(k) or {})
    cur.update(kwargs)
    TG_AI_CTX[k] = cur


def telegram_track(name: str, *, telegram_user_id: int, viewer_user_id: int | None = None, payload: dict[str, Any] | None = None) -> None:
    try:
        backend.request(
            "POST",
            "/api/v1/admin/telegram/analytics/track",
            json_body={
                "name": name,
                "user_id": viewer_user_id,
                "telegram_admin_id": int(telegram_user_id),
                "payload": payload or {},
            },
        )
    except Exception:
        pass


def _extract_copilot_texts(payload: dict[str, Any]) -> tuple[list[str], bool, bool]:
    opts = payload.get("options") if isinstance(payload.get("options"), list) else []
    texts: list[str] = []
    for o in opts[:3]:
        if isinstance(o, dict):
            texts.append(str(o.get("text") or "").strip())
    limited = bool(payload.get("limited"))
    fb = bool(payload.get("fallback"))
    return texts, limited, fb


def _fmt_diag_line(line: str) -> str:
    s = str(line or "").strip()
    if len(s) > 350:
        return escape(s[:350]) + "…"
    return escape(s)


def render_ai_hub(user_id: int = 0, telegram_chat_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    cid = int(telegram_chat_id or 0)
    ctx = ai_ctx_get(cid, uid) if cid else {}
    vu = int(ctx.get("viewer_uid") or 0)
    pu = int(ctx.get("partner_uid") or 0)
    text = f"<b>{t(uid, 'ai_hub_title')}</b>\n\n{t(uid, 'ai_hub_intro')}\n\n"
    text += f"viewer=<code>{vu}</code> · partner=<code>{pu}</code>"
    kb = [
        [{"text": t(uid, "ai_set_viewer"), "callback_data": "a:v"}, {"text": t(uid, "ai_set_partner"), "callback_data": "a:p"}],
        [{"text": t(uid, "ai_get_suggestions"), "callback_data": "a:g"}, {"text": t(uid, "ai_new_suggestions"), "callback_data": "a:ns"}],
        [{"text": t(uid, "ai_improve"), "callback_data": "a:im"}, {"text": t(uid, "ai_meeting_check"), "callback_data": "a:mr"}],
        [{"text": t(uid, "ai_start_strategy_btn"), "callback_data": "a:ss"}, {"text": t(uid, "ai_timed_now"), "callback_data": "a:tn"}],
        [{"text": t(uid, "ai_timed_reengage"), "callback_data": "a:te"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_orders_hub(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{t(uid, 'orders_hub_title')}</b>\n\n{t(uid, 'orders_hub_intro')}"
    kb = [
        [{"text": t(uid, "premium"), "callback_data": "m:premium"}, {"text": t(uid, "growth"), "callback_data": "m:growth"}],
        [{"text": t(uid, "statistics"), "callback_data": "m:stats"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_shipments_hub(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{t(uid, 'shipments_hub_title')}</b>\n\n{t(uid, 'shipments_hub_intro')}"
    kb = [
        [{"text": t(uid, "engagement"), "callback_data": "m:engagement"}, {"text": t(uid, "match_quality"), "callback_data": "m:match_quality"}],
        [{"text": t(uid, "conversation_quality"), "callback_data": "m:conversation_quality"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_analytics_hub(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{t(uid, 'analytics_hub_title')}</b>\n\n{t(uid, 'analytics_hub_intro')}"
    kb = [
        [{"text": t(uid, "statistics"), "callback_data": "m:stats"}, {"text": t(uid, "growth"), "callback_data": "m:growth"}],
        [{"text": t(uid, "conversation_quality"), "callback_data": "m:conversation_quality"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_settings_hub(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{t(uid, 'settings_hub_title')}</b>\n\n{t(uid, 'settings_hub_intro')}"
    kb = [
        [{"text": t(uid, "language"), "callback_data": "m:lang"}, {"text": t(uid, "system"), "callback_data": "m:system"}],
        [{"text": t(uid, "menu_ai_quality"), "callback_data": "m:aiq"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_product_diagnostics(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    try:
        raw = backend.request("GET", "/api/v1/admin/telegram/diagnostics")
    except Exception:
        raw = {}
    doc = raw if isinstance(raw, dict) else {}
    lines = doc.get("telegram_diagnostic_lines") if isinstance(doc.get("telegram_diagnostic_lines"), list) else []
    modes = doc.get("telegram_active_modes") if isinstance(doc.get("telegram_active_modes"), dict) else {}
    tag_err = str(doc.get("telegram_error_tags") or "[partial]")
    errs = doc.get("telegram_last_errors") if isinstance(doc.get("telegram_last_errors"), list) else []

    text = f"<b>{t(uid, 'diag_hub_title')}</b>\n\n"
    text += "<b>Core</b>\n"
    for ln in lines[:6]:
        text += _fmt_diag_line(str(ln)) + "\n"
    text += f"\n<b>Active modes</b> <code>{escape(json.dumps(modes, ensure_ascii=False))}</code>\n"
    text += f"\n<b>Errors</b> {escape(tag_err)}\n"
    if errs:
        for i, er in enumerate(errs[:5], start=1):
            chunk = er if isinstance(er, str) else json.dumps(er, ensure_ascii=False)
            text += f"{i}. <pre>{escape(chunk[:400])}</pre>\n"
    else:
        text += "<i>none</i>\n"

    kb = [[{"text": t(uid, "diag_refresh"), "callback_data": "m:diag"}], [{"text": t(uid, "back"), "callback_data": "m:home"}]]
    return text, kb


def render_users_search_prompt(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{escape(t(uid, 'users_section_title'))}</b>\n\n{t(uid, 'users_search_prompt')}"
    return text, [[{"text": t(uid, "back"), "callback_data": "m:home"}]]


def render_safety_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{escape(t(uid, 'safety'))}</b>\n\n{t(uid, 'safety_menu_intro')}"
    kb = [
        [{"text": t(uid, "safety_open_reports"), "callback_data": "m:reports_open"}, {"text": t(uid, "safety_resolved_reports"), "callback_data": "m:reports_resolved"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_premium_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{escape(t(uid, 'premium'))}</b>\n\n{t(uid, 'premium_menu_intro')}"
    kb = [
        [{"text": t(uid, "mq_overview"), "callback_data": "m:premium_overview"}, {"text": t(uid, "premium_expiring_title"), "callback_data": "m:premium_expiring"}],
        [{"text": t(uid, "premium_grant_all_dev"), "callback_data": "c:premium_grant_all"}],
        [{"text": t(uid, "premium_create_promo"), "callback_data": "c:promo_create"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_premium_overview(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    raw = backend.request("GET", "/api/v1/admin/premium/overview")
    data = raw if isinstance(raw, dict) else raw
    rr = (data or {}).get("referral_rewards") if isinstance(data, dict) else None
    rr = rr if isinstance(rr, dict) else {}
    head = f"<b>{escape(t(uid, 'premium_overview_title'))}</b>"
    if rr:
        head += "\n\n" + t(
            uid,
            "premium_overview_referral_line",
            grants=int(rr.get("grants_last_30d") or 0),
            days=int(rr.get("premium_days_granted_last_30d") or 0),
            flags=len(rr.get("abuse_flags") or []),
        )
    text = head + "\n\n" + fmt_json_block(uid, data)
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:premium_overview"}],
        [{"text": t(uid, "back"), "callback_data": "m:premium"}],
    ]
    return text, kb


def render_premium_expiring(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    users = backend.request("GET", "/api/v1/admin/premium/expiring-trials")
    rows = users if isinstance(users, list) else []
    text = f"<b>{escape(t(uid, 'premium_expiring_title'))}</b>\n\n" + fmt_json_block(uid, rows[:50])
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:premium_expiring"}],
        [{"text": t(uid, "back"), "callback_data": "m:premium"}],
    ]
    return text, kb


def render_reports_list(user_id: int = 0, status: str = "open", limit: int = 20, offset: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    st = str(status or "open").strip() or "open"
    items = backend.request("GET", f"/api/v1/admin/reports?status={st}&limit={limit}&offset={offset}")
    rows = items if isinstance(items, list) else []
    text = f"<b>{escape(t(uid, 'reports_title'))}</b>\n\n{t(uid, 'reports_status')}: <code>{st}</code>\n{t(uid, 'reports_count')}: {len(rows)}"
    kb: list[list[dict[str, str]]] = []
    for r in rows[:12]:
        rd = r if isinstance(r, dict) else {}
        rid = int(rd.get("report_id") or 0)
        title = f"#{rid} · {rd.get('category') or 'other'} · u{rd.get('reported_user_id')} · {str(rd.get('reason') or '')[:24]}"
        kb.append([{"text": title[:60], "callback_data": f"r:{rid}"}])
    kb.append([{"text": t(uid, "refresh"), "callback_data": f"m:reports_{st}"}])
    kb.append([{"text": t(uid, "back"), "callback_data": "m:safety"}])
    return text, kb


def render_match_quality_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{escape(t(uid, 'match_quality_title_plain'))}</b>\n\n{t(uid, 'mq_menu_intro')}"
    kb = [
        [{"text": t(uid, "mq_overview"), "callback_data": "m:match_quality_overview"}, {"text": t(uid, "mq_weak_matches"), "callback_data": "m:match_quality_weak"}],
        [{"text": t(uid, "mq_dead_chats"), "callback_data": "m:match_quality_dead"}],
        [{"text": t(uid, "mq_recompute"), "callback_data": "m:match_quality_recompute"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_match_quality_overview(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    raw = backend.request("GET", "/api/v1/admin/match-quality/overview")
    data = raw if isinstance(raw, dict) else {}

    def pct(x: float) -> str:
        try:
            return f"{round(float(x) * 100)}%"
        except Exception:
            return "0%"

    text = f"<b>{escape(t(uid, 'match_quality_title_plain'))}</b>\n\n"
    text += t(
        uid,
        "mq_overview_matches",
        total=data.get("total_matches", 0),
        today=data.get("matches_today", 0),
    )
    text += "\n"
    text += t(
        uid,
        "mq_overview_counts",
        weak=data.get("weak_matches_count", 0),
        dead=data.get("dead_chats_count", 0),
        active=data.get("active_chats_count", 0),
    )
    text += "\n"
    text += t(uid, "mq_overview_rates", reply=pct(data.get("reply_rate", 0)), mutual=pct(data.get("mutual_like_rate", 0)))
    text += "\n"
    text += t(
        uid,
        "mq_overview_ai",
        cov=pct(data.get("ai_match_coverage_rate", 0)),
        score=round(float(data.get("average_compatibility_score", 0) or 0), 1),
    )
    issues = (data or {}).get("top_match_issues") if isinstance(data, dict) else []
    if issues:
        top = ", ".join([f"{(i or {}).get('issue')}({(i or {}).get('count')})" for i in issues[:5] if isinstance(i, dict)])
        text += t(uid, "mq_overview_top_issues", issues=top)

    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:match_quality_overview"}],
        [{"text": t(uid, "back"), "callback_data": "m:match_quality"}],
    ]
    return text, kb


def _render_match_list(user_id: int, title: str, rows: Any, back_cb: str) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    arr = rows if isinstance(rows, list) else []
    digest = []
    for r in arr[:30]:
        users = r.get("users") if isinstance(r, dict) else None
        a = (users or {}).get("a", {}) if isinstance(users, dict) else {}
        b = (users or {}).get("b", {}) if isinstance(users, dict) else {}
        digest.append(
            {
                "match_id": r.get("match_id"),
                "a": {"id": a.get("id"), "name": a.get("display_name"), "age": a.get("age"), "city": a.get("city")},
                "b": {"id": b.get("id"), "name": b.get("display_name"), "age": b.get("age"), "city": b.get("city")},
                "score": r.get("compatibility_score"),
                "msgs": r.get("messages_count"),
                "last": r.get("last_message_at"),
                "reason": r.get("reason"),
            }
        )
    text = f"<b>{title}</b>\n\n" + fmt_json_block(uid, digest)
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": back_cb}],
        [{"text": t(uid, "back"), "callback_data": "m:match_quality"}],
    ]
    return text, kb


def render_match_quality_weak(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    rows = backend.request("GET", "/api/v1/admin/match-quality/weak-matches")
    return _render_match_list(int(user_id or 0), t(int(user_id or 0), "mq_weak_title"), rows, "m:match_quality_weak")


def render_match_quality_dead(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    rows = backend.request("GET", "/api/v1/admin/match-quality/dead-chats")
    return _render_match_list(int(user_id or 0), t(int(user_id or 0), "mq_dead_title"), rows, "m:match_quality_dead")


ENGAGEMENT_SCREEN_BACK: dict[str, str] = {
    "a": "m:engagement_ai_suggestions",
    "v": "m:engagement_revive",
    "f": "m:engagement_first_boost",
    "o": "m:engagement_overview",
}

ENGAGEMENT_SCREEN_MENU_KEY: dict[str, str] = {
    "a": "engagement_ai_suggestions",
    "v": "engagement_revive",
    "f": "engagement_first_boost",
    "o": "engagement_overview",
}


def parse_engagement_generate_callback(data: str) -> tuple[str, str, int, str] | None:
    parts = str(data or "").strip().split(":")
    if len(parts) != 4 or parts[0] != "e":
        return None
    _, gk, screen, mid_s = parts
    if gk not in {"gt", "gr", "go"} or screen not in ENGAGEMENT_SCREEN_BACK:
        return None
    try:
        mid = int(mid_s)
    except Exception:
        return None
    if mid <= 0:
        return None
    kmap = {"gt": "tones", "gr": "revive", "go": "opener"}
    refresh = f"e:{gk}:{screen}:{mid}"
    if len(refresh.encode("utf-8")) > 64:
        return None
    return kmap[gk], screen, mid, refresh[:64]


def _engagement_pct(val: Any) -> str:
    try:
        return f"{round(float(val) * 100)}%"
    except Exception:
        return "0%"


def _engagement_ts_short(iso_s: str | None) -> str:
    if not iso_s:
        return "—"
    s = str(iso_s).strip()
    return s[:19].replace("T", " ") if s else "—"


def _engagement_fetch_targets() -> dict[str, Any]:
    try:
        raw = backend.request("GET", "/api/v1/admin/engagement/targets")
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _engagement_format_actions_text(uid: int, actions: list[Any], type_filter: set[str] | None = None) -> str:
    arr = actions if isinstance(actions, list) else []
    blocks: list[str] = []
    idx = 0
    for a in arr:
        if not isinstance(a, dict):
            continue
        at = str(a.get("type") or "").strip()
        if type_filter is not None and at not in type_filter:
            continue
        idx += 1
        mid = int(a.get("match_id") or 0)
        if at == "first_message_nudge":
            u = int(a.get("user_id") or 0)
            head = t(uid, "engagement_action_opener_nudge", i=idx, uid=u, mid=mid)
            sug = str(a.get("suggestion") or "").strip()
            blocks.append(head + (f"\n<i>{escape(sug[:450])}</i>" if sug else ""))
        elif at == "ai_message_suggestion":
            pair = f'{a.get("user_a_name") or ""} · {a.get("user_b_name") or ""}'.strip()
            head = t(uid, "engagement_action_opener_suggestions", i=idx, mid=mid)
            if pair:
                head += f" — {escape(pair[:120])}"
            tones = a.get("tones") if isinstance(a.get("tones"), dict) else None
            if tones and any(str(tones.get(k) or "").strip() for k in ("light", "flirty", "deep")):
                body = (
                    f"\n{t(uid, 'engagement_label_light')} {escape(str(tones.get('light') or '')[:400])}\n"
                    f"{t(uid, 'engagement_label_flirty')} {escape(str(tones.get('flirty') or '')[:400])}\n"
                    f"{t(uid, 'engagement_label_deep')} {escape(str(tones.get('deep') or '')[:400])}"
                )
            else:
                body = ""
                for j, s in enumerate((a.get("suggestions") or [])[:6], 1):
                    lbl = ("light", "flirty", "deep")[j - 1] if j <= 3 else str(j)
                    body += f"\n<b>{escape(lbl)}</b> {escape(str(s)[:400])}"
            blocks.append(head + body)
        elif at == "revive_chat":
            head = t(uid, "engagement_action_revive", i=idx, mid=mid)
            pair = f'{a.get("user_a_name") or ""} · {a.get("user_b_name") or ""}'.strip()
            if pair:
                head += f" — {escape(pair[:100])}"
            when = _engagement_ts_short(str(a.get("last_message_at") or "") or None)
            if when != "—":
                head += f"\n{t(uid, 'engagement_last_active', when=escape(when))}"
            sug = str(a.get("suggestion") or "").strip()
            blocks.append(head + (f"\n<i>{escape(sug[:450])}</i>" if sug else ""))
        elif at == "weak_match_hint":
            head = t(uid, "engagement_action_weak", i=idx, mid=mid)
            sug = str(a.get("suggestion") or "").strip()
            blocks.append(head + (f"\n<i>{escape(sug[:450])}</i>" if sug else ""))
        else:
            head = t(uid, "engagement_action_generic", i=idx, atype=escape(at or "?"), mid=mid)
            blocks.append(head)
    return "\n\n".join(blocks)


def render_engagement_generated_detail(
    user_id: int = 0,
    api_kind: str = "",
    payload: dict[str, Any] | None = None,
    back_cb: str = "m:engagement",
    refresh_cb: str = "m:engagement",
) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    payload = payload if isinstance(payload, dict) else {}
    kind = str(api_kind or "").strip().lower()
    pair = escape(str(payload.get("pair_label") or "").strip() or "—")
    mid = int(payload.get("match_id") or 0)
    text = f"<b>{escape(t(uid, 'engagement'))}</b>\n"
    if kind in {"tones", "opener", "revive"}:
        src = t(uid, "engagement_ai_src_ai") if payload.get("ai_used") else t(uid, "engagement_ai_src_template")
        text += t(uid, "engagement_ai_used", src=escape(src)) + "\n\n"
        if kind == "tones":
            tones = payload.get("tones") if isinstance(payload.get("tones"), dict) else {}
            text += t(uid, "engagement_tone_intro", mid=mid, pair=pair) + "\n\n"
            text += f"{t(uid, 'engagement_label_light')} {escape(str(tones.get('light') or '')[:650])}\n\n"
            text += f"{t(uid, 'engagement_label_flirty')} {escape(str(tones.get('flirty') or '')[:650])}\n\n"
            text += f"{t(uid, 'engagement_label_deep')} {escape(str(tones.get('deep') or '')[:650])}\n"
        elif kind == "opener":
            text += t(uid, "engagement_opener_intro", mid=mid, pair=pair) + "\n\n"
            text += f"<i>{escape(str(payload.get('opener') or '')[:900])}</i>\n"
        elif kind == "revive":
            last = payload.get("last_message_at")
            if last:
                text += escape(t(uid, "engagement_last_active", when=_engagement_ts_short(str(last)))) + "\n\n"
            text += t(uid, "engagement_revive_intro", mid=mid, pair=pair) + "\n\n"
            text += f"<i>{escape(str(payload.get('revive_message') or '')[:900])}</i>\n"
        text += "\n" + t(uid, "engagement_safety_note")
    else:
        text += t(uid, "engagement_menu_intro") + "\n\n" + t(uid, "engagement_safety_note")
    if len(text) > 3800:
        text = text[:3790] + "…"
    refresh_data = str(refresh_cb or "m:engagement")[:64]
    back_data = str(back_cb or "m:engagement")[:64]
    kb = [
        [{"text": t(uid, "engagement_btn_regenerate"), "callback_data": refresh_data}],
        [{"text": t(uid, "back"), "callback_data": back_data}],
    ]
    return text, kb


def render_engagement_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    title = escape(t(uid, "engagement"))
    text = f"<b>{title}</b>\n\n{t(uid, 'engagement_menu_intro')}\n\n{t(uid, 'engagement_safety_note')}"
    kb = [
        [{"text": t(uid, "engagement_btn_overview"), "callback_data": "m:engagement_overview"}, {"text": t(uid, "engagement_btn_suggested"), "callback_data": "m:engagement_actions"}],
        [{"text": t(uid, "engagement_btn_revive"), "callback_data": "m:engagement_revive"}, {"text": t(uid, "engagement_btn_first_boost"), "callback_data": "m:engagement_first_boost"}],
        [{"text": t(uid, "engagement_btn_ai_suggestions"), "callback_data": "m:engagement_ai_suggestions"}],
        [{"text": t(uid, "engagement_btn_style_learning"), "callback_data": "m:engagement_style_learning_7d"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_engagement_style_learning(user_id: int = 0, period: str = "7d") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    p = str(period or "7d").strip().lower()
    if p not in {"today", "7d", "30d"}:
        p = "7d"
    raw = backend.request("GET", f"/api/v1/admin/stats/chat-brain-style?period={p}")
    data = raw if isinstance(raw, dict) else {}
    title = escape(t(uid, "engagement_style_learning_title"))
    plab = t(uid, "engagement_style_period_today" if p == "today" else "engagement_style_period_30d" if p == "30d" else "engagement_style_period_7d")
    text = f"<b>{title}</b>\n\n{t(uid, 'engagement_style_learning_intro')}\n\n"
    text += t(uid, "engagement_style_period_line", label=escape(plab)) + "\n\n"
    rr = float(data.get("reply_after_brain_rate") or 0)
    text += t(uid, "engagement_style_reply_rate", pct=_engagement_pct(rr)) + "\n"
    text += t(uid, "engagement_style_sends", n=int(data.get("brain_assisted_sends") or 0)) + "\n"
    text += t(uid, "engagement_style_replies", n=int(data.get("brain_followup_replies_observed") or 0)) + "\n\n"
    top_p = data.get("top_picked_style")
    top_s = data.get("top_successful_style")
    if top_p:
        text += t(uid, "engagement_style_top_pick", style=escape(str(top_p))) + "\n"
    else:
        text += t(uid, "engagement_style_top_pick_none") + "\n"
    if top_s:
        text += t(uid, "engagement_style_top_success", style=escape(str(top_s))) + "\n"
    else:
        text += t(uid, "engagement_style_top_success_none") + "\n"
    sp = data.get("style_distribution_picks") if isinstance(data.get("style_distribution_picks"), dict) else {}
    sr = data.get("style_distribution_replies") if isinstance(data.get("style_distribution_replies"), dict) else {}
    text += f"\n<b>{escape(t(uid, 'engagement_style_dist_picks'))}</b>\n"
    for k in ("light", "flirty", "deep"):
        text += f"• {k}: {int(sp.get(k) or 0)}\n"
    text += f"\n<b>{escape(t(uid, 'engagement_style_dist_replies'))}</b>\n"
    for k in ("light", "flirty", "deep"):
        text += f"• {k}: {int(sr.get(k) or 0)}\n"
    text += "\n<i>" + escape(t(uid, "engagement_style_aggregate_note")) + "</i>"
    refresh_map = {"today": "m:engagement_style_learning_today", "7d": "m:engagement_style_learning_7d", "30d": "m:engagement_style_learning_30d"}
    refresh_cb = refresh_map.get(p, "m:engagement_style_learning_7d")
    kb = [
        [
            {"text": t(uid, "engagement_style_period_today"), "callback_data": "m:engagement_style_learning_today"},
            {"text": t(uid, "engagement_style_period_7d"), "callback_data": "m:engagement_style_learning_7d"},
        ],
        [{"text": t(uid, "engagement_style_period_30d"), "callback_data": "m:engagement_style_learning_30d"}],
        [{"text": t(uid, "refresh"), "callback_data": refresh_cb}],
        [{"text": t(uid, "back"), "callback_data": "m:engagement"}],
    ]
    return text, kb


def render_engagement_overview(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    raw = backend.request("GET", "/api/v1/admin/engagement/overview")
    data = raw if isinstance(raw, dict) else {}
    tg = _engagement_fetch_targets()
    counts = tg.get("counts") if isinstance(tg.get("counts"), dict) else {}
    title = escape(t(uid, "engagement"))
    pct = _engagement_pct
    text = f"<b>{title}</b>\n\n"
    text += t(uid, "engagement_first_rate", pct=pct(data.get("first_message_rate", 0))) + "\n"
    text += t(uid, "engagement_reply_rate", pct=pct(data.get("reply_rate", 0))) + "\n"
    text += t(uid, "engagement_dead_chats", n=int(data.get("dead_chats_count") or 0)) + "\n"
    text += t(uid, "engagement_chats_no_msg", n=int(data.get("chats_no_first_message_count") or 0)) + "\n"
    text += t(uid, "engagement_stale_sample", n=int(data.get("stale_chats_sample_count") or 0)) + "\n"
    avg_h = data.get("avg_time_to_first_message_hours")
    if avg_h is not None:
        try:
            text += t(uid, "engagement_avg_first", hours=round(float(avg_h), 1)) + "\n"
        except Exception:
            pass
    rs = data.get("revive_success_rate")
    if rs is not None:
        text += t(uid, "engagement_revive_success", pct=pct(rs)) + "\n"
    text += "\n"
    text += f"<b>{escape(t(uid, 'engagement_issues_header'))}</b>\n"
    n_no = int(data.get("chats_no_first_message_count") or 0)
    n_stale = int(data.get("stale_chats_sample_count") or 0)
    if n_no or n_stale:
        if n_no:
            text += escape(t(uid, "engagement_issue_line_no_msg", n=n_no)) + "\n"
        if n_stale:
            text += escape(t(uid, "engagement_issue_line_stale", n=n_stale)) + "\n"
    else:
        text += escape(t(uid, "engagement_no_issues")) + "\n"
    text += f"\n<b>{escape(t(uid, 'engagement_targets_snapshot'))}</b>\n"
    text += t(
        uid,
        "engagement_targets_no_first",
        n=int(counts.get("no_first_message") or 0),
        shown=len(tg.get("no_first_message") or []),
    ) + "\n"
    for r in (tg.get("no_first_message") or [])[:4]:
        if not isinstance(r, dict):
            continue
        text += (
            escape(
                t(
                    uid,
                    "engagement_pair_line",
                    a=str(r.get("user_a_name") or "")[:40],
                    b=str(r.get("user_b_name") or "")[:40],
                    mid=int(r.get("match_id") or 0),
                )
            )
            + "\n"
        )
    text += t(
        uid,
        "engagement_targets_stale",
        n=int(counts.get("dead_stale") or 0),
        shown=len(tg.get("stale_chats") or []),
    ) + "\n"
    for r in (tg.get("stale_chats") or [])[:4]:
        if not isinstance(r, dict):
            continue
        line = t(
            uid,
            "engagement_pair_line",
            a=str(r.get("user_a_name") or "")[:40],
            b=str(r.get("user_b_name") or "")[:40],
            mid=int(r.get("match_id") or 0),
        )
        la = _engagement_ts_short(str(r.get("last_message_at") or "") or None)
        text += escape(line) + f" · {escape(la)}\n"
    text += "\n" + escape(t(uid, "engagement_note_no_private"))
    kb: list[list[dict[str, str]]] = []
    for r in (tg.get("no_first_message") or [])[:3]:
        if not isinstance(r, dict):
            continue
        mid = int(r.get("match_id") or 0)
        if mid <= 0:
            continue
        cb = f"e:gt:o:{mid}"[:64]
        kb.append([{"text": f"{t(uid, 'engagement_btn_tones_short')} m{mid}"[:64], "callback_data": cb}])
    for r in (tg.get("stale_chats") or [])[:2]:
        if not isinstance(r, dict):
            continue
        mid = int(r.get("match_id") or 0)
        if mid <= 0:
            continue
        kb.append([{"text": f"{t(uid, 'engagement_btn_revive_short')} m{mid}"[:64], "callback_data": f"e:gr:o:{mid}"[:64]}])
    kb.append([{"text": t(uid, "refresh"), "callback_data": "m:engagement_overview"}])
    kb.append([{"text": t(uid, "back"), "callback_data": "m:engagement"}])
    return text, kb


def render_engagement_suggested_actions(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    raw = backend.request("GET", "/api/v1/admin/engagement/actions")
    data = raw if isinstance(raw, dict) else {}
    actions = data.get("actions") if isinstance(data.get("actions"), list) else []
    body = _engagement_format_actions_text(uid, actions, None)
    text = f"<b>{escape(t(uid, 'engagement'))}</b>\n\n<b>{escape(t(uid, 'engagement_actions_title'))}</b>\n\n"
    if body:
        text += body + "\n\n"
    else:
        text += escape(t(uid, "engagement_actions_empty")) + "\n\n"
    text += t(uid, "engagement_safety_note")
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:engagement_actions"}],
        [{"text": t(uid, "back"), "callback_data": "m:engagement"}],
    ]
    return text, kb


def render_engagement_revive(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    tg = _engagement_fetch_targets()
    counts = tg.get("counts") if isinstance(tg.get("counts"), dict) else {}
    rows = tg.get("stale_chats") if isinstance(tg.get("stale_chats"), list) else []
    text = f"<b>{escape(t(uid, 'engagement'))}</b>\n\n<b>{escape(t(uid, 'engagement_btn_revive'))}</b>\n\n"
    text += t(uid, "engagement_targets_stale", n=int(counts.get("dead_stale") or 0), shown=len(rows)) + "\n"
    text += escape(t(uid, "engagement_note_no_private")) + "\n\n"
    if not rows:
        text += escape(t(uid, "engagement_actions_empty")) + "\n\n"
    else:
        for r in rows[:10]:
            if not isinstance(r, dict):
                continue
            mid = int(r.get("match_id") or 0)
            line = t(
                uid,
                "engagement_pair_line",
                a=str(r.get("user_a_name") or "")[:36],
                b=str(r.get("user_b_name") or "")[:36],
                mid=mid,
            )
            la = _engagement_ts_short(str(r.get("last_message_at") or "") or None)
            text += escape(line) + "\n"
            text += escape(t(uid, "engagement_last_active", when=la)) + "\n\n"
    text += t(uid, "engagement_safety_note")
    kb: list[list[dict[str, str]]] = []
    for r in rows[:8]:
        if not isinstance(r, dict):
            continue
        mid = int(r.get("match_id") or 0)
        if mid <= 0:
            continue
        pair = f'{str(r.get("user_a_name") or "")[:8]}↔{str(r.get("user_b_name") or "")[:8]}'
        kb.append(
            [
                {
                    "text": f"{t(uid, 'engagement_btn_revive_short')} m{mid}"[:64],
                    "callback_data": f"e:gr:v:{mid}"[:64],
                }
            ]
        )
    kb.append([{"text": t(uid, "refresh"), "callback_data": "m:engagement_revive"}])
    kb.append([{"text": t(uid, "back"), "callback_data": "m:engagement"}])
    return text, kb


def render_engagement_first_boost(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    tg = _engagement_fetch_targets()
    counts = tg.get("counts") if isinstance(tg.get("counts"), dict) else {}
    rows = tg.get("no_first_message") if isinstance(tg.get("no_first_message"), list) else []
    text = f"<b>{escape(t(uid, 'engagement'))}</b>\n\n<b>{escape(t(uid, 'engagement_btn_first_boost'))}</b>\n\n"
    text += t(uid, "engagement_targets_no_first", n=int(counts.get("no_first_message") or 0), shown=len(rows)) + "\n"
    text += escape(t(uid, "engagement_note_no_private")) + "\n\n"
    if not rows:
        text += escape(t(uid, "engagement_actions_empty")) + "\n\n"
    else:
        for r in rows[:12]:
            if not isinstance(r, dict):
                continue
            mid = int(r.get("match_id") or 0)
            line = t(
                uid,
                "engagement_pair_line",
                a=str(r.get("user_a_name") or "")[:36],
                b=str(r.get("user_b_name") or "")[:36],
                mid=mid,
            )
            text += escape(line) + "\n"
    text += "\n" + t(uid, "engagement_safety_note")
    kb: list[list[dict[str, str]]] = []
    for r in rows[:8]:
        if not isinstance(r, dict):
            continue
        mid = int(r.get("match_id") or 0)
        if mid <= 0:
            continue
        kb.append(
            [
                {
                    "text": f"{t(uid, 'engagement_btn_opener_short')} m{mid}"[:64],
                    "callback_data": f"e:go:f:{mid}"[:64],
                }
            ]
        )
    kb.append([{"text": t(uid, "refresh"), "callback_data": "m:engagement_first_boost"}])
    kb.append([{"text": t(uid, "back"), "callback_data": "m:engagement"}])
    return text, kb


def render_engagement_ai_suggestions(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    tg = _engagement_fetch_targets()
    counts = tg.get("counts") if isinstance(tg.get("counts"), dict) else {}
    rows = tg.get("no_first_message") if isinstance(tg.get("no_first_message"), list) else []
    text = f"<b>{escape(t(uid, 'engagement'))}</b>\n\n{t(uid, 'engagement_ai_screen_intro')}\n\n"
    text += t(uid, "engagement_targets_no_first", n=int(counts.get("no_first_message") or 0), shown=len(rows)) + "\n"
    text += escape(t(uid, "engagement_note_no_private")) + "\n\n"
    if not rows:
        text += escape(t(uid, "engagement_actions_empty")) + "\n\n"
    else:
        for r in rows[:10]:
            if not isinstance(r, dict):
                continue
            mid = int(r.get("match_id") or 0)
            line = t(
                uid,
                "engagement_pair_line",
                a=str(r.get("user_a_name") or "")[:36],
                b=str(r.get("user_b_name") or "")[:36],
                mid=mid,
            )
            text += escape(line) + "\n"
    text += "\n" + t(uid, "engagement_safety_note")
    kb: list[list[dict[str, str]]] = []
    for r in rows[:8]:
        if not isinstance(r, dict):
            continue
        mid = int(r.get("match_id") or 0)
        if mid <= 0:
            continue
        kb.append(
            [
                {
                    "text": f"{t(uid, 'engagement_btn_tones_short')} m{mid}"[:64],
                    "callback_data": f"e:gt:a:{mid}"[:64],
                }
            ]
        )
    kb.append([{"text": t(uid, "refresh"), "callback_data": "m:engagement_ai_suggestions"}])
    kb.append([{"text": t(uid, "back"), "callback_data": "m:engagement"}])
    return text, kb


def render_conversation_quality_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    text = f"<b>{t(uid, 'conversation_quality')}</b>\n\n"
    text += t(uid, "cq_choose_period") + "\n"
    kb = [
        [{"text": t(uid, "period_today"), "callback_data": "m:conversation_quality_today"}, {"text": t(uid, "period_7d"), "callback_data": "m:conversation_quality_7d"}, {"text": t(uid, "period_30d"), "callback_data": "m:conversation_quality_30d"}],
        [{"text": t(uid, "label_issues"), "callback_data": "m:conversation_quality_issues"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_conversation_quality_overview(user_id: int = 0, period: str = "today") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    p = period if period in {"today", "7d", "30d"} else "today"
    data = backend.request("GET", f"/api/v1/admin/conversation-quality/overview?period={p}")
    if not isinstance(data, dict):
        data = {}
    summ_raw = data.get("summary")
    summ = summ_raw if isinstance(summ_raw, dict) else {}
    styles_raw = data.get("styles")
    styles = styles_raw if isinstance(styles_raw, dict) else {}

    def pct(x: float) -> str:
        try:
            return f"{round(float(x) * 100)}%"
        except Exception:
            return "0%"

    best = None
    worst = None
    try:
        rr = {k: float((v or {}).get("reply_rate") or 0.0) for k, v in (styles or {}).items() if k in {"light", "flirty", "deep"}}
        if rr:
            best = max(rr.items(), key=lambda kv: kv[1])[0]
            worst = min(rr.items(), key=lambda kv: kv[1])[0]
    except Exception:
        pass

    title = t(uid, "conversation_quality")
    period_label = _period_label(uid, p)

    text = f"<b>{title}</b>\n<code>{period_label}</code>\n\n"
    text += t(
        uid,
        "cq_overview_ai_options",
        shown=summ.get("ai_options_shown", 0),
        selected=summ.get("ai_options_selected", 0),
    )
    text += "\n"
    text += t(uid, "cq_overview_selection", sel=pct(summ.get("selection_rate", 0)), edited=pct(summ.get("edited_rate", 0)))
    text += "\n"
    text += t(uid, "cq_overview_partner_reply", rate=pct(summ.get("partner_reply_rate", 0)))
    text += "\n"
    text += t(
        uid,
        "cq_overview_stalled",
        stall=summ.get("stall_detected_count", 0),
        revive=summ.get("revive_used_count", 0),
    )
    text += "\n"
    text += t(
        uid,
        "cq_overview_meeting",
        suggested=summ.get("meeting_suggested_count", 0),
        rejected=summ.get("meeting_rejected_count", 0),
    )
    text += "\n"
    if best or worst:
        text += t(uid, "cq_best_worst_style", best=best or "-", worst=worst or "-")

    issues_raw = data.get("issues")
    issues = issues_raw if isinstance(issues_raw, list) else []
    if issues:
        text += t(uid, "cq_issues_prefix") + ", ".join(
            [str(i.get("type")) for i in issues[:5] if isinstance(i, dict)]
        )

    kb = [
        [{"text": t(uid, "refresh"), "callback_data": f"m:conversation_quality_{p}"}],
        [{"text": t(uid, "label_issues"), "callback_data": "m:conversation_quality_issues"}],
        [{"text": t(uid, "back"), "callback_data": "m:conversation_quality"}],
    ]
    return text, kb


def render_conversation_quality_issues(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = backend.request("GET", "/api/v1/admin/conversation-quality/issues")
    text = f"<b>{t(uid, 'conversation_quality')}</b>\n\n"
    text += t(uid, "cq_issues_heading") + "\n\n"
    text += fmt_json_block(uid, data if isinstance(data, (dict, list)) else [])
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:conversation_quality_issues"}],
        [{"text": t(uid, "back"), "callback_data": "m:conversation_quality"}],
    ]
    return text, kb


def render_report_detail(admin_id: int = 0, report_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(admin_id or 0)
    rid = int(report_id or 0)
    if rid <= 0:
        return fallback_render_ui(uid, t(uid, "no_data_available"), "m:reports_open")
    raw = backend.request("GET", f"/api/v1/admin/reports/{rid}")
    data = raw if isinstance(raw, dict) else {}
    rep = (data or {}).get("report") or {}
    rec = (data or {}).get("moderation_recommendation") or {}
    reported_user_id = int(rep.get("reported_user_id") or 0)
    text = f"<b>{escape(t(uid, 'report_detail_title'))}</b>\n\n" + fmt_json_block(
        uid,
        {
            "report": rep,
            "reported_user": (data or {}).get("reported_user") or {},
            "reporter_user": (data or {}).get("reporter_user") or {},
            "previous_reports_count": (data or {}).get("previous_reports_count"),
            "recommendation": rec,
        },
    )
    kb: list[list[dict[str, str]]] = [
        [{"text": t(uid, "report_open_reported"), "callback_data": f"u:{reported_user_id}"}],
        [{"text": t(uid, "report_dismiss"), "callback_data": f"c:rep_dismiss:{rid}"}, {"text": t(uid, "report_ban_user"), "callback_data": f"c:rep_ban:{rid}:{reported_user_id}"}],
        [{"text": t(uid, "back"), "callback_data": "m:reports_open"}],
    ]
    return text, kb


def render_growth_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    title = t(uid, "growth")
    text = f"<b>{title}</b>\n\n"
    text += t(uid, "growth_choose_period") + "\n"
    kb = [
        [{"text": t(uid, "period_today"), "callback_data": "m:growth_today"}, {"text": t(uid, "period_7d"), "callback_data": "m:growth_7d"}, {"text": t(uid, "period_30d"), "callback_data": "m:growth_30d"}],
        [{"text": t(uid, "label_recommendations"), "callback_data": "m:growth_recs"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_growth_overview(user_id: int = 0, period: str = "7d") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    p = period if period in {"today", "7d", "30d"} else "7d"
    data = backend.request("GET", f"/api/v1/admin/growth/overview?period={p}")
    if not isinstance(data, dict):
        data = {}

    def _subobj(key: str) -> dict[str, Any]:
        v = data.get(key)
        return v if isinstance(v, dict) else {}

    acq = _subobj("acquisition")
    act = _subobj("activation")
    ret = _subobj("retention")
    mon = _subobj("monetization")
    recs_raw = data.get("recommendations")
    recs = recs_raw if isinstance(recs_raw, list) else []

    def pct(x: float) -> str:
        try:
            return f"{round(float(x) * 100)}%"
        except Exception:
            return "0%"

    def top_k(d: dict, n: int = 3) -> str:
        if not isinstance(d, dict) or not d:
            return "-"
        items = sorted([(str(k), int(v or 0)) for k, v in d.items()], key=lambda kv: kv[1], reverse=True)[:n]
        return ", ".join([f"{k}:{v}" for k, v in items]) if items else "-"

    title = t(uid, "growth")
    period_label = _period_label(uid, p)

    text = f"<b>{title}</b>\n<code>{period_label}</code>\n\n"
    text += t(uid, "growth_overview_new_active", new_u=acq.get("new_users", 0), active=ret.get("active_users", 0))
    text += "\n"
    text += t(uid, "growth_overview_profile", prof=pct(act.get("profile_completed_rate", 0)), photo=pct(act.get("photo_added_rate", 0)))
    text += "\n"
    text += t(uid, "growth_overview_first", match=pct(act.get("first_match_rate", 0)), msg=pct(act.get("first_message_rate", 0)))
    text += "\n"
    text += t(uid, "growth_overview_premium", conv=pct(mon.get("premium_conversion_rate", 0)), views=mon.get("paywall_views", 0))
    text += "\n"
    ref_parent = data.get("referrals")
    ref_blk = (ref_parent.get("referral_rewards") if isinstance(ref_parent, dict) else None)
    ref_blk = ref_blk if isinstance(ref_blk, dict) else {}
    text += t(
        uid,
        "growth_overview_referral_rewards",
        grants=int(ref_blk.get("premium_grants_in_period") or 0),
        flags=len(ref_blk.get("abuse_flags") or []),
    )
    text += "\n"
    text += t(uid, "growth_overview_locales", locales=top_k(acq.get("signups_by_locale", {})))
    text += "\n"
    text += t(uid, "growth_overview_countries", countries=top_k(acq.get("signups_by_country", {})))
    text += "\n"
    if recs:
        top_titles = "; ".join([str(r.get("title") or "") for r in (recs[:2] if isinstance(recs, list) else []) if isinstance(r, dict) and r.get("title")])
        if top_titles:
            text += t(uid, "growth_overview_top_recs", recs=top_titles)

    kb = [
        [{"text": t(uid, "refresh"), "callback_data": f"m:growth_{p}"}],
        [{"text": t(uid, "label_recommendations"), "callback_data": "m:growth_recs"}],
        [{"text": t(uid, "back"), "callback_data": "m:growth"}],
    ]
    return text, kb


def render_growth_recommendations(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    rows = backend.request("GET", "/api/v1/admin/growth/recommendations")
    arr = rows if isinstance(rows, list) else []
    title = t(uid, "growth")
    text = f"<b>{title}</b>\n\n"
    text += t(uid, "growth_recs_heading") + "\n\n"
    text += fmt_json_block(uid, arr)
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:growth_recs"}],
        [{"text": t(uid, "back"), "callback_data": "m:growth"}],
    ]
    return text, kb

def render_user_results(user_id: int = 0, items: list[dict[str, Any]] | None = None, q: str = "") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    arr = items if isinstance(items, list) else []
    text = f"<b>{escape(t(uid, 'users_section_title'))}</b>\n\n{t(uid, 'users_query', q=escape(q))}\n\n{t(uid, 'users_found', n=len(arr))}"
    kb: list[list[dict[str, str]]] = []
    for u in arr[:12]:
        row = u if isinstance(u, dict) else {}
        uname = str(row.get("display_name") or row.get("email") or t(uid, "word_unknown"))
        title = f"{uname} (id {row.get('id')})"
        kb.append([{"text": title[:60], "callback_data": f"u:{int(row.get('id') or 0)}"}])
    kb.append([{"text": t(uid, "users_new_search"), "callback_data": "m:users"}])
    kb.append([{"text": t(uid, "back"), "callback_data": "m:home"}])
    return text, kb


def render_product_manager_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    title = t(uid, "product_manager")
    text = f"<b>{title}</b>\n\n"
    text += t(uid, "pm_choose_brief") + "\n"
    kb = [
        [{"text": t(uid, "pm_daily_brief"), "callback_data": "m:pm_today"}, {"text": t(uid, "pm_brief_7d"), "callback_data": "m:pm_7d"}, {"text": t(uid, "pm_brief_30d"), "callback_data": "m:pm_30d"}],
        [{"text": t(uid, "label_risks"), "callback_data": "m:pm_risks"}, {"text": t(uid, "label_next_actions"), "callback_data": "m:pm_next"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_product_manager_brief(user_id: int = 0, period: str = "today") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    p = period if period in {"today", "7d", "30d"} else "today"
    data = backend.request("GET", f"/api/v1/admin/product-manager/daily-brief?period={p}")
    title = t(uid, "product_manager")

    top = (data or {}).get("top_priority") if isinstance(data, dict) else {}
    prios = (data or {}).get("priorities") if isinstance(data, dict) else []
    risks = (data or {}).get("risks") if isinstance(data, dict) else []
    next_actions = (data or {}).get("next_actions") if isinstance(data, dict) else []

    period_label = _period_label(uid, p)

    text = f"<b>{title}</b>\n<code>{period_label}</code>\n\n"
    text += t(uid, "pm_health_score", score=data.get("health_score", 0) if isinstance(data, dict) else 0)
    if isinstance(top, dict) and top:
        text += f"{t(uid, 'pm_top_priority')} {top.get('title', '')}\n"
        text += f"{t(uid, 'pm_why')} {top.get('reason', '')}\n"
        text += f"{t(uid, 'pm_action')} {top.get('recommended_action', '')}\n"

    if isinstance(prios, list) and prios:
        text += "\n" + t(uid, "pm_top3") + "\n"
        for i, r in enumerate(prios[:3], start=1):
            if not isinstance(r, dict):
                continue
            text += f"{i}) {r.get('title', '')} ({r.get('impact', '')}/{r.get('effort', '')})\n"

    if isinstance(risks, list) and risks:
        text += "\n" + t(uid, "pm_risks_heading") + " " + ", ".join([str(x.get("title")) for x in risks[:2] if isinstance(x, dict)])
    if isinstance(next_actions, list) and next_actions:
        text += "\n" + t(uid, "pm_next_heading") + " " + "; ".join([str(x.get("action")) for x in next_actions[:2] if isinstance(x, dict)])

    kb = [
        [{"text": t(uid, "refresh"), "callback_data": f"m:pm_{p}"}],
        [{"text": t(uid, "label_risks"), "callback_data": "m:pm_risks"}, {"text": t(uid, "label_next_actions"), "callback_data": "m:pm_next"}],
        [{"text": t(uid, "back"), "callback_data": "m:pm"}],
    ]
    return text, kb


def render_product_manager_risks(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = backend.request("GET", "/api/v1/admin/product-manager/daily-brief?period=7d")
    risks = (data or {}).get("risks") if isinstance(data, dict) else []
    title = t(uid, "product_manager")
    text = f"<b>{title}</b>\n\n" + t(uid, "pm_risks_heading") + "\n\n"
    text += fmt_json_block(uid, risks if isinstance(risks, list) else [])
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:pm_risks"}],
        [{"text": t(uid, "back"), "callback_data": "m:pm"}],
    ]
    return text, kb


def render_product_manager_next_actions(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = backend.request("GET", "/api/v1/admin/product-manager/daily-brief?period=7d")
    nxt = (data or {}).get("next_actions") if isinstance(data, dict) else []
    title = t(uid, "product_manager")
    text = f"<b>{title}</b>\n\n" + t(uid, "label_next_actions") + ":\n\n"
    text += fmt_json_block(uid, nxt if isinstance(nxt, list) else [])
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:pm_next"}],
        [{"text": t(uid, "back"), "callback_data": "m:pm"}],
    ]
    return text, kb

def render_user_details(admin_id: int = 0, target_user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(admin_id or 0)
    tid = int(target_user_id or 0)
    if tid <= 0:
        return fallback_render_ui(uid, t(uid, "no_data_available"), "m:users")
    raw = backend.request("GET", f"/api/v1/admin/users/{tid}")
    data = raw if isinstance(raw, dict) else {}
    user = (data.get("user") if isinstance(data.get("user"), dict) else None) or {}
    profile = (data.get("profile") if isinstance(data.get("profile"), dict) else None) or {}
    text = f"<b>{escape(t(uid, 'user_card_title'))}</b>\n\n" + fmt_json_block(
        uid,
        {
            "user": user,
            "profile": profile,
            "photos_count": data.get("photos_count"),
            "matches_count": data.get("matches_count"),
            "messages_count": data.get("messages_count"),
            "reports_count": data.get("reports_count"),
            "ai_memory_exists": data.get("ai_memory_exists"),
            "subscription": data.get("subscription"),
        },
    )
    is_banned = bool(user.get("is_banned"))
    kb: list[list[dict[str, str]]] = [
        [{"text": t(uid, "user_grant_premium_7d"), "callback_data": f"c:prem:{tid}:7"}, {"text": t(uid, "user_grant_premium_30d"), "callback_data": f"c:prem:{tid}:30"}],
        [{"text": t(uid, "user_revoke_premium"), "callback_data": f"c:revoke:{tid}"}, {"text": t(uid, "user_reset_ai_memory"), "callback_data": f"c:memreset:{tid}"}],
        [{"text": t(uid, "user_ban"), "callback_data": f"c:ban:{tid}"}, {"text": t(uid, "user_unban"), "callback_data": f"c:unban:{tid}"}],
        [{"text": t(uid, "back"), "callback_data": "m:users"}],
    ]
    if is_banned:
        kb[2] = [{"text": t(uid, "user_unban"), "callback_data": f"c:unban:{tid}"}, {"text": t(uid, "user_ban"), "callback_data": f"c:ban:{tid}"}]
    return text, kb


def render_cto_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    title = t(uid, "cto")
    text = f"<b>{title}</b>\n\n"
    text += t(uid, "cto_choose_roadmap") + "\n"
    kb = [
        [{"text": t(uid, "period_today"), "callback_data": "m:cto_today"}, {"text": t(uid, "period_7d_short"), "callback_data": "m:cto_7d"}, {"text": t(uid, "period_30d_short"), "callback_data": "m:cto_30d"}],
        [{"text": t(uid, "cto_tech_risks"), "callback_data": "m:cto_risks"}, {"text": t(uid, "cto_next_dev"), "callback_data": "m:cto_next"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def render_cto_roadmap(user_id: int = 0, period: str = "today") -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    p = period if period in {"today", "7d", "30d"} else "today"
    data = backend.request("GET", f"/api/v1/admin/cto/roadmap?period={p}")
    title = t(uid, "cto")
    top = (data or {}).get("top_engineering_priority") if isinstance(data, dict) else {}
    prios = (data or {}).get("priorities") if isinstance(data, dict) else []
    debt = (data or {}).get("technical_debt") if isinstance(data, dict) else []
    risks = (data or {}).get("risks") if isinstance(data, dict) else []
    next_actions = (data or {}).get("next_actions") if isinstance(data, dict) else []

    period_label = _period_label(uid, p)

    text = f"<b>{title}</b>\n<code>{period_label}</code>\n\n"
    text += t(uid, "cto_health_score", score=data.get("technical_health_score", 0) if isinstance(data, dict) else 0) + "\n\n"
    if isinstance(top, dict) and top:
        text += f"{t(uid, 'cto_top_eng')} {top.get('title', '')}\n"
        text += f"{t(uid, 'cto_reason')} {top.get('reason', '')}\n"
        text += f"{t(uid, 'cto_action')} {top.get('recommended_action', '')}\n"

    if isinstance(prios, list) and prios:
        text += "\n" + t(uid, "cto_top3") + "\n"
        for i, r in enumerate(prios[:3], start=1):
            if not isinstance(r, dict):
                continue
            text += f"{i}) {r.get('title', '')} ({r.get('impact', '')}/{r.get('risk', '')})\n"

    if isinstance(debt, list) and debt:
        text += "\n" + t(uid, "cto_debt") + " " + ", ".join([str(x.get("title")) for x in debt[:2] if isinstance(x, dict)])
    if isinstance(risks, list) and risks:
        text += "\n" + t(uid, "cto_risks_heading") + " " + ", ".join([str(x.get("title")) for x in risks[:2] if isinstance(x, dict)])
    if isinstance(next_actions, list) and next_actions:
        text += "\n" + t(uid, "cto_next_heading") + " " + "; ".join([str(x.get("action")) for x in next_actions[:2] if isinstance(x, dict)])

    kb = [
        [{"text": t(uid, "refresh"), "callback_data": f"m:cto_{p}"}],
        [{"text": t(uid, "cto_tech_risks"), "callback_data": "m:cto_risks"}, {"text": t(uid, "cto_next_dev"), "callback_data": "m:cto_next"}],
        [{"text": t(uid, "back"), "callback_data": "m:cto"}],
    ]
    return text, kb


def render_cto_risks(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = backend.request("GET", "/api/v1/admin/cto/roadmap?period=7d")
    risks = (data or {}).get("risks") if isinstance(data, dict) else []
    title = t(uid, "cto")
    text = f"<b>{title}</b>\n\n" + t(uid, "cto_risks_page_heading") + "\n\n"
    text += fmt_json_block(uid, risks if isinstance(risks, list) else [])
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:cto_risks"}],
        [{"text": t(uid, "back"), "callback_data": "m:cto"}],
    ]
    return text, kb


def render_cto_next_actions(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    data = backend.request("GET", "/api/v1/admin/cto/roadmap?period=7d")
    nxt = (data or {}).get("next_actions") if isinstance(data, dict) else []
    title = t(uid, "cto")
    text = f"<b>{title}</b>\n\n" + t(uid, "cto_next_actions_heading") + "\n\n"
    text += fmt_json_block(uid, nxt if isinstance(nxt, list) else [])
    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:cto_next"}],
        [{"text": t(uid, "back"), "callback_data": "m:cto"}],
    ]
    return text, kb


def render_menu_qa_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    title = t(uid, "menu_qa")
    text = f"<b>{title}</b>\n\n"
    text += t(uid, "menu_qa_intro")
    kb = [
        [{"text": t(uid, "label_run_scan"), "callback_data": "m:menu_qa_run"}],
        [{"text": t(uid, "label_show_critical"), "callback_data": "m:menu_qa_critical"}, {"text": t(uid, "label_warnings"), "callback_data": "m:menu_qa_warnings"}],
        [{"text": t(uid, "label_missing_translations"), "callback_data": "m:menu_qa_missing_tr"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def _menu_qa_fetch() -> dict:
    data = backend.request("GET", "/api/v1/admin/telegram-menu-qa/scan")
    return data if isinstance(data, dict) else {"status": "fail", "summary": {}, "issues": []}


def _menu_qa_render(user_id: int, mode: str = "all") -> tuple[str, list[list[dict[str, str]]]]:
    uidw = int(user_id or 0)
    try:
        return _menu_qa_render_body(user_id, mode)
    except Exception:
        return fallback_render_ui(uidw, t(uidw, "render_error_generic"), "m:menu_qa")


def _menu_qa_render_body(user_id: int, mode: str) -> tuple[str, list[list[dict[str, str]]]]:
    data = _menu_qa_fetch()
    title = t(user_id, "menu_qa")
    status = str(data.get("status") or "unknown")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    issues = data.get("issues") if isinstance(data.get("issues"), list) else []

    def _flt(it: dict) -> bool:
        if not isinstance(it, dict):
            return False
        if mode == "critical":
            return str(it.get("severity") or "") == "critical"
        if mode == "warnings":
            return str(it.get("severity") or "") in {"warning", "critical"}
        if mode == "missing_tr":
            return str(it.get("type") or "") == "missing_translation"
        return True

    filt = [i for i in (issues or []) if _flt(i)]
    top = filt[:15]
    uid = int(user_id or 0)
    text = f"<b>{title}</b>\n\n"
    text += f"{t(uid, 'menu_qa_status')} <code>{status}</code>\n"
    text += t(
        uid,
        "menu_qa_scan_line",
        menus=summary.get("menus_checked", 0),
        buttons=summary.get("buttons_checked", 0),
        callbacks=summary.get("callbacks_checked", 0),
    )
    text += "\n"
    text += t(
        uid,
        "menu_qa_metrics_line",
        mh=summary.get("missing_handlers", 0),
        mt=summary.get("missing_translations", 0),
        unsafe=summary.get("unsafe_actions", 0),
        rend=summary.get("render_errors", 0),
    )
    text += "\n\n"
    text += fmt_json_block(uid, top)

    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:menu_qa_run"}],
        [{"text": t(uid, "label_show_critical"), "callback_data": "m:menu_qa_critical"}, {"text": t(uid, "label_warnings"), "callback_data": "m:menu_qa_warnings"}],
        [{"text": t(uid, "label_missing_translations"), "callback_data": "m:menu_qa_missing_tr"}],
        [{"text": t(uid, "back"), "callback_data": "m:menu_qa"}],
    ]
    return text, kb


def render_e2e_qa_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    title = t(uid, "e2e_qa")
    text = f"<b>{title}</b>\n\n"
    text += t(uid, "e2e_qa_intro")
    kb = [
        [{"text": t(uid, "label_run_scan"), "callback_data": "m:e2e_qa_run"}],
        [{"text": t(uid, "label_critical_issues"), "callback_data": "m:e2e_qa_critical"}, {"text": t(uid, "label_warnings"), "callback_data": "m:e2e_qa_warnings"}],
        [{"text": t(uid, "label_last_report"), "callback_data": "m:e2e_qa_last"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def _e2e_qa_fetch() -> dict:
    data = backend.request("GET", "/api/v1/admin/e2e-qa/scan")
    return data if isinstance(data, dict) else {"status": "fail", "summary": {}, "flows": [], "issues": []}


def _e2e_qa_render(user_id: int, mode: str = "all") -> tuple[str, list[list[dict[str, str]]]]:
    uidw = int(user_id or 0)
    try:
        return _e2e_qa_render_body(user_id, mode)
    except Exception:
        return fallback_render_ui(uidw, t(uidw, "render_error_generic"), "m:e2e_qa")


def _e2e_qa_render_body(user_id: int, mode: str) -> tuple[str, list[list[dict[str, str]]]]:
    data = _e2e_qa_fetch()
    title = t(user_id, "e2e_qa")
    status = str(data.get("status") or "unknown")
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    issues = data.get("issues") if isinstance(data.get("issues"), list) else []
    flows = data.get("flows") if isinstance(data.get("flows"), list) else []

    def _flt(it: dict) -> bool:
        if not isinstance(it, dict):
            return False
        if mode == "critical":
            return str(it.get("severity") or "") == "critical"
        if mode == "warnings":
            return str(it.get("severity") or "") in {"warning", "critical"}
        return True

    top_issues = [i for i in (issues or []) if _flt(i)][:12]
    uid = int(user_id or 0)
    text = f"<b>{title}</b>\n\n"
    text += f"{t(uid, 'menu_qa_status')} <code>{status}</code>\n"
    text += t(
        uid,
        "e2e_flows_line",
        flows=summary.get("flows_checked", 0),
        passed=summary.get("passed", 0),
        warn=summary.get("warnings", 0),
        failed=summary.get("failed", 0),
    )
    text += "\n\n"
    text += t(uid, "e2e_top_issues") + "\n"
    text += fmt_json_block(uid, top_issues)

    try:
        flow_status = [{"id": f.get("id"), "status": f.get("status")} for f in (flows or [])[:10] if isinstance(f, dict)]
        text += "\n\n" + fmt_json_block(uid, flow_status, max_len=900)
    except Exception:
        pass

    kb = [
        [{"text": t(uid, "refresh"), "callback_data": "m:e2e_qa_run"}],
        [{"text": t(uid, "label_critical_issues"), "callback_data": "m:e2e_qa_critical"}, {"text": t(uid, "label_warnings"), "callback_data": "m:e2e_qa_warnings"}],
        [{"text": t(uid, "label_last_report"), "callback_data": "m:e2e_qa_last"}],
        [{"text": t(uid, "back"), "callback_data": "m:e2e_qa"}],
    ]
    return text, kb


def render_full_product_qa_menu(user_id: int = 0) -> tuple[str, list[list[dict[str, str]]]]:
    uid = int(user_id or 0)
    title = t(uid, "full_product_qa_title")
    text = f"<b>{escape(title)}</b>\n\n" + t(uid, "full_product_qa_intro")
    kb = [
        [{"text": t(uid, "full_product_qa_run"), "callback_data": "m:full_product_qa_run"}],
        [{"text": t(uid, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def _full_product_qa_choose(user_id: int) -> tuple[str, list[list[dict[str, str]]]]:
    uidw = int(user_id or 0)
    kb = [
        [{"text": "⚡ Quick QA", "callback_data": "m:full_product_qa_quick"}],
        [{"text": "🧪 Deep QA", "callback_data": "m:full_product_qa_deep"}],
        [{"text": t(uidw, "back"), "callback_data": "m:home"}],
    ]
    text = (
        "<b>🧪 Full Product QA</b>\n\n"
        "Choose mode:\n"
        "• ⚡ Quick QA — fast API smoke check\n"
        "• 🧪 Deep QA — real browser flows (Playwright)\n"
    )
    return text, kb


def _full_product_qa_run(user_id: int, *, kind: str) -> tuple[str, list[list[dict[str, str]]]]:
    uidw = int(user_id or 0)
    try:
        payload = backend.request("POST", "/api/v1/admin/qa-agent/run", json_body={"kind": kind})
    except Exception:
        return fallback_render_ui(uidw, t(uidw, "render_error_generic"), "m:home")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        err = str((payload or {}).get("error") or "").strip()
        if err == "QA_AGENT_DISABLED":
            return fallback_render_ui(uidw, t(uidw, "qa_disabled"), "m:home")
        return fallback_render_ui(uidw, t(uidw, "render_error_generic"), "m:home")
    formatted = str(payload.get("formatted_html") or "").strip()
    if not formatted:
        try:
            last = backend.request("GET", "/api/v1/admin/qa-agent/last?mode=deep")
            formatted = str((last or {}).get("formatted_html") or "").strip()
        except Exception:
            formatted = ""
    text = formatted or fmt_json_block(uidw, payload.get("report"), max_len=3600)
    kb = [
        [{"text": t(uidw, "full_product_qa_fix_top"), "callback_data": "m:full_product_qa_fix_top"}],
        [{"text": t(uidw, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def _full_product_qa_fix_top(user_id: int) -> tuple[str, list[list[dict[str, str]]]]:
    uidw = int(user_id or 0)
    try:
        payload = backend.request("GET", "/api/v1/admin/qa-agent/last?mode=prompts_top")
    except Exception:
        return fallback_render_ui(uidw, t(uidw, "render_error_generic"), "m:home")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return fallback_render_ui(uidw, "No QA report found yet.", "m:home")
    formatted = str(payload.get("formatted_html") or "").strip()
    text = formatted or fmt_json_block(uidw, payload.get("report"), max_len=3600)
    kb = [
        [{"text": t(uidw, "back"), "callback_data": "m:home"}],
    ]
    return text, kb


def _qa_agent_run(user_id: int, kind: str) -> tuple[str, list[list[dict[str, str]]]]:
    uidw = int(user_id or 0)
    try:
        payload = backend.request("POST", "/api/v1/admin/qa-agent/run", json_body={"kind": kind})
    except Exception:
        return fallback_render_ui(uidw, t(uidw, "render_error_generic"), "m:qa_agent")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        err = str((payload or {}).get("error") or "").strip()
        if err == "QA_AGENT_DISABLED":
            return fallback_render_ui(uidw, t(uidw, "qa_disabled"), "m:qa_agent")
        return fallback_render_ui(uidw, t(uidw, "render_error_generic"), "m:qa_agent")

    rep = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    title = str(rep.get("title") or t(uidw, "qa_agent_title"))
    score = rep.get("score")
    runtime_s = rep.get("runtime_s")
    top = rep.get("top_issues") if isinstance(rep.get("top_issues"), list) else []
    text = f"<b>{escape(title)}</b>\n\n"
    if score is not None:
        text += f"Score: <b>{escape(str(score))}</b>/100\n"
    if runtime_s is not None:
        text += f"Runtime: <code>{escape(str(runtime_s))}s</code>\n"
    if kind == "localization":
        text += "\n" + t(uidw, "qa_after_l10n") + "\n"
    if top:
        text += "\n<b>Top issues</b>\n"
        for it in top[:5]:
            if not isinstance(it, dict):
                continue
            sev = str(it.get("severity") or "").strip()
            ttl = str(it.get("title") or it.get("message") or "").strip()
            locs = it.get("probable_locations") if isinstance(it.get("probable_locations"), list) else []
            loc = str(locs[0]) if locs else ""
            text += f"• <code>{escape(sev)}</code> {escape(ttl)}"
            if loc:
                text += f"\n  <i>{escape(loc)}</i>"
            text += "\n"
    kb = [
        [{"text": t(uidw, "qa_mode_summary"), "callback_data": "m:qa_last_summary"}, {"text": t(uidw, "qa_mode_fixes"), "callback_data": "m:qa_last_fixes"}],
        [{"text": t(uidw, "qa_mode_deep"), "callback_data": "m:qa_last_deep"}],
        [{"text": t(uidw, "back"), "callback_data": "m:qa_agent"}],
    ]
    return text, kb


def _qa_agent_last(user_id: int, mode: str) -> tuple[str, list[list[dict[str, str]]]]:
    uidw = int(user_id or 0)
    try:
        payload = backend.request("GET", f"/api/v1/admin/qa-agent/last?mode={mode}")
    except Exception:
        return fallback_render_ui(uidw, t(uidw, "render_error_generic"), "m:qa_agent")
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        return fallback_render_ui(uidw, "No QA report found yet.", "m:qa_agent")
    title = str((payload.get("report") if isinstance(payload.get("report"), dict) else {}).get("title") or "QA report")
    formatted = str(payload.get("formatted_html") or "").strip()
    text = formatted if formatted else (f"<b>{escape(title)}</b>\n\n" + fmt_json_block(uidw, payload.get("report"), max_len=2400))
    kb = [
        [{"text": t(uidw, "qa_mode_summary"), "callback_data": "m:qa_last_summary"}, {"text": t(uidw, "qa_mode_fixes"), "callback_data": "m:qa_last_fixes"}],
        [{"text": t(uidw, "qa_mode_deep"), "callback_data": "m:qa_last_deep"}],
        [{"text": t(uidw, "back"), "callback_data": "m:qa_agent"}],
    ]
    return text, kb


def _short_btn_label(text: str, max_len: int = 58) -> str:
    s = (text or "").strip().replace("\n", " ")
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _extract_timed_texts(payload: dict[str, Any]) -> list[str]:
    opts = payload.get("options") if isinstance(payload.get("options"), list) else []
    out: list[str] = []
    for o in opts[:3]:
        if isinstance(o, dict):
            out.append(str(o.get("text") or "").strip())
    return out


def _route_ai_product_callbacks(data: str, chat_id: int, msg_id: int, user_id: int, cbq_id: str) -> None:
    uid0 = int(user_id or 0)
    cid0 = int(chat_id or 0)
    mid0 = int(msg_id or 0)

    def _impl() -> None:
        uid = uid0
        cid = cid0
        msg_id = mid0
        ctx = ai_ctx_get(cid, uid)

        def vu_pu() -> tuple[int, int]:
            v = _safe_app_user_id(ctx.get("viewer_uid"))
            p = _safe_app_user_id(ctx.get("partner_uid"))
            return (v or 0), (p or 0)

        if data == "a:v":
            set_input(cid, uid, "ai_viewer_id", {})
            tg_edit(cid, msg_id, t(uid, "ai_prompt_viewer"), [[{"text": t(uid, "cancel"), "callback_data": "m:ai"}]])
            tg_answer_callback(cbq_id)
            return
        if data == "a:p":
            set_input(cid, uid, "ai_partner_id", {})
            tg_edit(cid, msg_id, t(uid, "ai_prompt_partner"), [[{"text": t(uid, "cancel"), "callback_data": "m:ai"}]])
            tg_answer_callback(cbq_id)
            return

        if data in {"a:g", "a:ns"}:
            vu, pu = vu_pu()
            if vu < 1 or pu < 1:
                tg_answer_callback(cbq_id, t(uid, "ai_need_pair"), show_alert=True)
                return
            tg_answer_callback(cbq_id, t(uid, "toast_loading"))
            copilot_body: dict[str, Any] = {"viewer_user_id": vu, "partner_user_id": pu, "locale": "en"}
            # a:g → initial chat-copilot; a:ns → same endpoint with style hint for a fresh batch.
            if data == "a:ns":
                copilot_body["user_selected_style"] = "new_suggestions"
            try:
                payload = backend.request(
                    "POST",
                    "/api/v1/admin/telegram/ai/chat-copilot",
                    json_body=copilot_body,
                )
            except Exception as e:
                tg_edit(cid, msg_id, f"<b>Copilot</b>\n\n<pre>{escape(str(e)[:500])}</pre>", [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
                return
            if not isinstance(payload, dict):
                tg_edit(cid, msg_id, t(uid, "render_error_generic"), [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
                return
            texts, limited, _fb = _extract_copilot_texts(payload)
            ai_ctx_set(cid, uid, last_options=texts, viewer_uid=vu, partner_uid=pu)
            flow = "new_suggestions" if data == "a:ns" else "get_suggestions"
            telegram_track(
                "ai_used",
                telegram_user_id=uid,
                viewer_user_id=vu,
                payload={"endpoint": "chat-copilot", "limited": limited, "flow": flow},
            )
            if limited:
                telegram_track("ai_limit_hit", telegram_user_id=uid, viewer_user_id=vu, payload={"endpoint": "chat-copilot"})
            if not texts:
                tg_edit(
                    cid,
                    msg_id,
                    "<b>Copilot</b>\n\n<i>No lines returned — backend fallback may apply; tap refresh.</i>",
                    [[{"text": t(uid, "ai_new_suggestions"), "callback_data": "a:ns"}, {"text": t(uid, "back"), "callback_data": "m:ai"}]],
                )
                return
            parts = [f"<b>Copilot</b> ({'limited' if limited else 'ok'})"]
            for i, tx in enumerate(texts[:3], start=1):
                parts.append(f"{i}. {escape(tx)}")
            text_out = "\n".join(parts)
            kb: list[list[dict[str, str]]] = []
            for i in range(min(3, len(texts))):
                kb.append([{"text": _short_btn_label(f"{i + 1}. {texts[i]}"), "callback_data": f"a:u:{i}"}])
            kb.append([{"text": t(uid, "ai_new_suggestions"), "callback_data": "a:ns"}, {"text": t(uid, "ai_improve"), "callback_data": "a:im"}])
            kb.append([{"text": t(uid, "ai_meeting_check"), "callback_data": "a:mr"}, {"text": t(uid, "back"), "callback_data": "m:ai"}])
            tg_edit(cid, msg_id, text_out, kb)
            return

        if data.startswith("a:u:"):
            try:
                idx = int(str(data.split(":", 2)[2] or ""))
            except Exception:
                tg_answer_callback(cbq_id, t(uid, "unknown_action"))
                return
            texts = ctx.get("last_options") if isinstance(ctx.get("last_options"), list) else []
            if idx < 0 or idx >= len(texts):
                tg_answer_callback(cbq_id, t(uid, "unknown_action"))
                return
            vu, _pu = vu_pu()
            telegram_track(
                "ai_suggestion_used",
                telegram_user_id=uid,
                viewer_user_id=vu if vu > 0 else None,
                payload={"index": idx, "source": "chat-copilot"},
            )
            tg_edit(
                cid,
                msg_id,
                t(uid, "ai_pick_option", idx=idx + 1) + f"\n\n<pre>{escape(str(texts[idx])[:3500])}</pre>",
                [[{"text": t(uid, "ai_get_suggestions"), "callback_data": "a:g"}, {"text": t(uid, "back"), "callback_data": "m:ai"}]],
            )
            tg_answer_callback(cbq_id)
            return

        if data == "a:im":
            set_input(cid, uid, "ai_improve_text", {})
            tg_edit(cid, msg_id, t(uid, "ai_prompt_improve"), [[{"text": t(uid, "cancel"), "callback_data": "m:ai"}]])
            tg_answer_callback(cbq_id)
            return

        if data == "a:kc":
            tt, kb = render_ai_hub(uid, cid)
            tg_edit(cid, msg_id, tt, kb)
            tg_answer_callback(cbq_id)
            return

        if data.startswith("a:ms:"):
            try:
                mi = int(str(data.split(":", 2)[2] or ""))
            except Exception:
                mi = -1
            vu, _pu = vu_pu()
            telegram_track("ai_suggestion_used", telegram_user_id=uid, viewer_user_id=vu if vu > 0 else None, payload={"index": mi, "source": "meeting-ready"})
            tg_answer_callback(cbq_id, t(uid, "toast_ok"))
            tt, kb = render_ai_hub(uid, cid)
            tg_edit(cid, msg_id, tt, kb)
            return

        if data == "a:mr":
            vu, pu = vu_pu()
            if vu < 1 or pu < 1:
                tg_answer_callback(cbq_id, t(uid, "ai_need_pair"), show_alert=True)
                return
            tg_answer_callback(cbq_id, t(uid, "toast_loading"))
            try:
                payload = backend.request(
                    "POST",
                    "/api/v1/admin/telegram/ai/meeting-ready",
                    json_body={"viewer_user_id": vu, "partner_user_id": pu, "locale": "en"},
                )
            except Exception as e:
                tg_edit(cid, msg_id, f"<b>Meeting ready</b>\n\n<pre>{escape(str(e)[:500])}</pre>", [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
                return
            if not isinstance(payload, dict):
                tg_edit(cid, msg_id, t(uid, "render_error_generic"), [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
                return
            score = int(payload.get("readiness_score") or 0)
            warm = bool(payload.get("telegram_closer_hint"))
            sugg = [str(x or "").strip() for x in (payload.get("suggestions") or []) if str(x or "").strip()][:3]
            telegram_track("ai_used", telegram_user_id=uid, viewer_user_id=vu, payload={"endpoint": "meeting-ready", "score": score})
            if warm and sugg:
                lines = [f"<b>{t(uid, 'ai_closer_hot')}</b>", f"score=<code>{score}</code>", ""]
                for i, s in enumerate(sugg, start=1):
                    lines.append(f"{i}. {escape(s)}")
                kb2: list[list[dict[str, str]]] = []
                for i in range(len(sugg)):
                    kb2.append([{"text": _short_btn_label(f"📅 {sugg[i]}"), "callback_data": f"a:ms:{i}"}])
                kb2.append([{"text": t(uid, "ai_keep_chatting"), "callback_data": "a:kc"}, {"text": t(uid, "back"), "callback_data": "m:ai"}])
                tg_edit(cid, msg_id, "\n".join(lines), kb2)
                return
            lines2 = [f"<b>Meeting readiness</b>", f"score=<code>{score}</code>", ""]
            if sugg:
                for i, s in enumerate(sugg, start=1):
                    lines2.append(f"{i}. {escape(s)}")
            else:
                lines2.append("<i>No meeting lines yet — keep building rapport.</i>")
            tg_edit(cid, msg_id, "\n".join(lines2), [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
            return

        if data == "a:ss":
            vu, pu = vu_pu()
            if vu < 1 or pu < 1:
                tg_answer_callback(cbq_id, t(uid, "ai_need_pair"), show_alert=True)
                return
            tg_answer_callback(cbq_id, t(uid, "toast_loading"))
            try:
                payload = backend.request(
                    "POST",
                    "/api/v1/admin/telegram/ai/start-strategy",
                    json_body={"viewer_user_id": vu, "partner_user_id": pu, "locale": "en"},
                )
            except Exception as e:
                tg_edit(cid, msg_id, f"<b>Start strategy</b>\n\n<pre>{escape(str(e)[:500])}</pre>", [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
                return
            if not isinstance(payload, dict):
                tg_edit(cid, msg_id, t(uid, "render_error_generic"), [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
                return
            strat = escape(str(payload.get("strategy") or ""))
            hooks = payload.get("hooks") if isinstance(payload.get("hooks"), list) else []
            openers = payload.get("openers") if isinstance(payload.get("openers"), list) else []
            hm = f"<b>Start strategy</b>\n\n{strat}\n\n<b>hooks</b>\n<pre>{escape(json.dumps(hooks, ensure_ascii=False)[:800])}</pre>\n<b>openers</b>\n"
            for o in openers[:3]:
                if isinstance(o, dict):
                    hm += f"• {escape(str(o.get('text') or ''))}\n"
            telegram_track("ai_used", telegram_user_id=uid, viewer_user_id=vu, payload={"endpoint": "start-strategy"})
            tg_edit(cid, msg_id, hm, [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
            return

        if data in {"a:tn", "a:te"}:
            vu, pu = vu_pu()
            if vu < 1 or pu < 1:
                tg_answer_callback(cbq_id, t(uid, "ai_need_pair"), show_alert=True)
                return
            # a:tn → timed-replies nudge_type "now"; a:te → "reengage"
            nudge = "now" if data == "a:tn" else "reengage"
            tg_answer_callback(cbq_id, t(uid, "toast_loading"))
            try:
                payload = backend.request(
                    "POST",
                    "/api/v1/admin/telegram/ai/timed-replies",
                    json_body={"viewer_user_id": vu, "partner_user_id": pu, "nudge_type": nudge, "locale": "en"},
                )
            except Exception as e:
                tg_edit(cid, msg_id, f"<b>Timed replies</b>\n\n<pre>{escape(str(e)[:500])}</pre>", [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
                return
            texts = _extract_timed_texts(payload) if isinstance(payload, dict) else []
            telegram_track("ai_used", telegram_user_id=uid, viewer_user_id=vu, payload={"endpoint": "timed-replies", "nudge": nudge})
            if not texts:
                tg_edit(cid, msg_id, "<b>Timed replies</b>\n\n<i>No lines — check match/thread.</i>", [[{"text": t(uid, "back"), "callback_data": "m:ai"}]])
                return
            parts = [f"<b>Timed ({nudge})</b>"]
            for i, tx in enumerate(texts[:3], start=1):
                parts.append(f"{i}. {escape(tx)}")
            kb3 = [[{"text": t(uid, "back"), "callback_data": "m:ai"}]]
            tg_edit(cid, msg_id, "\n".join(parts), kb3)
            return

        tg_answer_callback(cbq_id, t(uid, "unknown_action"))

    try:
        _impl()
    except Exception:
        _log_callback_exception(data)
        try:
            tg_edit(
                cid0,
                mid0,
                f"<b>{escape(TG_CALLBACK_FALLBACK_MSG)}</b>",
                [[{"text": t(uid0, "back"), "callback_data": "m:ai"}]],
            )
        except Exception:
            pass
        try:
            tg_answer_callback(cbq_id)
        except Exception:
            pass


def route_callback(data: str, chat_id: int, msg_id: int, user_id: int, cbq_id: str) -> None:
    global alerts_muted_until
    if not is_admin(user_id):
        tg_answer_callback(cbq_id, t(user_id, "access_denied"))
        return

    if data.startswith("e:"):
        parsed = parse_engagement_generate_callback(data)
        if not parsed:
            tg_answer_callback(cbq_id, t(user_id, "unknown_action"))
            return
        api_kind, screen, mid, refresh_cb = parsed
        back_cb = ENGAGEMENT_SCREEN_BACK.get(screen, "m:engagement")
        mk = ENGAGEMENT_SCREEN_MENU_KEY.get(screen, "engagement")
        try:
            payload = backend.request(
                "POST",
                "/api/v1/admin/engagement/generate",
                json_body={"match_id": mid, "kind": api_kind, "use_ai": True},
            )
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                text, kb = fallback_render_ui(user_id, t(user_id, "engagement_generate_failed"), back_cb)
            else:
                text, kb = render_engagement_generated_detail(user_id, api_kind, payload, back_cb, refresh_cb)
                kb = _inject_ai_help(kb, "engagement", user_id, mk)
                try:
                    telegram_track(
                        "shipment_created",
                        telegram_user_id=int(user_id or 0),
                        viewer_user_id=None,
                        payload={"source": "telegram_engagement_generate", "match_id": int(mid)},
                    )
                except Exception:
                    pass
        except Exception:
            text, kb = fallback_render_ui(user_id, t(user_id, "render_error_generic"), back_cb)
        tg_edit(chat_id, msg_id, text, kb)
        tg_answer_callback(cbq_id)
        return

    if data.startswith("a:"):
        _route_ai_product_callbacks(data, chat_id, msg_id, user_id, cbq_id)
        return

    if data.startswith("m:"):
        key = data.split(":", 1)[1]
        text = ""
        kb: list[list[dict[str, str]]] = []
        try:
            if key == "home":
                if int(user_id) not in admin_lang:
                    text, kb = render_language_picker(user_id)
                else:
                    text, kb = render_home(user_id)
            elif key == "command_center":
                text, kb = render_home(user_id)
            elif key == "more":
                text, kb = render_more_menu(user_id)
            elif key == "ai":
                text, kb = render_ai_hub(user_id, chat_id)
            elif key == "orders":
                text, kb = render_orders_hub(user_id)
            elif key == "shipments":
                text, kb = render_shipments_hub(user_id)
            elif key == "analytics_hub":
                text, kb = render_analytics_hub(user_id)
            elif key == "settings_hub":
                text, kb = render_settings_hub(user_id)
            elif key == "diag":
                text, kb = render_product_diagnostics(user_id)
            elif key == "full_analysis":
                text, kb = render_full_system_analysis(user_id)
            elif key == "stats":
                text, kb = render_statistics(user_id)
            elif key == "stats_today":
                text, kb = render_statistics_period(user_id, "today")
            elif key == "stats_7d":
                text, kb = render_statistics_period(user_id, "7d")
            elif key == "stats_30d":
                text, kb = render_statistics_period(user_id, "30d")
            elif key == "aiq":
                text, kb = render_ai_quality(user_id)
            elif key == "l10n":
                text, kb = render_localization(user_id)
            elif key == "l10n_agent":
                text, kb = render_localization_agent(user_id)
            elif key == "l10n_coverage":
                text, kb = render_localization_coverage(user_id)
            elif key == "system":
                text, kb = render_system(user_id)
            elif key == "system_doctor":
                text, kb = render_system(user_id)
            elif key == "last_errors":
                text, kb = render_last_errors(user_id)
            elif key == "users":
                set_input(chat_id, user_id, "user_search", {})
                text, kb = render_users_search_prompt(user_id)
            elif key == "safety":
                text, kb = render_safety_menu(user_id)
            elif key == "reports_open":
                text, kb = render_reports_list(user_id, "open")
            elif key == "reports_resolved":
                text, kb = render_reports_list(user_id, "resolved")
            elif key == "premium":
                text, kb = render_premium_menu(user_id)
            elif key == "premium_overview":
                text, kb = render_premium_overview(user_id)
            elif key == "premium_expiring":
                text, kb = render_premium_expiring(user_id)
            elif key == "match_quality":
                text, kb = render_match_quality_menu(user_id)
            elif key == "match_quality_overview":
                text, kb = render_match_quality_overview(user_id)
            elif key == "match_quality_weak":
                text, kb = render_match_quality_weak(user_id)
            elif key == "match_quality_dead":
                text, kb = render_match_quality_dead(user_id)
            elif key == "match_quality_recompute":
                set_confirm(chat_id, user_id, "match_quality_recompute", {})
                text = t(user_id, "confirm_match_recompute_html")
                kb = [
                    [
                        {"text": t(user_id, "confirm"), "callback_data": "x:match_quality_recompute_yes"},
                        {"text": t(user_id, "cancel"), "callback_data": "m:match_quality"},
                    ]
                ]
            elif key == "lang":
                text, kb = render_language_picker(user_id)
            elif key == "conversation_quality":
                text, kb = render_conversation_quality_menu(user_id)
            elif key == "conversation_quality_today":
                text, kb = render_conversation_quality_overview(user_id, "today")
            elif key == "conversation_quality_7d":
                text, kb = render_conversation_quality_overview(user_id, "7d")
            elif key == "conversation_quality_30d":
                text, kb = render_conversation_quality_overview(user_id, "30d")
            elif key == "conversation_quality_issues":
                text, kb = render_conversation_quality_issues(user_id)
            elif key == "growth":
                text, kb = render_growth_menu(user_id)
            elif key == "growth_today":
                text, kb = render_growth_overview(user_id, "today")
            elif key == "growth_7d":
                text, kb = render_growth_overview(user_id, "7d")
            elif key == "growth_30d":
                text, kb = render_growth_overview(user_id, "30d")
            elif key == "growth_recs":
                text, kb = render_growth_recommendations(user_id)
            elif key == "engagement":
                text, kb = render_engagement_menu(user_id)
            elif key == "engagement_overview":
                text, kb = render_engagement_overview(user_id)
            elif key == "engagement_actions":
                text, kb = render_engagement_suggested_actions(user_id)
            elif key == "engagement_revive":
                text, kb = render_engagement_revive(user_id)
            elif key == "engagement_first_boost":
                text, kb = render_engagement_first_boost(user_id)
            elif key == "engagement_ai_suggestions":
                text, kb = render_engagement_ai_suggestions(user_id)
            elif key == "engagement_style_learning_today":
                text, kb = render_engagement_style_learning(user_id, "today")
            elif key in {"engagement_style_learning", "engagement_style_learning_7d"}:
                text, kb = render_engagement_style_learning(user_id, "7d")
            elif key == "engagement_style_learning_30d":
                text, kb = render_engagement_style_learning(user_id, "30d")
            elif key == "pm":
                text, kb = render_product_manager_menu(user_id)
            elif key == "pm_today":
                text, kb = render_product_manager_brief(user_id, "today")
            elif key == "pm_7d":
                text, kb = render_product_manager_brief(user_id, "7d")
            elif key == "pm_30d":
                text, kb = render_product_manager_brief(user_id, "30d")
            elif key == "pm_risks":
                text, kb = render_product_manager_risks(user_id)
            elif key == "pm_next":
                text, kb = render_product_manager_next_actions(user_id)
            elif key == "cto":
                text, kb = render_cto_menu(user_id)
            elif key == "cto_today":
                text, kb = render_cto_roadmap(user_id, "today")
            elif key == "cto_7d":
                text, kb = render_cto_roadmap(user_id, "7d")
            elif key == "cto_30d":
                text, kb = render_cto_roadmap(user_id, "30d")
            elif key == "cto_risks":
                text, kb = render_cto_risks(user_id)
            elif key == "cto_next":
                text, kb = render_cto_next_actions(user_id)
            elif key == "menu_qa":
                text, kb = render_menu_qa_menu(user_id)
            elif key == "menu_qa_run":
                text, kb = _menu_qa_render(user_id, "all")
            elif key == "menu_qa_critical":
                text, kb = _menu_qa_render(user_id, "critical")
            elif key == "menu_qa_warnings":
                text, kb = _menu_qa_render(user_id, "warnings")
            elif key == "menu_qa_missing_tr":
                text, kb = _menu_qa_render(user_id, "missing_tr")
            elif key == "e2e_qa":
                text, kb = render_e2e_qa_menu(user_id)
            elif key == "e2e_qa_run":
                text, kb = _e2e_qa_render(user_id, "all")
            elif key == "e2e_qa_critical":
                text, kb = _e2e_qa_render(user_id, "critical")
            elif key == "e2e_qa_warnings":
                text, kb = _e2e_qa_render(user_id, "warnings")
            elif key == "e2e_qa_last":
                text, kb = _e2e_qa_render(user_id, "all")
            elif key == "qa_agent":
                text, kb = render_full_product_qa_menu(user_id)
            elif key == "full_product_qa_run":
                text, kb = _full_product_qa_choose(user_id)
            elif key == "full_product_qa_quick":
                tg_answer_callback(cbq_id, t(user_id, "qa_running"))
                text, kb = _full_product_qa_run(user_id, kind="quick_product")
            elif key == "full_product_qa_deep":
                tg_answer_callback(cbq_id, t(user_id, "qa_running"))
                text, kb = _full_product_qa_run(user_id, kind="deep_product")
            elif key == "deep_product_qa_run":
                tg_answer_callback(cbq_id, t(user_id, "qa_running"))
                text, kb = _full_product_qa_run(user_id, kind="deep_product")
            elif key == "full_product_qa_fix_top":
                text, kb = _full_product_qa_fix_top(user_id)
            elif key == "qa_en":
                tg_answer_callback(cbq_id, t(user_id, "qa_running"))
                text, kb = _qa_agent_run(user_id, "english_ux")
            elif key == "qa_l10n":
                tg_answer_callback(cbq_id, t(user_id, "qa_running"))
                text, kb = _qa_agent_run(user_id, "localization")
            elif key == "qa_chat":
                tg_answer_callback(cbq_id, t(user_id, "qa_running"))
                text, kb = _qa_agent_run(user_id, "chat")
            elif key == "qa_menu":
                tg_answer_callback(cbq_id, t(user_id, "qa_running"))
                text, kb = _qa_agent_run(user_id, "menu")
            elif key == "qa_bot2bot":
                tg_answer_callback(cbq_id, t(user_id, "qa_running"))
                text, kb = _qa_agent_run(user_id, "bot2bot")
            elif key == "qa_last_summary":
                text, kb = _qa_agent_last(user_id, "summary")
            elif key == "qa_last_fixes":
                text, kb = _qa_agent_last(user_id, "fixes")
            elif key == "qa_last_deep":
                text, kb = _qa_agent_last(user_id, "deep")
            elif key == "demo":
                text, kb = render_demo_mode_menu(user_id)
            elif key == "demo_metrics":
                text, kb = render_demo_mode_metrics(user_id)
            elif key == "demo_behavior":
                text, kb = render_demo_behavior_menu(user_id)
            elif key == "founder":
                text, kb = render_founder_menu(user_id)
            elif key == "founder_daily":
                text, kb = render_founder_daily(user_id)
            elif key == "founder_alerts":
                text, kb = render_founder_alerts(user_id)
            elif key == "founder_focus":
                text, kb = render_founder_focus(user_id)
            elif key == "autopilot":
                text, kb = render_autopilot_menu(user_id)
            elif key == "autopilot_suggestions":
                text, kb = render_autopilot_suggestions(user_id)
            elif key == "autopilot_actions":
                text, kb = render_autopilot_actions(user_id)
            elif key == "alerts":
                text, kb = render_alerts_menu(user_id)
            elif key == "alerts_active":
                text, kb = render_active_alerts(user_id)
            elif key == "backups":
                text, kb = render_backup_center(user_id)
            elif key == "backups_list":
                text, kb = render_backup_list(user_id)
            elif key == "backups_restore":
                text, kb = render_backup_restore_select(user_id)
            elif key == "audit":
                text, kb = render_audit_menu(user_id)
            elif key == "audit_last":
                text, kb = render_audit_log(user_id, "")
            elif key == "audit_premium":
                text, kb = render_audit_log(user_id, "premium")
            elif key == "audit_user":
                text, kb = render_audit_log(user_id, "user")
            elif key == "audit_system":
                text, kb = render_audit_log(user_id, "system")
            elif key == "audit_safety":
                text, kb = render_audit_log(user_id, "safety")
            elif key == "release":
                text, kb = render_release_menu(user_id)
            elif key == "release_readiness":
                text, kb = render_release_readiness(user_id)
            elif key == "release_blockers":
                text, kb = render_release_readiness(user_id, "blockers")
            elif key == "release_warnings":
                text, kb = render_release_readiness(user_id, "warnings")
            else:
                text, kb = (t(user_id, "section_stub", key=escape(key)), back_btn(user_id, "home"))
        except Exception:
            text, kb = fallback_render_ui(int(user_id or 0), t(int(user_id or 0), "render_error_generic"), "m:home")

        sec_slug = AI_HELP_MENU_TO_SECTION.get(key)
        if sec_slug and isinstance(kb, list):
            kb = _inject_ai_help(kb, sec_slug, user_id, key)
        tg_edit(chat_id, msg_id, text, kb)
        tg_answer_callback(cbq_id)
        return

    if data.startswith("ai_help:"):
        rest = str(data[8:] or "").strip()
        back_map = {
            "command_center": "m:home",
            "more_menu": "m:more",
            "statistics": "m:stats",
            "users": "m:users",
            "safety": "m:safety",
            "premium": "m:premium",
            "match_quality": "m:match_quality",
            "conversation_quality": "m:conversation_quality",
            "growth": "m:growth",
            "product_manager": "m:pm",
            "cto": "m:cto",
            "autopilot": "m:autopilot",
            "founder": "m:founder",
            "alerts": "m:alerts",
            "system": "m:system",
            "backup": "m:backups",
            "audit": "m:audit",
            "release": "m:release",
            "menu_qa": "m:menu_qa",
            "e2e_qa": "m:e2e_qa",
            "localization": "m:l10n",
            "full_analysis": "m:more",
            "ai_quality": "m:aiq",
            "engagement": "m:engagement",
            "demo_mode": "m:demo",
            "demo_behavior": "m:demo_behavior",
        }
        if "~" in rest:
            sec, back_key = rest.split("~", 1)
            sec = sec.strip().lower()
            back_key = back_key.strip()
            back_cb = f"m:{back_key}" if back_key and not back_key.startswith("m:") else (back_key or "m:home")
        else:
            sec = rest.strip().lower()
            back_cb = back_map.get(sec, "m:home")
        text, kb = _render_ai_help(user_id, sec, back_cb, data[:64])
        tg_edit(chat_id, msg_id, text, kb)
        tg_answer_callback(cbq_id)
        return

    if data.startswith("r:"):
        rid = int(data.split(":", 1)[1] or 0)
        try:
            text, kb = render_report_detail(user_id, rid)
        except Exception:
            text, kb = fallback_render_ui(int(user_id or 0), t(int(user_id or 0), "render_error_generic"), "m:reports_open")
        tg_edit(chat_id, msg_id, text, kb)
        tg_answer_callback(cbq_id)
        return

    if data.startswith("u:"):
        uid_target = int(data.split(":", 1)[1] or 0)
        try:
            text, kb = render_user_details(user_id, uid_target)
        except Exception:
            text, kb = fallback_render_ui(int(user_id or 0), t(int(user_id or 0), "render_error_generic"), "m:users")
        tg_edit(chat_id, msg_id, text, kb)
        tg_answer_callback(cbq_id)
        return

    # Confirm prompts
    if data.startswith("c:auto:"):
        action_id = str(data.split(":", 2)[2] or "").strip()
        if action_id not in AUTOPILOT_ACTIONS:
            tg_answer_callback(cbq_id, t(user_id, "unknown_action"))
            return
        set_confirm(chat_id, user_id, f"autopilot:{action_id}", {})
        try:
            text, kb = render_autopilot_confirm(user_id, action_id)
        except Exception:
            text, kb = fallback_render_ui(int(user_id or 0), t(int(user_id or 0), "render_error_generic"), "m:autopilot")
        tg_edit(chat_id, msg_id, text, kb)
        tg_answer_callback(cbq_id)
        return

    if data == "c:backup_create":
        set_confirm(chat_id, user_id, "backup_create", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "backup_center_title_plain"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:backup_create_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:backups"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data.startswith("c:backup_restore:"):
        filename = _backup_filename(data.split(":", 2)[2])
        if not filename:
            tg_answer_callback(cbq_id, t(user_id, "unknown_action"))
            return
        set_input(chat_id, user_id, "backup_restore_phrase", {"filename": filename, "message_id": msg_id})
        text, kb = render_backup_restore_warning(user_id, filename)
        tg_edit(chat_id, msg_id, text, kb)
        tg_answer_callback(cbq_id)
        return

    if data == "c:release_mark":
        set_input(chat_id, user_id, "release_mark", {"message_id": msg_id})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "release_mark_html"),
            [[{"text": t(user_id, "cancel"), "callback_data": "m:release"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:l10n_fix":
        set_confirm(chat_id, user_id, "l10n_fix", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_l10n_fix_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:l10n_fix_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:l10n"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:lagent_fix":
        set_confirm(chat_id, user_id, "lagent_fix", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_lagent_fix_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:lagent_fix_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:l10n_agent"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:demo_enable":
        set_confirm(chat_id, user_id, "demo_enable", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "telegram.demo.confirmEnable_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:demo_enable_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:demo"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:demo_disable":
        set_confirm(chat_id, user_id, "demo_disable", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "telegram.demo.confirmDisable_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:demo_disable_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:demo"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:demo_regen":
        set_confirm(chat_id, user_id, "demo_regen", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "telegram.demo.confirmRegenerate_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:demo_regen_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:demo"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:demo_clear":
        set_confirm(chat_id, user_id, "demo_clear", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "telegram.demo.confirmClear_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:demo_clear_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:demo"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:demo_live_enable":
        set_confirm(chat_id, user_id, "demo_live_enable", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "telegram.demo.confirmLiveOn_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:demo_live_enable_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:demo_behavior"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:demo_live_disable":
        set_confirm(chat_id, user_id, "demo_live_disable", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "telegram.demo.confirmLiveOff_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:demo_live_disable_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:demo_behavior"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:demo_regen_personalities":
        set_confirm(chat_id, user_id, "demo_regen_personalities", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "telegram.demo.confirmRegenPersonalities_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:demo_regen_personalities_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:demo_behavior"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:demo_speed_fast":
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/live-behavior", json_body={"confirm": True, "speed": "fast"})
        text, kb = render_demo_behavior_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "c:demo_speed_normal":
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/live-behavior", json_body={"confirm": True, "speed": "normal"})
        text, kb = render_demo_behavior_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "c:demo_speed_slow":
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/live-behavior", json_body={"confirm": True, "speed": "slow"})
        text, kb = render_demo_behavior_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "c:demo_ignore_down":
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request(
            "POST",
            "/api/v1/admin/demo-mode/live-behavior",
            json_body={"confirm": True, "ignore_rate_delta": -0.05},
        )
        text, kb = render_demo_behavior_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "c:demo_ignore_up":
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request(
            "POST",
            "/api/v1/admin/demo-mode/live-behavior",
            json_body={"confirm": True, "ignore_rate_delta": 0.05},
        )
        text, kb = render_demo_behavior_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "c:backup_db":
        set_confirm(chat_id, user_id, "backup_db", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_backup_db_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:backup_db_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:system_doctor"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:clear_cache":
        set_confirm(chat_id, user_id, "clear_cache", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_clear_cache_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:clear_cache_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:system_doctor"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:run_migrations":
        set_confirm(chat_id, user_id, "run_migrations", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_run_migrations_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:run_migrations_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:system_doctor"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data.startswith("c:prem:"):
        _, _, uid_s, days_s = data.split(":", 3)
        uid = int(uid_s)
        days = int(days_s)
        set_confirm(chat_id, user_id, f"grant_premium:{uid}:{days}", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_grant_premium_html", days=days, uid=uid),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:prem_yes:{uid}:{days}"}, {"text": t(user_id, "cancel"), "callback_data": f"u:{uid}"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data.startswith("c:revoke:"):
        uid = int(data.split(":", 2)[2])
        set_confirm(chat_id, user_id, f"revoke_premium:{uid}", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_revoke_premium_html", uid=uid),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:revoke_yes:{uid}"}, {"text": t(user_id, "cancel"), "callback_data": f"u:{uid}"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data.startswith("c:memreset:"):
        uid = int(data.split(":", 2)[2])
        set_confirm(chat_id, user_id, f"reset_mem:{uid}", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_memreset_html", uid=uid),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:memreset_yes:{uid}"}, {"text": t(user_id, "cancel"), "callback_data": f"u:{uid}"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data.startswith("c:ban:"):
        uid = int(data.split(":", 2)[2])
        set_input(chat_id, user_id, "ban_reason", {"target_user_id": uid, "message_id": msg_id})
        tg_edit(chat_id, msg_id, t(user_id, "ban_request_html", uid=uid), [[{"text": t(user_id, "cancel"), "callback_data": f"u:{uid}"}]])
        tg_answer_callback(cbq_id)
        return

    if data.startswith("c:rep_dismiss:"):
        rid = int(data.split(":", 2)[2])
        set_confirm(chat_id, user_id, f"rep_dismiss:{rid}", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_rep_dismiss_html", rid=rid),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:rep_dismiss_yes:{rid}"}, {"text": t(user_id, "cancel"), "callback_data": f"r:{rid}"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data.startswith("c:rep_ban:"):
        _, _, rid_s, uid_s = data.split(":", 3)
        rid = int(rid_s)
        uid = int(uid_s)
        set_confirm(chat_id, user_id, f"rep_ban:{rid}:{uid}", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_rep_ban_html", rid=rid, uid=uid),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:rep_ban_yes:{rid}:{uid}"}, {"text": t(user_id, "cancel"), "callback_data": f"r:{rid}"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:premium_grant_all":
        set_confirm(chat_id, user_id, "premium_grant_all", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_premium_grant_all_html"),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:premium_grant_all_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:premium"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "c:promo_create":
        set_input(chat_id, user_id, "promo_create", {"message_id": msg_id})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "promo_create_instructions"),
            [[{"text": t(user_id, "cancel"), "callback_data": "m:premium"}]],
        )
        tg_answer_callback(cbq_id)
        return

    if data == "x:alerts_mute_1h":
        alerts_muted_until = time.time() + 60 * 60
        tg_answer_callback(cbq_id, t(user_id, "toast_muted_1h"))
        text, kb = render_alerts_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "x:alerts_unmute":
        alerts_muted_until = 0.0
        tg_answer_callback(cbq_id, t(user_id, "toast_unmuted"))
        text, kb = render_alerts_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data.startswith("x:lang:"):
        lang = str(data.split(":", 2)[2] or "").strip().lower()
        if lang not in {"uk", "en"}:
            lang = "en"
        admin_lang[int(user_id)] = lang
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        text, kb = render_home(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data.startswith("c:unban:"):
        uid = int(data.split(":", 2)[2])
        set_confirm(chat_id, user_id, f"unban:{uid}", {})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "confirm_unban_html", uid=uid),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:unban_yes:{uid}"}, {"text": t(user_id, "cancel"), "callback_data": f"u:{uid}"}]],
        )
        tg_answer_callback(cbq_id)
        return

    # Actions
    if data.startswith("x:auto:"):
        action_id = str(data.split(":", 2)[2] or "").strip()
        if action_id not in AUTOPILOT_ACTIONS:
            tg_answer_callback(cbq_id, t(user_id, "unknown_action"))
            return
        if not pop_confirm(chat_id, user_id, f"autopilot:{action_id}"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_executing"))
        out = backend.request("POST", "/api/v1/admin/autopilot/execute", json_body={"action_id": action_id, "confirm": True})
        title = _autopilot_action_label(user_id, action_id)
        tg_edit(
            chat_id,
            msg_id,
            f"<b>{escape(t(user_id, 'autopilot'))}</b>\n\n{t(user_id, 'autopilot_tool_prefix')}{escape(title)}\n\n" + fmt_json_block(user_id, out),
            [[{"text": t(user_id, "back"), "callback_data": "m:autopilot"}]],
        )
        return

    if data == "x:backup_create_yes":
        if not pop_confirm(chat_id, user_id, "backup_create"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id)
        back_kb = [[{"text": t(user_id, "back"), "callback_data": "m:backups"}]]
        status_mid: int | None = None
        try:
            status_mid = tg_send(chat_id, t(user_id, "backup_status_creating"))
        except Exception:
            status_mid = None
        t0 = time.monotonic()
        try:
            out = backend.request("POST", "/api/v1/admin/backups/create", json_body={"confirm": True})
        except BaseException as e:
            elapsed = time.monotonic() - t0
            reason = escape(_format_backup_create_error(e))
            err_html = (
                f"<b>{escape(t(user_id, 'backup_status_failed'))}</b>\n\n"
                f"{reason}\n\n"
                f"<b>{escape(t(user_id, 'backup_field_duration'))}</b>: {elapsed:.1f}s"
            )
            _tg_edit_or_send_fallback(chat_id, status_mid, err_html, back_kb)
            return
        elapsed = time.monotonic() - t0
        if not isinstance(out, dict) or not out.get("success") or not str(out.get("filename") or "").strip():
            reason = escape(t(user_id, "backup_api_invalid_response"))
            err_html = (
                f"<b>{escape(t(user_id, 'backup_status_failed'))}</b>\n\n"
                f"{reason}\n\n"
                f"<b>{escape(t(user_id, 'backup_field_duration'))}</b>: {elapsed:.1f}s"
            )
            _tg_edit_or_send_fallback(chat_id, status_mid, err_html, back_kb)
            return
        fn_raw = str(out.get("filename") or "").strip()
        sz_num = out.get("size")
        if sz_num is None:
            sz_num = out.get("size_bytes")
        sz_disp = _format_backup_size_bytes(sz_num)
        dur_s = out.get("duration_seconds")
        if dur_s is None:
            dur_s = out.get("duration")
        try:
            dur_show = float(dur_s) if dur_s is not None else elapsed
        except (TypeError, ValueError):
            dur_show = elapsed
        fn_line = escape(fn_raw)
        lines = [
            f"<b>{escape(t(user_id, 'backup_status_created'))}</b>",
            "",
            f"<b>{escape(t(user_id, 'backup_field_file'))}</b>: {fn_line}",
        ]
        if sz_disp:
            lines.append(f"<b>{escape(t(user_id, 'backup_field_size'))}</b>: {escape(sz_disp)}")
        lines.append(f"<b>{escape(t(user_id, 'backup_field_duration'))}</b>: {dur_show:.1f}s")
        ok_html = "\n".join(lines)
        _tg_edit_or_send_fallback(chat_id, status_mid, ok_html, back_kb)
        return

    if data == "x:backup_export_latest":
        filename = _latest_backup_filename()
        if not filename:
            tg_answer_callback(cbq_id, t(user_id, "toast_no_backups"))
            text, kb = render_backup_list(user_id)
            tg_edit(chat_id, msg_id, text, kb)
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_exporting"))
        dl_name, content = backend.download(f"/api/v1/admin/backups/{filename}/download")
        tg_send_document(chat_id, dl_name, content, caption=f"🗄 NEYRA backup: {escape(filename)}")
        text, kb = render_backup_center(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data.startswith("x:backup_restore:"):
        filename = _backup_filename(data.split(":", 2)[2])
        if not filename:
            tg_answer_callback(cbq_id, t(user_id, "unknown_action"))
            return
        if not pop_confirm(chat_id, user_id, f"backup_restore:{filename}"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_restoring"))
        out = backend.request(
            "POST",
            f"/api/v1/admin/backups/{filename}/restore",
            json_body={"confirm": True, "confirm_phrase": BACKUP_RESTORE_PHRASE},
        )
        tg_edit(chat_id, msg_id, t(user_id, "result_backup_restored") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:backups"}]])
        return

    if data == "x:release_mark_yes":
        conf = pop_confirm(chat_id, user_id, "release_mark")
        if not conf:
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        payload = conf.get("payload") or {}
        tg_answer_callback(cbq_id, t(user_id, "toast_marking_release"))
        out = backend.request(
            "POST",
            "/api/v1/admin/release/mark",
            json_body={"version": payload.get("version"), "notes": payload.get("notes"), "confirm": True},
        )
        tg_edit(chat_id, msg_id, t(user_id, "result_release_marked") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:release"}]])
        return

    if data == "x:l10n_cov_miss":
        tg_answer_callback(cbq_id, t(user_id, "toast_loading"))
        cov_doc = backend.request("GET", "/api/v1/admin/localization/coverage")
        rows = [x for x in (cov_doc.get("locales") or []) if isinstance(x, dict) and x.get("code") != "en"]
        rows.sort(key=lambda r: (int(r.get("missing") or 0) + int(r.get("empty") or 0)), reverse=True)
        body = [
            {
                "code": r.get("code"),
                "missing": r.get("missing"),
                "empty": r.get("empty"),
                "top_missing_keys": (r.get("top_missing_keys") or [])[:12],
            }
            for r in rows[:14]
        ]
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "l10n_top_missing_title") + "\n" + fmt_json_block(user_id, body, max_len=3500),
            [[{"text": t(user_id, "back"), "callback_data": "m:l10n_coverage"}]],
        )
        return

    if data == "x:l10n_cov_fix":
        tg_answer_callback(cbq_id, t(user_id, "toast_loading"))
        cov_doc = backend.request("GET", "/api/v1/admin/localization/coverage")
        rows = [x for x in (cov_doc.get("locales") or []) if isinstance(x, dict) and x.get("code") != "en"]
        rows.sort(key=lambda r: int(r.get("identical_to_en") or 0), reverse=True)
        body = [
            {
                "code": r.get("code"),
                "identical_to_en": r.get("identical_to_en"),
                "top_identical_to_en_keys": (r.get("top_identical_to_en_keys") or [])[:12],
            }
            for r in rows[:14]
        ]
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "l10n_fix_suggestions_still_en") + "\n" + fmt_json_block(user_id, body, max_len=3500),
            [[{"text": t(user_id, "back"), "callback_data": "m:l10n_coverage"}]],
        )
        return

    if data == "x:l10n_scan":
        tg_answer_callback(cbq_id, t(user_id, "toast_scan_running"))
        out = backend.request("POST", "/api/v1/admin/localization/scan")
        tg_edit(chat_id, msg_id, f"<b>{escape(t(user_id, 'l10n_geo_title'))}</b>\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:l10n"}]])
        return

    if data == "x:l10n_fix_yes":
        if not pop_confirm(chat_id, user_id, "l10n_fix"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_safe_fix"))
        out = backend.request("POST", "/api/v1/admin/localization/fix", json_body={"confirm": True})
        tg_edit(chat_id, msg_id, f"<b>{escape(t(user_id, 'l10n_geo_title'))}</b>\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:l10n"}]])
        return

    if data == "x:lagent_scan":
        tg_answer_callback(cbq_id, t(user_id, "toast_scan_short"))
        out = backend.request("GET", "/api/v1/admin/localization-agent/scan")
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "l10n_agent_scan_result") + fmt_json_block(user_id, out),
            [[{"text": t(user_id, "back"), "callback_data": "m:l10n_agent"}]],
        )
        return

    if data == "x:lagent_missing":
        tg_answer_callback(cbq_id, t(user_id, "toast_loading"))
        scan = backend.request("GET", "/api/v1/admin/localization-agent/scan")
        body = _lagent_filtered_scan(scan, "missing_keys")
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "l10n_agent_missing_title") + "\n" + fmt_json_block(user_id, body),
            [[{"text": t(user_id, "back"), "callback_data": "m:l10n_agent"}]],
        )
        return

    if data == "x:lagent_cities":
        tg_answer_callback(cbq_id, t(user_id, "toast_loading"))
        scan = backend.request("GET", "/api/v1/admin/localization-agent/scan")
        body = _lagent_filtered_scan(scan, "bad_city_cases")
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "l10n_agent_bad_cities_title") + fmt_json_block(user_id, body),
            [[{"text": t(user_id, "back"), "callback_data": "m:l10n_agent"}]],
        )
        return

    if data == "x:lagent_fix_yes":
        if not pop_confirm(chat_id, user_id, "lagent_fix"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_lagent_fix"))
        out = backend.request("POST", "/api/v1/admin/localization-agent/fix", json_body={"confirm": True, "mode": "safe"})
        tg_edit(
            chat_id,
            msg_id,
            t(user_id, "l10n_agent_safe_fix_title") + fmt_json_block(user_id, out),
            [[{"text": t(user_id, "back"), "callback_data": "m:l10n_agent"}]],
        )
        return

    if data == "x:demo_enable_yes":
        if not pop_confirm(chat_id, user_id, "demo_enable"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/toggle", json_body={"enabled": True, "confirm": True})
        text, kb = render_demo_mode_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "x:demo_disable_yes":
        if not pop_confirm(chat_id, user_id, "demo_disable"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/toggle", json_body={"enabled": False, "confirm": True})
        text, kb = render_demo_mode_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "x:demo_regen_yes":
        if not pop_confirm(chat_id, user_id, "demo_regen"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/regenerate", json_body={"confirm": True})
        text, kb = render_demo_mode_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "x:demo_clear_yes":
        if not pop_confirm(chat_id, user_id, "demo_clear"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/clear-conversations", json_body={"confirm": True})
        text, kb = render_demo_mode_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "x:demo_live_enable_yes":
        if not pop_confirm(chat_id, user_id, "demo_live_enable"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/live-behavior", json_body={"confirm": True, "enabled": True})
        text, kb = render_demo_behavior_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "x:demo_live_disable_yes":
        if not pop_confirm(chat_id, user_id, "demo_live_disable"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/live-behavior", json_body={"confirm": True, "enabled": False})
        text, kb = render_demo_behavior_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "x:demo_regen_personalities_yes":
        if not pop_confirm(chat_id, user_id, "demo_regen_personalities"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_ok"))
        backend.request("POST", "/api/v1/admin/demo-mode/regenerate-personalities", json_body={"confirm": True})
        text, kb = render_demo_behavior_menu(user_id)
        tg_edit(chat_id, msg_id, text, kb)
        return

    if data == "x:backup_db_yes":
        if not pop_confirm(chat_id, user_id, "backup_db"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_backup_db"))
        out = backend.request("POST", "/api/v1/admin/system/backup-db", json_body={"confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "system_backup_db_title") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:system_doctor"}]])
        return

    if data == "x:clear_cache_yes":
        if not pop_confirm(chat_id, user_id, "clear_cache"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_clearing_cache"))
        out = backend.request("POST", "/api/v1/admin/system/clear-cache", json_body={"confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "system_clear_cache_title") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:system_doctor"}]])
        return

    if data == "x:run_migrations_yes":
        if not pop_confirm(chat_id, user_id, "run_migrations"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_retry"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_running_migrations"))
        out = backend.request("POST", "/api/v1/admin/system/run-migrations", json_body={"confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "system_run_migrations_title") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:system_doctor"}]])
        return

    if data == "x:l10n_export":
        tg_answer_callback(cbq_id)
        out = backend.request("GET", "/api/v1/admin/localization-quality")
        tg_send(chat_id, t(user_id, "l10n_report_title") + "\n\n" + fmt_json_block(user_id, out))
        return

    if data == "x:ai_cache_clear":
        # Not yet wired to backend endpoint; keep safe.
        tg_answer_callback(cbq_id, t(user_id, "toast_not_wired"))
        return

    if data.startswith("x:prem_yes:"):
        _, _, uid_s, days_s = data.split(":", 3)
        uid = int(uid_s)
        days = int(days_s)
        if not pop_confirm(chat_id, user_id, f"grant_premium:{uid}:{days}"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_grant_premium"))
        out = backend.request("POST", f"/api/v1/admin/users/{uid}/grant-premium", json_body={"days": days, "confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "result_premium_granted") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": f"u:{uid}"}]])
        return

    if data.startswith("x:revoke_yes:"):
        uid = int(data.split(":", 2)[2])
        if not pop_confirm(chat_id, user_id, f"revoke_premium:{uid}"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_revoke_premium"))
        out = backend.request("POST", f"/api/v1/admin/users/{uid}/revoke-premium", json_body={"confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "result_premium_revoked") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": f"u:{uid}"}]])
        return

    if data.startswith("x:memreset_yes:"):
        uid = int(data.split(":", 2)[2])
        if not pop_confirm(chat_id, user_id, f"reset_mem:{uid}"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_reset_ai_memory"))
        out = backend.request("POST", f"/api/v1/admin/users/{uid}/reset-ai-memory", json_body={"confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "result_ai_memory_reset") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": f"u:{uid}"}]])
        return

    if data.startswith("x:unban_yes:"):
        uid = int(data.split(":", 2)[2])
        if not pop_confirm(chat_id, user_id, f"unban:{uid}"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_unbanning"))
        out = backend.request("POST", f"/api/v1/admin/users/{uid}/unban", json_body={"confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "result_unbanned") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": f"u:{uid}"}]])
        return

    if data.startswith("x:ban_yes:"):
        uid = int(data.split(":", 2)[2])
        conf = pop_confirm(chat_id, user_id, f"ban:{uid}")
        if not conf:
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        reason = str((conf.get("payload") or {}).get("reason") or "")[:240]
        tg_answer_callback(cbq_id, t(user_id, "toast_banning"))
        out = backend.request("POST", f"/api/v1/admin/users/{uid}/ban", json_body={"reason": reason, "confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "result_banned") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": f"u:{uid}"}]])
        return

    if data.startswith("x:rep_dismiss_yes:"):
        rid = int(data.split(":", 2)[2])
        if not pop_confirm(chat_id, user_id, f"rep_dismiss:{rid}"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_dismissing"))
        out = backend.request("POST", f"/api/v1/admin/reports/{rid}/dismiss", json_body={"confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "result_dismissed") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:reports_open"}]])
        return

    if data.startswith("x:rep_ban_yes:"):
        _, _, rid_s, uid_s = data.split(":", 3)
        rid = int(rid_s)
        uid = int(uid_s)
        if not pop_confirm(chat_id, user_id, f"rep_ban:{rid}:{uid}"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_resolving_banning"))
        out = backend.request("POST", f"/api/v1/admin/reports/{rid}/resolve", json_body={"action": "ban", "confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "result_banned_resolved") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:reports_open"}]])
        return

    if data == "x:premium_grant_all_yes":
        if not pop_confirm(chat_id, user_id, "premium_grant_all"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_granting"))
        out = backend.request("POST", "/api/v1/admin/premium/grant-all-dev", json_body={"days": 30, "confirm": True})
        tg_edit(chat_id, msg_id, t(user_id, "result_grant_all_dev") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:premium"}]])
        return

    if data.startswith("x:promo_create_yes:"):
        code = str(data.split(":", 2)[2] or "").strip().upper()
        conf = pop_confirm(chat_id, user_id, f"promo_create:{code}")
        if not conf:
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        payload = conf.get("payload") or {}
        tg_answer_callback(cbq_id, t(user_id, "toast_creating"))
        out = backend.request(
            "POST",
            "/api/v1/admin/premium/create-promo-code",
            json_body={"code": payload.get("code"), "days": payload.get("days"), "max_uses": payload.get("max_uses"), "confirm": True},
        )
        try:
            telegram_track(
                "order_created",
                telegram_user_id=int(user_id or 0),
                viewer_user_id=None,
                payload={"source": "telegram_promo_code", "code": str(code)},
            )
        except Exception:
            pass
        tg_edit(chat_id, msg_id, t(user_id, "result_promo_created") + "\n\n" + fmt_json_block(user_id, out), [[{"text": t(user_id, "back"), "callback_data": "m:premium"}]])
        return

    if data == "x:match_quality_recompute_yes":
        if not pop_confirm(chat_id, user_id, "match_quality_recompute"):
            tg_answer_callback(cbq_id, t(user_id, "toast_confirm_expired_short"))
            return
        tg_answer_callback(cbq_id, t(user_id, "toast_recomputing"))
        uid = int(user_id or 0)
        try:
            out = backend.request("POST", "/api/v1/admin/match-quality/recompute", json_body={"confirm": True})
        except Exception as e:
            detail = escape(str(e)[:500])
            tg_edit(
                chat_id,
                msg_id,
                f"{t(uid, 'mq_recompute_failed')}\n\n<pre>{detail}</pre>",
                [[{"text": t(uid, "back"), "callback_data": "m:match_quality"}]],
            )
            return
        tg_edit(
            chat_id,
            msg_id,
            t(uid, "result_recompute_done") + "\n\n" + fmt_json_block(uid, out),
            [[{"text": t(uid, "back"), "callback_data": "m:match_quality"}]],
        )
        return

    tg_answer_callback(cbq_id, t(user_id, "unknown_action"))


def route_message(text: str, chat_id: int, user_id: int) -> None:
    if not is_admin(user_id):
        tg_send(chat_id, t(user_id, "access_denied"))
        return
    if text.strip() in {"/start", "/menu"}:
        if int(user_id) not in admin_lang:
            tt, kb = render_language_picker(user_id)
        else:
            tt, kb = render_home(user_id)
        tg_send(chat_id, tt, kb)
        return
    pending = pop_input(chat_id, user_id)
    if pending and pending.get("mode") == "ai_viewer_id":
        raw = text.strip()
        try:
            vid = int(raw)
        except Exception:
            set_input(chat_id, user_id, "ai_viewer_id", {})
            tg_send(chat_id, t(user_id, "ai_prompt_viewer"), [[{"text": t(user_id, "back"), "callback_data": "m:ai"}]])
            return
        if vid < 1:
            set_input(chat_id, user_id, "ai_viewer_id", {})
            tg_send(chat_id, t(user_id, "ai_prompt_viewer"), [[{"text": t(user_id, "back"), "callback_data": "m:ai"}]])
            return
        ai_ctx_set(chat_id, user_id, viewer_uid=vid)
        tg_send(
            chat_id,
            f"<b>OK</b>\nviewer=<code>{vid}</code>",
            [[{"text": t(user_id, "menu_ai"), "callback_data": "m:ai"}]],
        )
        return
    if pending and pending.get("mode") == "ai_partner_id":
        raw = text.strip()
        try:
            pid = int(raw)
        except Exception:
            set_input(chat_id, user_id, "ai_partner_id", {})
            tg_send(chat_id, t(user_id, "ai_prompt_partner"), [[{"text": t(user_id, "back"), "callback_data": "m:ai"}]])
            return
        if pid < 1:
            set_input(chat_id, user_id, "ai_partner_id", {})
            tg_send(chat_id, t(user_id, "ai_prompt_partner"), [[{"text": t(user_id, "back"), "callback_data": "m:ai"}]])
            return
        ai_ctx_set(chat_id, user_id, partner_uid=pid)
        tg_send(
            chat_id,
            f"<b>OK</b>\npartner=<code>{pid}</code>",
            [[{"text": t(user_id, "menu_ai"), "callback_data": "m:ai"}]],
        )
        return
    if pending and pending.get("mode") == "ai_improve_text":
        draft = text.strip()
        if len(draft) < 1:
            set_input(chat_id, user_id, "ai_improve_text", {})
            tg_send(chat_id, t(user_id, "ai_prompt_improve"), [[{"text": t(user_id, "back"), "callback_data": "m:ai"}]])
            return
        ctx = ai_ctx_get(chat_id, user_id)
        vu = _safe_app_user_id(ctx.get("viewer_uid")) or 0
        if vu < 1:
            tg_send(chat_id, t(user_id, "ai_need_pair"), [[{"text": t(user_id, "back"), "callback_data": "m:ai"}]])
            return
        try:
            out = backend.request(
                "POST",
                "/api/v1/admin/telegram/ai/improve-reply",
                json_body={"viewer_user_id": vu, "draft": draft, "locale": "en", "conversation_context": []},
            )
        except Exception as e:
            tg_send(chat_id, f"<pre>{escape(str(e)[:500])}</pre>", [[{"text": t(user_id, "back"), "callback_data": "m:ai"}]])
            return
        vars_ = out.get("variants") if isinstance(out, dict) else None
        meta = (out.get("meta") if isinstance(out, dict) else {}) or {}
        lim = bool((meta or {}).get("limited"))
        if lim:
            telegram_track("ai_limit_hit", telegram_user_id=user_id, viewer_user_id=vu, payload={"endpoint": "improve-reply"})
        telegram_track("ai_used", telegram_user_id=user_id, viewer_user_id=vu, payload={"endpoint": "improve-reply"})
        lines = ["<b>Improve</b>"]
        if isinstance(vars_, list):
            for i, v in enumerate(vars_[:5], start=1):
                if isinstance(v, dict):
                    lines.append(f"{i}. {escape(str(v.get('text') or ''))}")
        tg_send(chat_id, "\n".join(lines), [[{"text": t(user_id, "menu_ai"), "callback_data": "m:ai"}]])
        return
    if pending and pending.get("mode") == "user_search":
        q = text.strip()
        items = backend.request("GET", f"/api/v1/admin/users/search?q={requests.utils.quote(q)}")
        tt, kb = render_user_results(user_id, items if isinstance(items, list) else [], q)
        tg_send(chat_id, tt, kb)
        return
    if pending and pending.get("mode") == "ban_reason":
        uid = int((pending.get("payload") or {}).get("target_user_id") or 0)
        reason = text.strip()
        if len(reason) < 2:
            set_input(chat_id, user_id, "ban_reason", {"target_user_id": uid})
            tg_send(chat_id, t(user_id, "telegram.route.ban_reason_too_short"))
            return
        # Require explicit confirm after reason is provided.
        set_confirm(chat_id, user_id, f"ban:{uid}", {"reason": reason})
        tg_send(
            chat_id,
            t(user_id, "telegram.route.ban_confirm_html", uid=uid, reason=escape(reason[:240])),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:ban_yes:{uid}"}, {"text": t(user_id, "cancel"), "callback_data": f"u:{uid}"}]],
        )
        return
    if pending and pending.get("mode") == "backup_restore_phrase":
        payload = pending.get("payload") or {}
        filename = _backup_filename(payload.get("filename"))
        msg_id = int(payload.get("message_id") or 0)
        phrase = text.strip()
        if not filename:
            tg_send(chat_id, t(user_id, "unknown_action"))
            return
        if phrase != BACKUP_RESTORE_PHRASE:
            set_input(chat_id, user_id, "backup_restore_phrase", {"filename": filename, "message_id": msg_id})
            tg_send(
                chat_id,
                t(user_id, "telegram.route.backup_phrase_mismatch_html", phrase=escape(BACKUP_RESTORE_PHRASE)),
                [[{"text": t(user_id, "cancel"), "callback_data": "m:backups_restore"}]],
            )
            return
        set_confirm(chat_id, user_id, f"backup_restore:{filename}", {"filename": filename})
        tg_send(
            chat_id,
            t(user_id, "telegram.route.backup_restore_confirm_html", filename=escape(filename)),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:backup_restore:{filename}"}, {"text": t(user_id, "cancel"), "callback_data": "m:backups_restore"}]],
        )
        return
    if pending and pending.get("mode") == "release_mark":
        raw = text.strip()
        if "|" in raw:
            version, notes = [part.strip() for part in raw.split("|", 1)]
        else:
            parts = raw.split(maxsplit=1)
            version = parts[0].strip() if parts else ""
            notes = parts[1].strip() if len(parts) > 1 else ""
        if not version:
            set_input(chat_id, user_id, "release_mark", pending.get("payload") or {})
            tg_send(chat_id, t(user_id, "telegram.route.release_version_required_html"), [[{"text": t(user_id, "cancel"), "callback_data": "m:release"}]])
            return
        set_confirm(chat_id, user_id, "release_mark", {"version": version[:64], "notes": notes[:500]})
        tg_send(
            chat_id,
            t(
                user_id,
                "telegram.route.release_mark_confirm_html",
                version=escape(version[:64]),
                notes=escape(notes[:500]),
            ),
            [[{"text": t(user_id, "confirm"), "callback_data": "x:release_mark_yes"}, {"text": t(user_id, "cancel"), "callback_data": "m:release"}]],
        )
        return
    if pending and pending.get("mode") == "promo_create":
        parts = [p for p in text.strip().split() if p.strip()]
        if len(parts) < 3:
            set_input(chat_id, user_id, "promo_create", {})
            tg_send(chat_id, t(user_id, "telegram.route.promo_format_invalid"))
            return
        code = parts[0].strip().upper()[:64]
        try:
            days = int(parts[1])
            max_uses = int(parts[2])
        except Exception:
            set_input(chat_id, user_id, "promo_create", {})
            tg_send(chat_id, t(user_id, "telegram.route.promo_numbers_invalid"))
            return
        set_confirm(chat_id, user_id, f"promo_create:{code}", {"code": code, "days": days, "max_uses": max_uses})
        tg_send(
            chat_id,
            t(user_id, "telegram.route.promo_create_confirm_html", code=escape(code), days=days, max_uses=max_uses),
            [[{"text": t(user_id, "confirm"), "callback_data": f"x:promo_create_yes:{code}"}, {"text": t(user_id, "cancel"), "callback_data": "m:premium"}]],
        )
        return
    if text.strip().lower() in {"/users", "/user"}:
        set_input(chat_id, user_id, "user_search", {})
        tt, kb = render_users_search_prompt(user_id)
        tg_send(chat_id, tt, kb)
        return
    tg_send(chat_id, t(user_id, "unknown_command"))


def _install_render_guards() -> None:
    """Wrap every render_* so Menu QA and live polling never crash on empty/invalid API data."""
    g = globals()
    for name in list(g.keys()):
        if not name.startswith("render_"):
            continue
        fn = g.get(name)
        if not callable(fn) or getattr(fn, "__neyra_guarded_render__", False):
            continue

        def _make_guard(orig: Any, nm: str) -> Any:
            def guarded(*a: Any, **k: Any) -> tuple[str, list[list[dict[str, str]]]]:
                uid = _render_context_user_id(a, k)
                try:
                    out = orig(*a, **k)
                    if not isinstance(out, tuple) or len(out) != 2:
                        raise ValueError("render must return (text, keyboard)")
                    text, kb = out[0], out[1]
                    txt = str(text or "")
                    if not isinstance(kb, list):
                        kb = []
                    if not kb:
                        kb = [[{"text": t(uid, "back"), "callback_data": "m:home"}]]
                    return txt, kb
                except Exception as e:
                    _admin_debug_log(f"render_error:{nm}:{type(e).__name__}:{e}")
                    return fallback_render_ui(uid, None, "m:home")

            guarded.__neyra_guarded_render__ = True  # type: ignore[attr-defined]
            guarded.__name__ = nm
            return guarded

        g[name] = _make_guard(fn, name)


_install_render_guards()


def run_polling() -> None:
    _log("Telegram bot starting...")
    _acquire_single_instance_lock()
    _must_configure()
    _validate_telegram_token()
    _wait_for_backend_ready(max_seconds=60)
    _log("Polling started")
    offset = 0
    while True:
        try:
            poll_alerts_once()
            url = TG_API.format(token=TELEGRAM_BOT_TOKEN, method="getUpdates")
            res = requests.get(url, params={"timeout": POLL_TIMEOUT_S, "offset": offset}, timeout=POLL_TIMEOUT_S + 10)
            res.raise_for_status()
            data = res.json()
            if not data.get("ok"):
                time.sleep(1.0)
                continue
            for upd in data.get("result", []):
                offset = max(offset, int(upd.get("update_id", 0)) + 1)

                if "callback_query" in upd:
                    cb = upd["callback_query"]
                    cbq_id = cb.get("id")
                    from_user = cb.get("from") or {}
                    user_id = int(from_user.get("id") or 0)
                    msg = cb.get("message") or {}
                    chat = msg.get("chat") or {}
                    chat_id = int(chat.get("id") or 0)
                    msg_id = int(msg.get("message_id") or 0)
                    payload = (cb.get("data") or "").strip()
                    if cbq_id and chat_id and msg_id and payload:
                        route_callback(payload, chat_id, msg_id, user_id, cbq_id)
                    continue

                if "message" in upd:
                    msg = upd["message"]
                    chat = msg.get("chat") or {}
                    from_user = msg.get("from") or {}
                    chat_id = int(chat.get("id") or 0)
                    user_id = int(from_user.get("id") or 0)
                    text = msg.get("text") or ""
                    if chat_id and user_id and text:
                        route_message(text, chat_id, user_id)
        except Exception:
            time.sleep(1.0)


if __name__ == "__main__":
    run_polling()
