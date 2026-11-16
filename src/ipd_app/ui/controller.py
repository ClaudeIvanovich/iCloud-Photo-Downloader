"""Glue between the windows and the core. No widgets here.

All network work runs in worker threads; the windows only receive signals, so
the UI thread never waits for iCloud or the disk.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QCoreApplication, QObject, Qt, QThread, Signal, Slot

from .. import config, strings
from ..accounts import PasswordStore, forget_session
from ..config import AccountConfig, AppConfig
from ..icloud_adapter import ICloudClient, ICloudError, LoginResult, LoginStatus, TrustedPhone
from ..logging_setup import mask_apple_id, secret_filter
from ..sync_engine import Period, Plan, PreflightError, Report, StateDB, SyncEngine
from ..sync_engine.state_db import JobRow

log = logging.getLogger(__name__)

SESSION_UNKNOWN = "unknown"
SESSION_CHECKING = "checking"
SESSION_OK = "ok"
SESSION_EXPIRED = "expired"
SESSION_ERROR = "error"

ClientFactory = Callable[[str], ICloudClient]


def default_client_factory(apple_id: str) -> ICloudClient:
    from ..icloud_adapter.pyicloud_client import PyiCloudClient

    return PyiCloudClient(config.session_dir(apple_id))


class Task(QThread):
    """Runs one callable off the UI thread."""

    # (task, ok, result or exception). Delivered to the controller's own slot with a
    # queued connection, so result handlers always run in the UI thread. Plain
    # callables connected to a signal would run in the emitting thread instead.
    completed = Signal(object, bool, object)

    def __init__(
        self,
        work: Callable[[], Any],
        on_done: Callable[[Any], None],
        on_fail: Callable[[Any], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._work = work
        self.on_done = on_done
        self.on_fail = on_fail

    def run(self) -> None:
        try:
            result = self._work()
        except Exception as error:  # noqa: BLE001 - delivered to the UI as a signal
            if not isinstance(error, (ICloudError, PreflightError)):
                log.exception("Background task failed")
            self.completed.emit(self, False, error)
        else:
            self.completed.emit(self, True, result)


def user_message(error: BaseException) -> str:
    return getattr(error, "user_message", None) or f"{type(error).__name__}: {error}"


@dataclass
class LoginOutcome:
    status: LoginStatus
    message: str = ""
    phones: tuple[TrustedPhone, ...] = ()


class JobProgress:
    """Counters written by engine threads and polled by the UI timer."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.total_files = 0
            self.done_files = 0
            self.total_bytes = 0
            self.done_bytes = 0
            self.current = ""

    def planned(self, plan: Plan) -> None:
        with self._lock:
            self.total_files = plan.files_to_download
            self.total_bytes = plan.bytes_to_download

    def add_bytes(self, count: int) -> None:
        with self._lock:
            self.done_bytes += count

    def file_event(self, path: str, result: str) -> None:
        with self._lock:
            if result == "started":
                self.current = path
            elif result == "downloaded":
                self.done_files += 1

    def snapshot(self) -> tuple[int, int, int, int, str]:
        with self._lock:
            return self.done_files, self.total_files, self.done_bytes, self.total_bytes, self.current


