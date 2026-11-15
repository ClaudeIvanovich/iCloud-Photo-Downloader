"""Main window: account, period job, progress, last run. Plus the tray icon."""

from __future__ import annotations

import time
from collections import deque
from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import strings
from ..strings import UI, format_size
from ..sync_engine import Period, Plan, Report
from . import icons
from .controller import (
    SESSION_CHECKING,
    SESSION_ERROR,
    SESSION_EXPIRED,
    SESSION_OK,
    Controller,
)
from .dialogs import (
    AccountsDialog,
    LogDialog,
    ProblemsDialog,
    SettingsDialog,
    add_account,
    open_folder,
    run_dialog,
    sign_in_again,
)

STATE_LABELS = {
    "idle": strings.STATUS_IDLE,
    "counting": strings.STATUS_COUNTING,
    "downloading": strings.STATUS_DOWNLOADING,
    "paused": strings.STATUS_PAUSED,
    "error": strings.STATUS_ERROR,
}
SPEED_WINDOW_SECONDS = 5.0


def format_eta(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return UI.ETA_SECONDS.format(s=seconds)
    if seconds < 3600:
        return UI.ETA_MINUTES.format(m=seconds // 60, s=seconds % 60)
    return UI.ETA_HOURS.format(h=seconds // 3600, m=seconds % 3600 // 60)


def to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


class Tray(QSystemTrayIcon):
    def __init__(self, window: "MainWindow") -> None:
        super().__init__(icons.icon("idle"), window)
        self.window = window
        self._last_kind = "info"
        menu = QMenu()
        self.open_action = QAction(UI.TRAY_OPEN, menu)
        self.pause_action = QAction(UI.BTN_PAUSE, menu)
        self.stop_action = QAction(UI.BTN_STOP, menu)
        self.exit_action = QAction(UI.TRAY_EXIT, menu)
        menu.addAction(self.open_action)
        menu.addSeparator()
        menu.addAction(self.pause_action)
        menu.addAction(self.stop_action)
        menu.addSeparator()
        menu.addAction(self.exit_action)
        self._menu = menu  # keep a reference; the tray does not own it
        self.setContextMenu(menu)
        self.setToolTip(UI.TRAY_TIP_IDLE)
        self.open_action.triggered.connect(window.show_from_tray)
        self.pause_action.triggered.connect(window.toggle_pause)
        self.stop_action.triggered.connect(window.controller.stop_job)
        self.exit_action.triggered.connect(window.quit_app)
        self.activated.connect(self._on_activated)
        self.messageClicked.connect(self._on_message_clicked)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.window.show_from_tray()

    def _on_message_clicked(self) -> None:
        self.window.show_from_tray()
        if self._last_kind == "relogin":
            self.window.sign_in()

    def announce(self, title: str, text: str, kind: str) -> None:
        self._last_kind = kind
        icon = QSystemTrayIcon.MessageIcon.Critical if kind == "error" else QSystemTrayIcon.MessageIcon.Information
        if kind == "relogin":
            icon = QSystemTrayIcon.MessageIcon.Warning
        self.showMessage(title, text, icon, 10000)

    def reflect(self, state: str, running: bool, done: int, total: int) -> None:
        look = "error" if state == "error" else ("active" if running else "idle")
        self.setIcon(icons.icon(look))
        if look == "active":
            self.setToolTip(UI.TRAY_TIP_ACTIVE.format(done=done, total=total))
        else:
            self.setToolTip(UI.TRAY_TIP_ERROR if look == "error" else UI.TRAY_TIP_IDLE)
        self.pause_action.setEnabled(running)
        self.pause_action.setText(UI.BTN_RESUME if state == "paused" else UI.BTN_PAUSE)
        self.stop_action.setEnabled(running)


class MainWindow(QMainWindow):
    def __init__(self, controller: Controller, use_tray: bool = True) -> None:
        super().__init__()
        self.controller = controller
        self._quitting = False
        self._told_about_tray = False
        self._resume_offered: set[str] = set()
        self._samples: deque[tuple[float, int]] = deque()
        self.setWindowTitle(UI.APP_TITLE)
        self.setWindowIcon(icons.icon("idle"))
        self.setMinimumWidth(640)

        # --- account row
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(240)
        self.session_label = QLabel(UI.SESSION_UNKNOWN)
        self.sign_in_button = QPushButton(UI.BTN_SIGN_IN)
        self.accounts_button = QPushButton(UI.BTN_ACCOUNTS)
        self.settings_button = QPushButton(UI.BTN_SETTINGS)
        self.log_button = QPushButton(UI.BTN_LOG)
        top = QHBoxLayout()
        top.addWidget(QLabel(UI.ACCOUNT))
        top.addWidget(self.account_combo, 1)
        top.addWidget(self.session_label)
        top.addWidget(self.sign_in_button)
        tools = QHBoxLayout()
        tools.addWidget(self.accounts_button)
        tools.addWidget(self.settings_button)
        tools.addWidget(self.log_button)
        tools.addStretch(1)

        # --- job
        today = date.today()
        self.date_from = QDateEdit(to_qdate(date(today.year, 1, 1)))
        self.date_to = QDateEdit(to_qdate(today))
        for edit in (self.date_from, self.date_to):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("dd.MM.yyyy")
        self.all_time = QCheckBox(UI.ALL_TIME)
        self.preset_this_year = QPushButton(UI.PRESET_THIS_YEAR)
        self.preset_last_year = QPushButton(UI.PRESET_LAST_YEAR)
        self.preset_30_days = QPushButton(UI.PRESET_30_DAYS)
        self.hint = QLabel()
        self.hint.setStyleSheet("color: #B26A00;")
        self.start_button = QPushButton(UI.BTN_START)
        self.pause_button = QPushButton(UI.BTN_PAUSE)
        self.stop_button = QPushButton(UI.BTN_STOP)
        dates = QHBoxLayout()
        dates.addWidget(QLabel(UI.DATE_FROM))
        dates.addWidget(self.date_from)
        dates.addWidget(QLabel(UI.DATE_TO))
        dates.addWidget(self.date_to)
        dates.addSpacing(12)
        dates.addWidget(self.all_time)
        dates.addStretch(1)
        presets = QHBoxLayout()
        for button in (self.preset_this_year, self.preset_last_year, self.preset_30_days):
            presets.addWidget(button)
        presets.addStretch(1)
        actions = QHBoxLayout()
        actions.addWidget(self.start_button)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.stop_button)
        actions.addWidget(self.hint, 1)
        job_box = QGroupBox(UI.GROUP_JOB)
        job_layout = QVBoxLayout(job_box)
        job_layout.addLayout(dates)
        job_layout.addLayout(presets)
        job_layout.addLayout(actions)

        # --- progress
        self.status_label = QLabel(UI.STATUS.format(state=strings.STATUS_IDLE))
        self.plan_label = QLabel()
        self.plan_label.setWordWrap(True)
        self._reserve_lines(self.plan_label, 3)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.files_label = QLabel()
        self.bytes_label = QLabel()
        self.speed_label = QLabel()
        self.eta_label = QLabel()
        self.current_label = QLabel()
        self.current_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid = QGridLayout()
        grid.addWidget(self.files_label, 0, 0)
        grid.addWidget(self.bytes_label, 0, 1)
        grid.addWidget(self.speed_label, 1, 0)
        grid.addWidget(self.eta_label, 1, 1)
        progress_box = QGroupBox(UI.GROUP_PROGRESS)
        progress_layout = QVBoxLayout(progress_box)
        progress_layout.addWidget(self.status_label)
        progress_layout.addWidget(self.plan_label)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addLayout(grid)
        progress_layout.addWidget(self.current_label)

        # --- last run
        self.last_label = QLabel(UI.LAST_NONE)
        self.last_label.setWordWrap(True)
        self._reserve_lines(self.last_label, 3)
        self.errors_button = QPushButton(UI.BTN_SHOW_ERRORS)
        self.folder_button = QPushButton(UI.BTN_OPEN_FOLDER)
        last_buttons = QHBoxLayout()
        last_buttons.addWidget(self.errors_button)
        last_buttons.addWidget(self.folder_button)
        last_buttons.addStretch(1)
        last_box = QGroupBox(UI.GROUP_LAST)
        last_layout = QVBoxLayout(last_box)
        last_layout.addWidget(self.last_label)
        last_layout.addLayout(last_buttons)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addLayout(tools)
        layout.addWidget(job_box)
        layout.addWidget(progress_box)
        layout.addWidget(last_box)
        layout.addStretch(1)
        self.setCentralWidget(central)

        # --- tray
        self.tray: Tray | None = None
        if use_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = Tray(self)
            self.tray.show()

        # --- wiring
        self.account_combo.activated.connect(self._account_chosen)
        self.sign_in_button.clicked.connect(self.sign_in)
        self.accounts_button.clicked.connect(lambda: run_dialog(AccountsDialog(controller, self)))
        self.settings_button.clicked.connect(self._open_settings)
        self.log_button.clicked.connect(lambda: run_dialog(LogDialog(self)))
        self.all_time.toggled.connect(self._update_controls)
        self.date_from.dateChanged.connect(self._update_controls)
        self.date_to.dateChanged.connect(self._update_controls)
        self.preset_this_year.clicked.connect(lambda: self.set_period(date(date.today().year, 1, 1), date.today()))
        self.preset_last_year.clicked.connect(
            lambda: self.set_period(date(date.today().year - 1, 1, 1), date(date.today().year - 1, 12, 31))
        )
        self.preset_30_days.clicked.connect(lambda: self.set_period(date.today() - timedelta(days=30), date.today()))
        self.start_button.clicked.connect(self.start_job)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.stop_button.clicked.connect(controller.stop_job)
        self.errors_button.clicked.connect(lambda: run_dialog(ProblemsDialog(controller.problems(), self)))
        self.folder_button.clicked.connect(self._open_root)

        controller.accounts_changed.connect(self._refresh_accounts)
        controller.session_changed.connect(self._on_session)
        controller.job_state.connect(self._on_job_state)
        controller.job_plan.connect(self._on_plan)
        controller.job_finished.connect(self._on_job_finished)
        controller.notify.connect(self._on_notify)

        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._refresh_accounts()
        self._on_session(*controller.session_state())
        self._tick()

    @staticmethod
    def _reserve_lines(label: QLabel, lines: int) -> None:
        """Keep room for multi-line text so it is never clipped when it appears."""
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        label.setMinimumHeight(label.fontMetrics().lineSpacing() * lines + 4)

    # ----------------------------------------------------------- account

    def _refresh_accounts(self) -> None:
        active = self.controller.active()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for account in self.controller.accounts():
            self.account_combo.addItem(account.apple_id, account.apple_id)
        if active is not None:
            self.account_combo.setCurrentIndex(self.account_combo.findData(active.apple_id))
        else:
            self.account_combo.addItem(UI.NO_ACCOUNTS)
        self.account_combo.blockSignals(False)
        self._update_controls()

    def _account_chosen(self, index: int) -> None:
        apple_id = self.account_combo.itemData(index)
        active = self.controller.active()
        if not apple_id or (active and active.apple_id == apple_id):
            return
        if not self.controller.set_active(apple_id):
            QMessageBox.information(self, UI.APP_TITLE, UI.SWITCH_WHILE_RUNNING)
            self._refresh_accounts()

    def sign_in(self) -> None:
        if self.controller.active() is None:
            add_account(self, self.controller)
        else:
            sign_in_again(self, self.controller)

    def _open_settings(self) -> None:
        if self.controller.active() is None:
            add_account(self, self.controller)
            return
        run_dialog(SettingsDialog(self.controller, self))

    def _open_root(self) -> None:
        root = self.controller.root_dir()
        if root is not None and root.is_dir():
            open_folder(root)

    def _on_session(self, state: str, message: str) -> None:
        text = {
            SESSION_CHECKING: UI.SESSION_CHECKING,
            SESSION_OK: UI.SESSION_OK,
            SESSION_EXPIRED: UI.SESSION_EXPIRED,
            SESSION_ERROR: UI.SESSION_ERROR.format(message=message),
        }.get(state, UI.SESSION_UNKNOWN)
        self.session_label.setText(text)
        color = {SESSION_OK: "#2E9E5B", SESSION_EXPIRED: "#C8443C", SESSION_ERROR: "#C8443C"}.get(state, "")
        self.session_label.setStyleSheet(f"color: {color};" if color else "")
        self._update_controls()
        if state == SESSION_OK:
            QTimer.singleShot(0, self._offer_resume)

    def _offer_resume(self) -> None:
        """Once per account per run: offer to continue an interrupted job."""
        account = self.controller.active()
        if account is None or account.apple_id in self._resume_offered or self.controller.can_start():
            return
        self._resume_offered.add(account.apple_id)
        pending = self.controller.unfinished_job()
        if pending is None:
            return
        period = Period(
            date.fromisoformat(pending.date_from) if pending.date_from else None,
            date.fromisoformat(pending.date_to) if pending.date_to else None,
        )
        label = strings.PERIOD_ALL if period.unbounded else period.label()
        question = strings.RESUME_PROMPT.format(period=label, done=pending.done_files, total=pending.total_files)
        if QMessageBox.question(self, UI.RESUME_TITLE, question) == QMessageBox.StandardButton.Yes:
            self.show_period(period)
            self.controller.start_job(period)

    # ------------------------------------------------------------ period

    def set_period(self, start: date, end: date) -> None:
        self.all_time.setChecked(False)
        self.date_from.setDate(to_qdate(start))
        self.date_to.setDate(to_qdate(end))

    def show_period(self, period: Period) -> None:
        if period.unbounded:
            self.all_time.setChecked(True)
        elif period.date_from and period.date_to:
            self.set_period(period.date_from, period.date_to)

    def period(self) -> Period | None:
        """The period on screen, or None when it is not valid."""
        if self.all_time.isChecked():
            return Period()
        start, end = self.date_from.date().toPython(), self.date_to.date().toPython()
        if start > end:
            return None
        return Period(start, end)

    def start_job(self) -> None:
        period = self.period()
        if period is None or self.controller.can_start():
            self._update_controls()
            return
        self._samples.clear()
        self.plan_label.setText("")
        self.controller.start_job(period)
        self._update_controls()

    def toggle_pause(self) -> None:
        if self.controller.job_state_name == "paused":
            self.controller.resume_job()
        else:
            self.controller.pause_job()

    # ------------------------------------------------------------- state

    def _update_controls(self, *_ignored) -> None:
        running = self.controller.is_job_running
        state = self.controller.job_state_name
        blocked = self.controller.can_start()
        period_ok = self.period() is not None
        hint = ""
        if not running:
            hint = blocked or ("" if period_ok else UI.HINT_BAD_PERIOD)
        self.hint.setText(hint)
        self.start_button.setEnabled(not running and not blocked and period_ok)
        self.pause_button.setEnabled(running)
        self.pause_button.setText(UI.BTN_RESUME if state == "paused" else UI.BTN_PAUSE)
        self.stop_button.setEnabled(running)
        for widget in (self.date_from, self.date_to):
            widget.setEnabled(not running and not self.all_time.isChecked())
        for widget in (self.all_time, self.preset_this_year, self.preset_last_year, self.preset_30_days):
            widget.setEnabled(not running)
        self.account_combo.setEnabled(not running and bool(self.controller.accounts()))
        session = self.controller.session_state()[0]
        self.sign_in_button.setVisible(self.controller.active() is None or session in (SESSION_EXPIRED, SESSION_ERROR))
        self.settings_button.setEnabled(self.controller.active() is not None)
        self.folder_button.setEnabled(self.controller.root_dir() is not None)
        self.errors_button.setEnabled(bool(self.controller.problems()))

    def _on_job_state(self, state: str) -> None:
        self.status_label.setText(UI.STATUS.format(state=STATE_LABELS.get(state, state)))
        self.setWindowIcon(icons.icon("error" if state == "error" else ("active" if self.controller.is_job_running else "idle")))
        self._update_controls()
        self._tick()

    def _on_plan(self, plan: Plan) -> None:
        lines = [
            strings.PLAN_SUMMARY.format(
                total=plan.files_in_period,
                present=plan.files_present,
                todo=plan.files_to_download,
                size=format_size(plan.bytes_to_download),
            )
        ]
        if plan.boundary_assets:
            lines.append(strings.PLAN_BOUNDARY.format(count=plan.boundary_assets))
        if plan.compact_to_make:
            lines.append(strings.PLAN_COMPACT.format(count=plan.compact_to_make, size=format_size(plan.compact_bytes)))
        if plan.conflicts:
            lines.append(strings.PLAN_CONFLICTS.format(count=len(plan.conflicts)))
        self.plan_label.setText("\n".join(lines))

    def _on_job_finished(self, report: Report | None, error: str) -> None:
        if report is None:
            self.last_label.setText(UI.LAST_STOPPED.format(reason=error))
        else:
            lines = [
                UI.LAST_SUMMARY.format(
                    downloaded=report.downloaded,
                    skipped=report.skipped,
                    errors=len(report.errors),
                    conflicts=len(report.conflicts),
                ),
                UI.LAST_COMPACT.format(made=report.compact_made, errors=len(report.compact_errors)),
            ]
            if report.stopped_reason:
                lines.append(UI.LAST_STOPPED.format(reason=report.stopped_reason))
            self.last_label.setText("\n".join(lines))
        self._update_controls()
        self._tick()

    def _on_notify(self, title: str, text: str, kind: str) -> None:
        if self.tray is not None:
            self.tray.announce(title, text, kind)
        elif kind == "error" and self.isVisible():
            QMessageBox.warning(self, title, text)

    def _tick(self) -> None:
        done_files, total_files, done_bytes, total_bytes, current = self.controller.progress.snapshot()
        running = self.controller.is_job_running
        state = self.controller.job_state_name
        now = time.monotonic()
        speed = 0.0
        if running and state == "downloading":
            self._samples.append((now, done_bytes))
            while len(self._samples) > 2 and now - self._samples[0][0] > SPEED_WINDOW_SECONDS:
                self._samples.popleft()
            span = now - self._samples[0][0]
            if span > 0.3:
                speed = (done_bytes - self._samples[0][1]) / span
        else:
            self._samples.clear()

        self.files_label.setText(UI.PROGRESS_FILES.format(done=done_files, total=total_files))
        self.bytes_label.setText(
            UI.PROGRESS_BYTES.format(done=format_size(done_bytes), total=format_size(total_bytes))
        )
        self.speed_label.setText(UI.PROGRESS_SPEED.format(speed=format_size(speed) if speed else UI.DASH))
        remaining = max(0, total_bytes - done_bytes)
        eta = format_eta(remaining / speed) if speed > 0 and remaining else UI.DASH
        self.eta_label.setText(UI.PROGRESS_ETA.format(eta=eta))
        self.current_label.setText(UI.PROGRESS_CURRENT.format(name=current if running and current else UI.DASH))
        if state == "counting":
            self.progress_bar.setRange(0, 0)  # busy indicator while counting
        else:
            self.progress_bar.setRange(0, 1000)
            fraction = min(1.0, done_bytes / total_bytes) if total_bytes else (1.0 if total_files and done_files >= total_files else 0.0)
            self.progress_bar.setValue(int(fraction * 1000))
        if self.tray is not None:
            self.tray.reflect(state, running, done_files, total_files)

    # ------------------------------------------------------- window life

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting or self.tray is None:
            if not self._quitting and not self._confirm_exit():
                event.ignore()
                return
            self.controller.shutdown()
            event.accept()
            return
        # The cross hides the window; the app lives on in the tray.
        event.ignore()
        self.hide()
        if not self._told_about_tray:
            self._told_about_tray = True
            self.tray.announce(UI.APP_TITLE, UI.NOTE_TO_TRAY, "info")

    def _confirm_exit(self) -> bool:
        if not self.controller.is_job_running:
            return True
        answer = QMessageBox.question(self, UI.APP_TITLE, UI.CONFIRM_EXIT_RUNNING)
        return answer == QMessageBox.StandardButton.Yes

    def quit_app(self) -> None:
        if not self._confirm_exit():
            return
        self._quitting = True
        self.timer.stop()
        self.controller.shutdown()
        if self.tray is not None:
            self.tray.hide()
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()
