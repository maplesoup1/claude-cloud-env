"""Optional Telegram notifications (set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)."""
from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, token: str | None = None, chat_id: str | None = None):
        self.token = token
        self.chat_id = chat_id

    @classmethod
    def from_env(cls) -> "Notifier":
        return cls(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, text: str) -> None:
        log.warning("NOTIFY: %s", text)
        if not self.enabled:
            return
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data=json.dumps({"chat_id": self.chat_id, "text": text}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as e:  # notifications must never break trading
            log.error("telegram send failed: %s", e)
