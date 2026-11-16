"""Private newline-JSON bridge between the native macOS UI and the Qt controller.

The pipe is inherited from the parent process and is never exposed on a socket.
Passwords and codes are only sent through stdin, never arguments or logs.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import threading
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, QTimer, Signal, Slot

from . import config, strings
from .accounts import MemoryPasswordBackend, PasswordStore
from .logging_setup import setup_logging
from .sync_engine import Period
from .ui.controller import Controller

log = logging.getLogger(__name__)

# Translate the engine's existing stable user-facing messages without altering
# the Windows UI or the engine's comparisons against those strings.
_TRANSLATIONS = {
    "ERR_BAD_CREDENTIALS": "Incorrect Apple ID or password.",
    "ERR_BAD_2FA_CODE": "The verification code was not accepted.",
    "ERR_PASSWORD_STORAGE": "Could not save the password in the system keychain. Check access to it.",
    "ERR_SESSION_EXPIRED": "Session expired. Please sign in again.",
    "ERR_ADP": "Advanced Data Protection is enabled. Turn it off to access iCloud Photos on the web.",
    "ERR_WEB_ACCESS": "Access to iCloud data on the web is disabled. Enable it in iCloud settings.",
    "ERR_SECURITY_KEY": "Security keys are not supported.",
    "ERR_NETWORK": "Cannot reach iCloud. Check your internet connection.",
    "ERR_UNAVAILABLE": "iCloud is temporarily unavailable or rate-limited. Try again later.",
    "ERR_LIBRARY_NOT_READY": "The iCloud library is not ready yet. Try again later.",
    "ERR_ICLOUD_GENERIC": "iCloud error: {detail}",
    "ERR_NO_ROOT": "Choose a download folder in account settings.",
    "ERR_ROOT_UNAVAILABLE": "The folder {path} is unavailable. Check the disk or network connection.",
    "ERR_ROOT_NOT_WRITABLE": "Cannot write to {path}. Check its permissions.",
    "ERR_LOW_SPACE": "Not enough free disk space: {free} available, {need} required.",
    "ERR_PATH_TOO_LONG": "Path is too long: {path}",
    "ERR_BAD_PERIOD": "The start date is after the end date.",
    "ERR_JOB_RUNNING": "A job is already running.",
    "REASON_SAME_SIZE_CONFLICT": "a file with a different size already exists at this path",
    "REASON_SIZE_MISMATCH": "downloaded size does not match: {got} of {expected} bytes",
    "REASON_NO_VERSION": "this version is not available in iCloud",
    "STOP_USER": "stopped by the user",
}
_UI_TRANSLATIONS = {
    "HINT_NO_ACCOUNT": "Add an account before starting a job.",
    "HINT_NO_ROOT": "Choose a download folder in settings.",
    "HINT_NO_SESSION": "Sign in before starting a job.",
    "LOGIN_NEED_FIELDS": "Enter your Apple ID and password.",
}


def localized(message: str | None) -> dict[str, str]:
    """Return both languages, so changing the UI language also changes old errors."""
    message = message or ""
    if not message:
        return {"ru": "", "en": ""}
    for source, translations in ((strings, _TRANSLATIONS), (strings.UI, _UI_TRANSLATIONS)):
        for name, translated in translations.items():
            template = getattr(source, name)
            names = re.findall(r"\{(\w+)\}", template)
            pattern = re.escape(template)
            for field in names:
                pattern = pattern.replace(re.escape("{" + field + "}"), f"(?P<{field}>.*?)", 1)
            match = re.fullmatch(pattern, message, re.DOTALL)
            if match:
                return {"ru": message, "en": translated.format(**match.groupdict())}
    # Unknown upstream errors can contain implementation details; do not display
    # untrusted text in English. Russian still receives the original diagnostic.
    return {"ru": message, "en": "An error occurred. See the application log for details."}


class Bridge(QObject):
    incoming = Signal(object)
    eof = Signal()

    def __init__(self, fake: int | None = None):
        super().__init__()
        self._output_lock = threading.Lock()
        if fake is None:
            self.controller = Controller()
        else:
            from .icloud_adapter.fake_client import demo_library
            library = demo_library(fake)
            library.session_valid = False
            library.two_factor_code = os.environ.get("IPD_DEMO_2FA") or None
            self.controller = Controller(client_factory=lambda _: library,
                                         passwords=PasswordStore(MemoryPasswordBackend()))
        c = self.controller
        self.incoming.connect(self.dispatch)
        self.eof.connect(self.quit)
        c.accounts_changed.connect(self.snapshot)
        c.session_changed.connect(lambda state, message: self.send_event("session", state=state, message=localized(message)))
        c.login_finished.connect(lambda result: self.send_event("login", status=result.status.value,
            message=localized(result.message), phones=[asdict(p) for p in result.phones],
            pending=c._pending_login is not None))
        c.albums_loaded.connect(lambda albums, error: self.send_event("albums", albums=[asdict(a) for a in albums or []], message=localized(error)))
        c.job_state.connect(lambda state: self.send_event("job_state", state=state))
        c.count_progress.connect(lambda scanned: self.send_event("count_progress", scanned=scanned))
        c.job_plan.connect(lambda plan: self.send_event("plan", plan=asdict(plan)))
        c.job_problem.connect(lambda path, kind, message: self.send_event("problem", path=path, kind=kind, message=localized(message)))
        c.job_finished.connect(self.finished)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.progress)
        self.timer.start(500)
        threading.Thread(target=self.read_input, daemon=True).start()
        QTimer.singleShot(0, self.ready)

    def send_event(self, event: str, **payload: Any) -> None:
        with self._output_lock:
            print(json.dumps({"event": event, **payload}, ensure_ascii=False), flush=True)

    def read_input(self) -> None:
        for line in sys.stdin:
            try:
                command = json.loads(line)
                if isinstance(command, dict):
                    self.incoming.emit(command)
            except (ValueError, TypeError):
                self.send_event("error", message=localized(""))
        self.eof.emit()

    def ready(self) -> None:
        self.send_event("ready")
        self.snapshot()
        if self.controller.active():
            self.controller.check_session()

    def snapshot(self) -> None:
        c = self.controller
        active = c.active()
        self.send_event("accounts", accounts=[asdict(a) for a in c.accounts()],
                  active=active.apple_id if active else None,
                  shared=c.shared_root_accounts())

    def progress(self) -> None:
        if self.controller.is_job_running:
            done, total, done_bytes, total_bytes, current = self.controller.progress.snapshot()
            self.send_event("progress", done=done, total=total, done_bytes=done_bytes,
                      total_bytes=total_bytes, current=current)

    def finished(self, report: Any, message: str) -> None:
        data = asdict(report) if report else None
        if data:
            data["stopped_reason"] = localized(data["stopped_reason"])
            for key in ("errors", "conflicts", "compact_errors"):
                data[key] = [[path, localized(reason)] for path, reason in data[key]]
        self.send_event("finished", report=data, message=localized(message))

    @Slot(object)
    def dispatch(self, command: dict) -> None:
        c = self.controller
        try:
            action = command.get("action")
            if action == "login":
                c.begin_login(str(command.get("apple_id", "")), command.get("password"))
            elif action == "code":
                c.submit_code(str(command.get("code", "")))
            elif action == "request_sms":
                c.request_sms(int(command["phone_id"]))
            elif action == "sms_code":
                c.submit_sms_code(int(command["phone_id"]), str(command.get("code", "")))
            elif action == "cancel_login":
                c.cancel_login()
            elif action == "activate":
                c.set_active(command["apple_id"])
            elif action == "remove":
                c.remove_account(command["apple_id"])
            elif action == "sign_out":
                c.sign_out(command["apple_id"])
            elif action == "settings":
                allowed = {"root_dir", "photos", "videos", "albums", "live_video", "edited", "compact_enabled", "compact_long_side", "compact_quality", "concurrency", "min_free_gb", "restore_deleted"}
                if not c.is_job_running:
                    c.update_active(**{k: v for k, v in command.get("values", {}).items() if k in allowed})
            elif action == "albums":
                c.load_albums()
            elif action == "unfinished":
                job = c.unfinished_job()
                self.send_event("unfinished", job=asdict(job) if job else None)
            elif action in ("start", "preview"):
                error = c.can_start()
                if error:
                    self.send_event("error", message=localized(error))
                    return
                start = date.fromisoformat(command["from"]) if command.get("from") else None
                end = date.fromisoformat(command["to"]) if command.get("to") else None
                if start and end and start > end:
                    self.send_event("error", message=localized(strings.ERR_BAD_PERIOD))
                    return
                (c.start_preview if action == "preview" else c.start_job)(Period(start, end))
            elif action == "pause":
                c.pause_job()
            elif action == "resume":
                c.resume_job()
            elif action == "stop":
                c.stop_job()
            elif action == "quit":
                self.quit()
        except Exception as error:  # noqa: BLE001 - bridge boundary must not terminate the UI
            # Never print the command: it may contain a password or 2FA code.
            log.error("Bridge request failed (%s)", type(error).__name__)
            self.send_event("error", message={"ru": "Не удалось выполнить действие. Проверьте журнал.",
                                        "en": "Could not complete the action. Check the log."})

    @Slot()
    def quit(self) -> None:
        # Let Qt deliver task completion signals while downloads wind down. Do
        # not destroy their database or threads on a fixed short timeout.
        self.controller.stop_job()
        if any(task.isRunning() for task in self.controller._tasks):
            QTimer.singleShot(200, self.quit)
            return
        self.controller.shutdown()
        QCoreApplication.quit()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", type=int)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        import pillow_heif  # noqa: F401

        from .accounts import _system_backend
        from .icloud_adapter.pyicloud_client import PyiCloudClient  # noqa: F401
        if sys.platform == "darwin":
            # This checks the Security API is actually importable; no keychain
            # entry is read or written.
            assert _system_backend().priority > 0
        print(json.dumps({"event": "self_check", "ok": True}), flush=True)
        return 0
    if args.fake is not None:
        os.environ["IPD_APPDATA"] = os.environ.get("IPD_DEMO_APPDATA") or str(
            Path(tempfile.gettempdir()) / "iCloudPhotoDownloader-macos-demo"
        )
    lock = None
    if sys.platform == "darwin":
        # Multiple controllers would race over config, sessions and state DBs.
        import fcntl
        folder = config.app_data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        lock = (folder / ".macos.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"event": "error", "message": {
                "ru": "Программа уже запущена.", "en": "The application is already running."}}), flush=True)
            return 1
    app = QCoreApplication(sys.argv[:1])
    setup_logging()
    _bridge = Bridge(args.fake)  # Keep the QObject and signal handlers alive.
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
