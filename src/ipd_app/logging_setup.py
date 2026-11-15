"""Logging: rotating file (5 x 10 MB) with secrets scrubbed from every record.

Nothing that identifies or authenticates the user may reach a log: passwords,
2FA codes, cookies, tokens. Apple IDs are masked (al***@example.com). The filter
sits on the handlers, so it also covers records of third-party libraries.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config

MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5
REDACTED = "***"

_EMAIL = re.compile(r"\b([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
# key = value / "key": "value" pairs whose value must never be logged
_SECRET_KEYS = (
    r"pass(?:word|wd)?|session[_-]?token|trust[_-]?token|dsWebAuthToken|scnt|"
    r"securityCode|verificationCode|m1|m2|cookie|set-cookie|authorization|"
    r"X-Apple-[A-Za-z0-9-]*(?:Token|Session-Id|Rscd|Ercd)|X-APPLE-WEBAUTH-[A-Z-]+"
)
_KEY_VALUE = re.compile(
    rf"""(?P<key>(?<![A-Za-z])["']?(?:{_SECRET_KEYS})["']?\s*[:=]\s*)"""
    r"""(?P<value>\{[^}]*\}|"[^"]*"|'[^']*'|[^\s,;&}\]]+)""",
    re.IGNORECASE,
)
# "code: 123456" is a 2FA code; "code: -20283" is an Apple error code worth keeping.
_SIX_DIGIT_CODE = re.compile(r"""(?P<key>\bcode["']?\s*[:=]?\s*["']?)\d{6}\b""", re.IGNORECASE)
# Signed download links carry access tokens in the query string.
_URL_QUERY = re.compile(r"(https?://[^\s?\"']+)\?[^\s\"']+")


def mask_apple_id(apple_id: str) -> str:
    local, at, domain = apple_id.partition("@")
    if not at:
        return local[:2] + REDACTED
    return f"{local[:2]}{REDACTED}@{domain}"


def scrub(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    text = _URL_QUERY.sub(rf"\1?{REDACTED}", text)
    text = _KEY_VALUE.sub(lambda m: m.group("key") + REDACTED, text)
    text = _SIX_DIGIT_CODE.sub(lambda m: m.group("key") + REDACTED, text)
    return _EMAIL.sub(lambda m: f"{m.group(1)[:2]}{REDACTED}@{m.group(2)}", text)


class SecretFilter(logging.Filter):
    """Rewrites each record in place so no handler can emit a secret."""

    def __init__(self) -> None:
        super().__init__()
        self._secrets: set[str] = set()
        self._lock = threading.Lock()

    def add_secret(self, value: str | None) -> None:
        """Register a literal (a password, a 2FA code) to blank out wherever it appears."""
        if value and len(value) >= 4:
            with self._lock:
                self._secrets.add(value)

    def filter(self, record: logging.LogRecord) -> bool:
        with self._lock:
            secrets = tuple(self._secrets)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - malformed format args
            message = str(record.msg)
        record.msg = scrub(message, secrets)
        record.args = None
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        if record.exc_text:
            record.exc_text = scrub(record.exc_text, secrets)
        return True


secret_filter = SecretFilter()


def setup_logging(
    directory: Path | None = None, level: int = logging.INFO, console: bool = False
) -> Path:
    """Configure the root logger once. Returns the log file path."""
    directory = directory or config.log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    log_file = directory / "app.log"
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        if getattr(handler, "_ipd", False):
            root.removeHandler(handler)
            handler.close()
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    handlers: list[logging.Handler] = [
        RotatingFileHandler(log_file, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8")
    ]
    if console:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler._ipd = True  # type: ignore[attr-defined]
        handler.setFormatter(formatter)
        handler.addFilter(secret_filter)
        root.addHandler(handler)
    # The iCloud library logs request bodies and headers at DEBUG; never enable that.
    for noisy in ("pyicloud_ipd", "urllib3", "requests", "PIL"):
        logging.getLogger(noisy).setLevel(max(level, logging.INFO))
    return log_file


def install_excepthook() -> None:
    """No exception may end the app silently: log it, then let the caller show it."""

    def hook(exc_type, exc, traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, traceback)
            return
        logging.getLogger("ipd_app").critical("Unhandled exception", exc_info=(exc_type, exc, traceback))

    sys.excepthook = hook
    threading.excepthook = lambda args: hook(args.exc_type, args.exc_value, args.exc_traceback)
