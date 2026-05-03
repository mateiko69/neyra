from __future__ import annotations

import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailSender:
    def send(self, *, to_email: str, subject: str, text: str) -> None:
        raise NotImplementedError()


class DevLogEmailSender(EmailSender):
    def send(self, *, to_email: str, subject: str, text: str) -> None:
        # Dev-only: log the email content for local testing.
        if (settings.ENV or "").strip().lower() in {"production", "prod"}:
            return
        logger.info("DEV_EMAIL to=%s subject=%s body=%s", to_email, subject, text)


def get_email_sender() -> EmailSender:
    # v1: dev sender only; prod provider can be added later.
    return DevLogEmailSender()