class Controller(QObject):
    accounts_changed = Signal()
    session_changed = Signal(str, str)  # state, message
    login_finished = Signal(object)  # LoginOutcome
    albums_loaded = Signal(object, str)  # list[Album] | None, error message
    job_state = Signal(str)  # idle / counting / downloading / paused / error
    job_plan = Signal(object)  # Plan
    job_problem = Signal(str, str, str)  # path, kind, message
    job_finished = Signal(object, str)  # Report | None, error message
    notify = Signal(str, str, str)  # title, text, kind: info / error / relogin

    def __init__(
        self,
        client_factory: ClientFactory = default_client_factory,
        passwords: PasswordStore | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._client_factory = client_factory
        self._passwords = passwords or PasswordStore()
        self.config: AppConfig = config.load_config()
        self._clients: dict[str, ICloudClient] = {}
        self._session: dict[str, tuple[str, str]] = {}
        self._tasks: set[Task] = set()
        self._pending_login: tuple[str, str | None, ICloudClient] | None = None
        self.progress = JobProgress()
        self.last_report: Report | None = None
        self._engine: SyncEngine | None = None
        self._job_db: StateDB | None = None
        self._job_task: Task | None = None
        self._job_state = "idle"

    # ----------------------------------------------------------- helpers

    def _spawn(self, work: Callable[[], Any], done: Callable[[Any], None], fail: Callable[[Any], None]) -> Task:
        task = Task(work, done, fail, self)
        task.completed.connect(self._on_task_completed, Qt.ConnectionType.QueuedConnection)
        self._tasks.add(task)
        task.start()
        return task

    @Slot(object, bool, object)
    def _on_task_completed(self, task: Task, ok: bool, payload: Any) -> None:
        # The signal is emitted a moment before the thread really ends; a QThread
        # must not be destroyed in that window.
        task.wait()
        self._tasks.discard(task)
        try:
            (task.on_done if ok else task.on_fail)(payload)
        finally:
            task.deleteLater()

    def _client(self, apple_id: str) -> ICloudClient:
        key = config.account_id(apple_id)
        if key not in self._clients:
            self._clients[key] = self._client_factory(apple_id)
        return self._clients[key]

    def save(self) -> None:
        config.save_config(self.config)

    # ---------------------------------------------------------- accounts

    def accounts(self) -> list[AccountConfig]:
        return list(self.config.accounts.values())

    def active(self) -> AccountConfig | None:
        if self.config.active_account is None:
            return None
        return self.config.accounts.get(self.config.active_account)

    def set_language(self, choice: str) -> None:
        """Remember the language ("auto" or a code); it takes effect at the next start."""
        self.config.language = choice
        self.save()

    def set_active(self, apple_id: str) -> bool:
        """Switch the active account. Refused while a job is running."""
        if self.is_job_running:
            return False
        key = config.account_id(apple_id)
        if key not in self.config.accounts:
            return False
        self.config.active_account = key
        self.save()
        self.accounts_changed.emit()
        self.check_session()
        return True

    def sign_out(self, apple_id: str) -> bool:
        """Forget the saved password and session; the account stays in the list."""
        if self.is_job_running and self._is_active(apple_id):
            return False
        self._passwords.forget(apple_id)
        forget_session(apple_id)
        key = config.account_id(apple_id)
        self._clients.pop(key, None)
        self._session.pop(key, None)
        if self._is_active(apple_id):
            self.session_changed.emit(SESSION_EXPIRED, "")
        return True

    def remove_account(self, apple_id: str) -> bool:
        """Remove sign-in data and settings of an account. Downloaded files and
        the sync state are left alone."""
        if not self.sign_out(apple_id):
            return False
        self.config.drop_account(apple_id)
        self.save()
        self.accounts_changed.emit()
        self.check_session()
        return True

    def _is_active(self, apple_id: str) -> bool:
        return self.config.active_account == config.account_id(apple_id)

    def update_active(self, **fields: Any) -> None:
        account = self.active()
        if account is None:
            return
        for name, value in fields.items():
            setattr(account, name, value)
        self.save()
        self.accounts_changed.emit()

    def shared_root_accounts(self) -> list[str]:
        account = self.active()
        return self.config.shared_roots(account.apple_id) if account else []

    # ----------------------------------------------------------- session

    def session_state(self) -> tuple[str, str]:
        account = self.active()
        if account is None:
            return SESSION_UNKNOWN, ""
        return self._session.get(config.account_id(account.apple_id), (SESSION_UNKNOWN, ""))

    def _set_session(self, apple_id: str, state: str, message: str = "") -> None:
        self._session[config.account_id(apple_id)] = (state, message)
        if self._is_active(apple_id):
            self.session_changed.emit(state, message)

    def check_session(self) -> None:
        """Try the saved session of the active account, without asking anything."""
        account = self.active()
        if account is None:
            self.session_changed.emit(SESSION_UNKNOWN, "")
            return
        apple_id = account.apple_id
        client = self._client(apple_id)
        self._set_session(apple_id, SESSION_CHECKING)

        def done(result: LoginResult) -> None:
            if result.status is LoginStatus.OK:
                self._set_session(apple_id, SESSION_OK)
            elif result.error is not None and result.error.transient:
                self._set_session(apple_id, SESSION_ERROR, result.error.user_message)
            else:
                self._set_session(apple_id, SESSION_EXPIRED)

        self._spawn(
            lambda: client.login(apple_id, None),
            done,
            lambda error: self._set_session(apple_id, SESSION_ERROR, user_message(error)),
        )

    def has_saved_password(self, apple_id: str) -> bool:
        return bool(self._passwords.get(apple_id))

    # ------------------------------------------------------------- login

    def begin_login(self, apple_id: str, password: str | None) -> None:
        """Start sign-in. With password=None the saved password is used."""
        apple_id = apple_id.strip()
        typed = password is not None
        if password is None:
            password = self._passwords.get(apple_id)
        if not apple_id or not password:
            self.login_finished.emit(LoginOutcome(LoginStatus.FAILED, strings.UI.LOGIN_NEED_FIELDS))
            return
        secret_filter.add_secret(password)
        client = self._client(apple_id)
        self._pending_login = (apple_id, password if typed else None, client)
        log.info("Signing in %s", mask_apple_id(apple_id))
        self._spawn(lambda: client.login(apple_id, password), self._login_step, self._login_failed)

    def submit_code(self, code: str) -> None:
        if self._pending_login is None:
            return
        secret_filter.add_secret(code)
        client = self._pending_login[2]
        self._spawn(lambda: client.submit_2fa_code(code), self._login_step, self._login_failed)

    def request_sms(self, phone_id: int) -> None:
        if self._pending_login is None:
            return
        client = self._pending_login[2]
        self._spawn(lambda: client.request_sms_code(phone_id), lambda _: None, self._login_failed)

    def submit_sms_code(self, phone_id: int, code: str) -> None:
        if self._pending_login is None:
            return
        secret_filter.add_secret(code)
        client = self._pending_login[2]
        self._spawn(lambda: client.submit_sms_code(phone_id, code), self._login_step, self._login_failed)

    def cancel_login(self) -> None:
        self._pending_login = None

    def _login_step(self, result: LoginResult) -> None:
        if self._pending_login is None:
            return
        apple_id, typed_password, _client = self._pending_login
        if result.status is LoginStatus.NEEDS_2FA:
            self.login_finished.emit(LoginOutcome(LoginStatus.NEEDS_2FA, phones=result.phones))
            return
        if result.status is LoginStatus.FAILED:
            message = result.error.user_message if result.error else strings.ERR_ICLOUD_GENERIC.format(detail="")
            self.login_finished.emit(LoginOutcome(LoginStatus.FAILED, message))
            return
        self._pending_login = None
        if typed_password:
            self._passwords.save(apple_id, typed_password)
        new = self.config.account(apple_id) is None
        self.config.ensure_account(apple_id)
        if new and not self.is_job_running:
            self.config.active_account = config.account_id(apple_id)
        self.save()
        self._set_session(apple_id, SESSION_OK)
        self.accounts_changed.emit()
        self.login_finished.emit(LoginOutcome(LoginStatus.OK))

    def _login_failed(self, error: BaseException) -> None:
        self.login_finished.emit(LoginOutcome(LoginStatus.FAILED, user_message(error)))

    # ------------------------------------------------------------ albums

    def load_albums(self) -> None:
        account = self.active()
        if account is None:
            self.albums_loaded.emit(None, strings.UI.HINT_NO_ACCOUNT)
            return
        client = self._client(account.apple_id)
        self._spawn(
            client.list_albums,
            lambda albums: self.albums_loaded.emit(list(albums), ""),
            lambda error: self.albums_loaded.emit(None, user_message(error)),
        )

    # --------------------------------------------------------------- job

    @property
    def is_job_running(self) -> bool:
        return self._job_task is not None

    @property
    def job_state_name(self) -> str:
        return self._job_state

    def unfinished_job(self) -> JobRow | None:
        """The interrupted job of the active account, to offer 'continue?'."""
        account = self.active()
        if account is None or self.is_job_running:
            return None
        path = config.state_db_path(account.apple_id)
        if not path.exists():
            return None
        db = StateDB(path)
        try:
            return db.unfinished_job()
        finally:
            db.close()

    def can_start(self) -> str:
        """Empty string when a job may start, otherwise the reason it may not."""
        account = self.active()
        if account is None:
            return strings.UI.HINT_NO_ACCOUNT
        if not account.root_dir:
            return strings.UI.HINT_NO_ROOT
        if self.session_state()[0] != SESSION_OK:
            return strings.UI.HINT_NO_SESSION
        if self.is_job_running:
            return strings.ERR_JOB_RUNNING
        return ""

    def start_job(self, period: Period) -> bool:
        if self.can_start():
            return False
        account = self.active()
        assert account is not None
        client = self._client(account.apple_id)
        self.progress.reset()
        self._job_db = StateDB(config.state_db_path(account.apple_id))
        self._engine = SyncEngine(client, self._job_db, account.to_settings(), on_event=self._on_engine_event)
        engine = self._engine
        log.info("Starting job %s for %s", period.label(), mask_apple_id(account.apple_id))
        self._set_job_state("counting")
        self._job_task = self._spawn(lambda: engine.run(period), self._job_done, self._job_failed)
        return True

    def pause_job(self) -> None:
        if self._engine and self.is_job_running:
            self._engine.pause()

    def resume_job(self) -> None:
        if self._engine and self.is_job_running:
            self._engine.resume()

    def stop_job(self) -> None:
        if self._engine and self.is_job_running:
            self._engine.stop()

    def _set_job_state(self, state: str) -> None:
        self._job_state = state
        self.job_state.emit(state)

    def _on_engine_event(self, name: str, **data: Any) -> None:
        """Called from engine threads. Only thread-safe things happen here."""
        if name == "bytes":
            self.progress.add_bytes(data["count"])
        elif name == "file":
            self.progress.file_event(data["path"], data["result"])
            if data["result"] in ("error", "conflict"):
                self.job_problem.emit(data["path"], data["result"], data.get("message", ""))
        elif name == "plan":
            self.progress.planned(data["plan"])
            self.job_plan.emit(data["plan"])
        elif name == "status" and data["state"] in ("counting", "downloading", "paused"):
            self._job_state = data["state"]
            self.job_state.emit(data["state"])

    def _close_job(self) -> None:
        if self._job_db is not None:
            self._job_db.close()
        self._job_db = None
        self._engine = None
        self._job_task = None

    def _job_done(self, report: Report) -> None:
        account = self.active()
        self._close_job()
        self.last_report = report
        ui = strings.UI
        summary = ui.LAST_SUMMARY.format(
            downloaded=report.downloaded,
            skipped=report.skipped,
            errors=len(report.errors),
            conflicts=len(report.conflicts),
        )
        if report.finished:
            self._set_job_state("idle")
            self.notify.emit(ui.NOTE_DONE_TITLE, summary, "info")
        elif report.stopped_reason == strings.STOP_SESSION:
            self._set_job_state("error")
            if account is not None:
                self._set_session(account.apple_id, SESSION_EXPIRED)
            self.notify.emit(ui.NOTE_RELOGIN_TITLE, ui.NOTE_RELOGIN_TEXT, "relogin")
        elif report.stopped_reason == strings.STOP_USER:
            self._set_job_state("idle")
            self.notify.emit(ui.NOTE_STOPPED_TITLE, summary, "info")
        else:
            self._set_job_state("error")
            self.notify.emit(ui.NOTE_ERROR_TITLE, report.stopped_reason or "", "error")
        self.job_finished.emit(report, "")

    def _job_failed(self, error: BaseException) -> None:
        account = self.active()
        self._close_job()
        message = user_message(error)
        self._set_job_state("error")
        if message == strings.ERR_SESSION_EXPIRED:
            if account is not None:
                self._set_session(account.apple_id, SESSION_EXPIRED)
            self.notify.emit(strings.UI.NOTE_RELOGIN_TITLE, strings.UI.NOTE_RELOGIN_TEXT, "relogin")
        else:
            self.notify.emit(strings.UI.NOTE_ERROR_TITLE, message, "error")
        self.job_finished.emit(None, message)

    def problems(self) -> list[tuple[str, str, str]]:
        """(path, kind, reason) rows of the last run, for the errors window."""
        report = self.last_report
        if report is None:
            return []
        ui = strings.UI
        rows = [(path, ui.KIND_ERROR, reason) for path, reason in report.errors]
        rows += [(path, ui.KIND_CONFLICT, reason) for path, reason in report.conflicts]
        rows += [(path, ui.KIND_COMPACT, reason) for path, reason in report.compact_errors]
        return rows

    def root_dir(self) -> Path | None:
        account = self.active()
        return Path(account.root_dir) if account and account.root_dir else None

    # ---------------------------------------------------------- shutdown

    def shutdown(self, timeout_ms: int = 15000) -> None:
        """Stop the job and wait for worker threads before the app exits."""
        self.stop_job()
        for task in list(self._tasks):
            task.wait(timeout_ms)
        # Deliver the results of the tasks that have just ended.
        QCoreApplication.sendPostedEvents(self)
        self._close_job()
