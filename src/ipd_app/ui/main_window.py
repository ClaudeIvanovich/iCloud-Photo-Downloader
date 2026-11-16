"""Main window: account, period job, progress, last run. Plus the tray icon."""

from __future__ import annotations

import time
from collections import deque
from datetime import date, timedelta

from PySide6.QtCore import QDate, QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import strings
from ..strings import UI, format_size
from ..sync_engine import Period, Plan, Report
from . import icons, theme
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

# Names, not texts: the language is chosen after this module is imported.
STATE_TEXT_NAMES = {
    "idle": "STATUS_IDLE",
    "counting": "STATUS_COUNTING",
    "downloading": "STATUS_DOWNLOADING",
    "paused": "STATUS_PAUSED",
    "error": "STATUS_ERROR",
}


def state_label(state: str) -> str:
    name = STATE_TEXT_NAMES.get(state)
    return getattr(strings, name) if name else state


SPEED_WINDOW_SECONDS = 5.0
# The job is "searching" when files keep being checked and no bytes arrive for this long.
SEARCH_AFTER_SECONDS = 2.0


def format_eta(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return UI.ETA_SECONDS.format(s=seconds)
    if seconds < 3600:
        return UI.ETA_MINUTES.format(m=seconds // 60, s=seconds % 60)
    return UI.ETA_HOURS.format(h=seconds // 3600, m=seconds % 3600 // 60)


def to_qdate(value: date) -> QDate:
    return QDate(value.year, value.month, value.day)


class ElidedLabel(QLabel):
    """One centred line; a text that does not fit loses its middle, not its ends,
    so both the start of a file name and its extension stay readable."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt name
        self._full = text
        self._fit()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt name
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(self.width() - 4, 0))
        if shown != self.text():
            super().setText(shown)


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
        self._seen_bytes = 0
        self._seen_checked = 0
        self._bytes_at = float("-inf")
        self._checked_at = float("-inf")
        self._searching = False
        self.setWindowTitle(UI.APP_TITLE)
        self.setWindowIcon(icons.icon("idle"))

        # --- header: who is signed in, and the rarely used windows as icons
        self.account_combo = QComboBox()
        self.account_combo.setProperty("flat", True)
        self.account_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.account_combo.setToolTip(UI.ACCOUNT.rstrip(":： "))
        self.session_label = QLabel(UI.SESSION_UNKNOWN)
        self.sign_in_button = QPushButton(UI.BTN_SIGN_IN)
        self.sign_in_button.setProperty("primary", True)
        self.accounts_button = self._tool_button(theme.GLYPH_ACCOUNTS, UI.BTN_ACCOUNTS)
        self.settings_button = self._tool_button(theme.GLYPH_SETTINGS, UI.BTN_SETTINGS)
        self.log_button = self._tool_button(theme.GLYPH_LOG, UI.BTN_LOG)
        # Every language under its own name, so the list is readable in any of them.
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("language_combo")
        self.language_combo.setProperty("quiet", True)
        self.language_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.language_combo.setToolTip(UI.LANGUAGE.rstrip(":： "))
        self.language_combo.addItem(UI.LANGUAGE_AUTO, strings.AUTO)
        for code, name in strings.LANGUAGES.items():
            self.language_combo.addItem(name, code)
        saved = self.language_combo.findData(controller.config.language)
        self.language_combo.setCurrentIndex(max(saved, 0))
        self.language_combo.activated.connect(self._language_chosen)
        header = QHBoxLayout()
        header.setSpacing(6)
        header.addWidget(self.account_combo)
        header.addWidget(self.session_label)
        header.addWidget(self.sign_in_button)
        header.addStretch(1)
        header.addWidget(self.language_combo)
        header.addWidget(self.accounts_button)
        header.addWidget(self.settings_button)
        header.addWidget(self.log_button)

        # --- period: the dates are always in sight, the usual ranges are one click
        today = date.today()
        self.date_from = QDateEdit(to_qdate(date(today.year, 1, 1)))
        self.date_to = QDateEdit(to_qdate(today))
        for edit in (self.date_from, self.date_to):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat(UI.DATE_DISPLAY)
            edit.setMinimumWidth(128)
        self.preset_last_year = QPushButton(UI.PRESET_LAST_YEAR)
        self.preset_30_days = QPushButton(UI.PRESET_30_DAYS)
        self.all_time = QPushButton(UI.ALL_TIME)
        for chip in (self.preset_last_year, self.preset_30_days, self.all_time):
            chip.setProperty("chip", True)
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
        dates = QHBoxLayout()
        dates.setSpacing(8)
        dates.addWidget(self._caption(UI.DATE_FROM))
        dates.addWidget(self.date_from)
        dates.addWidget(self._caption(UI.DATE_TO))
        dates.addWidget(self.date_to)
        dates.addStretch(1)
        for chip in (self.preset_last_year, self.preset_30_days, self.all_time):
            dates.addWidget(chip)
        period_card, period_layout, _ = self._card(UI.GROUP_JOB)
        period_layout.addLayout(dates)

        # --- progress: one big number, one bar, one main button
        self.status_label = self._caption(UI.STATUS.format(state=strings.STATUS_IDLE))
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("percent")
        self.percent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setTextVisible(False)
        self._bar_animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._bar_animation.setDuration(350)
        self._bar_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animate = theme.animations_enabled()
        self.files_label = self._caption("")
        self.bytes_label = self._caption("")
        self.speed_label = self._caption("")
        self.eta_label = self._caption("")
        self.eta_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.current_label = ElidedLabel()
        self.current_label.setProperty("role", "muted")
        self.plan_label = self._caption("")
        self.plan_label.setWordWrap(True)
        self._reserve_lines(self.plan_label, 2)
        self.plan_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.hint = QLabel()
        self.hint.setProperty("role", "warning")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)
        self.start_button = QPushButton(UI.BTN_START)
        self.pause_button = QPushButton(UI.BTN_PAUSE)
        self.stop_button = QPushButton(UI.BTN_STOP)
        for button in (self.start_button, self.pause_button, self.stop_button):
            button.setProperty("big", True)
        self.start_button.setProperty("primary", True)
        self.pause_button.setProperty("primary", True)
        counts = QHBoxLayout()
        counts.setSpacing(6)
        counts.addStretch(1)
        counts.addWidget(self.files_label)
        counts.addWidget(self._caption("·"))
        counts.addWidget(self.bytes_label)
        counts.addStretch(1)
        # speed on the left, time on the right, the file in the middle takes what is left
        rates = QHBoxLayout()
        rates.setSpacing(12)
        rates.addWidget(self.speed_label, 1)
        rates.addWidget(self.current_label, 2)
        rates.addWidget(self.eta_label, 1)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch(1)
        actions.addWidget(self.start_button)
        actions.addWidget(self.pause_button)
        actions.addWidget(self.stop_button)
        actions.addStretch(1)
        progress_card, progress_layout, progress_head = self._card(UI.GROUP_PROGRESS)
        progress_head.addWidget(self.status_label)
        progress_layout.addWidget(self.percent_label)
        progress_layout.addLayout(counts)
        progress_layout.addSpacing(6)
        progress_layout.addWidget(self.progress_bar)
        progress_layout.addLayout(rates)
        progress_layout.addSpacing(8)
        progress_layout.addLayout(actions)
        progress_layout.addWidget(self.hint)
        progress_layout.addWidget(self.plan_label)

        # --- last run
        self.last_label = QLabel(UI.LAST_NONE)
        self.last_label.setWordWrap(True)
        self._reserve_lines(self.last_label, 3)
        self.errors_button = QPushButton(UI.BTN_SHOW_ERRORS)
        self.folder_button = QPushButton(UI.BTN_OPEN_FOLDER)
        last_buttons = QVBoxLayout()
        last_buttons.addWidget(self.folder_button)
        last_buttons.addWidget(self.errors_button)
        last_buttons.addStretch(1)
        last_card, last_layout, _ = self._card(UI.GROUP_LAST)
        last_row = QHBoxLayout()
        last_row.setSpacing(12)
        last_row.addWidget(self.last_label, 1)
        last_row.addLayout(last_buttons)
        last_layout.addLayout(last_row)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(period_card)
        layout.addWidget(progress_card)
        layout.addWidget(last_card)
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
        # No fixed minimum width: the layout knows how much the texts of the chosen
        # language need, and a fixed number would let the window clip them.
        self.resize(max(680, self.sizeHint().width()), self.sizeHint().height())

    @staticmethod
    def _card(title: str) -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
        """A rounded panel with a small heading; the style sheet draws it.

        Returns the panel, its layout and the heading row, where a note can sit on the right."""
        card = QFrame()
        card.setProperty("card", True)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setProperty("role", "title")
        head = QHBoxLayout()
        head.addWidget(heading)
        head.addStretch(1)
        layout.addLayout(head)
        return card, layout, head

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("role", "muted")
        return label

    @staticmethod
    def _tool_button(glyph: str, name: str) -> QAbstractButton:
        """An icon for a window that is opened rarely; its name is in the tooltip."""
        plain = name.rstrip("….")
        if not theme.has_icon_font():
            return QPushButton(name)
        button = QToolButton()
        button.setText(glyph)
        button.setFont(theme.icon_font(16))
        button.setToolTip(plain)
        button.setAccessibleName(plain)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

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

    def _language_chosen(self, index: int) -> None:
        choice = self.language_combo.itemData(index)
        if choice == self.controller.config.language:
            return
        self.controller.set_language(choice)
        if strings.resolve_language(choice) != strings.current_language:
            QMessageBox.information(self, UI.APP_TITLE, UI.LANGUAGE_RESTART)

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
        role = {SESSION_OK: "success", SESSION_EXPIRED: "danger", SESSION_ERROR: "danger"}.get(state, "muted")
        theme.set_role(self.session_label, role)
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
        self.hint.setVisible(bool(hint))
        self.start_button.setEnabled(not running and not blocked and period_ok)
        self.start_button.setVisible(not running)
        self.pause_button.setVisible(running)
        self.stop_button.setVisible(running)
        self._mark_presets()
        self.pause_button.setEnabled(running)
        self.pause_button.setText(UI.BTN_RESUME if state == "paused" else UI.BTN_PAUSE)
        self.stop_button.setEnabled(running)
        for widget in (self.date_from, self.date_to):
            widget.setEnabled(not running and not self.all_time.isChecked())
        for widget in (self.all_time, self.preset_last_year, self.preset_30_days):
            widget.setEnabled(not running)
        self.account_combo.setEnabled(not running and bool(self.controller.accounts()))
        session = self.controller.session_state()[0]
        self.sign_in_button.setVisible(self.controller.active() is None or session in (SESSION_EXPIRED, SESSION_ERROR))
        self.settings_button.setEnabled(self.controller.active() is not None)
        self.folder_button.setEnabled(self.controller.root_dir() is not None)
        self.errors_button.setEnabled(bool(self.controller.problems()))

    def _mark_presets(self) -> None:
        """Light up the chip whose range is the one in the date fields."""
        today = date.today()
        shown = None if self.all_time.isChecked() else self.period()
        ranges = {
            self.preset_last_year: Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)),
            self.preset_30_days: Period(today - timedelta(days=30), today),
        }
        for chip, period in ranges.items():
            chip.blockSignals(True)
            chip.setChecked(shown == period)
            chip.blockSignals(False)

    def _on_job_state(self, state: str) -> None:
        self.status_label.setText(UI.STATUS.format(state=state_label(state)))
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
        # A job that resumes, or goes back for a few files, first runs through
        # everything already on disk. Nothing downloads then: say what is going on.
        checked = self.controller.progress.checked_files()
        if done_bytes != self._seen_bytes:
            self._seen_bytes, self._bytes_at = done_bytes, now
        if checked != self._seen_checked:
            self._seen_checked, self._checked_at = checked, now
        searching = (
            running
            and state == "downloading"
            and now - self._checked_at < SEARCH_AFTER_SECONDS
            and now - self._bytes_at >= SEARCH_AFTER_SECONDS
        )
        if searching != self._searching:
            self._searching = searching
            if searching:
                self.status_label.setText(UI.STATUS.format(state=strings.STATUS_SEARCHING))
            elif running:
                self.status_label.setText(UI.STATUS.format(state=state_label(state)))

        remaining = max(0, total_bytes - done_bytes)
        eta = format_eta(remaining / speed) if speed > 0 and remaining else UI.DASH
        showing = running and state != "counting" and not searching
        self.speed_label.setText(
            UI.PROGRESS_SPEED.format(speed=format_size(speed) if speed else UI.DASH) if showing else ""
        )
        self.eta_label.setText(UI.PROGRESS_ETA.format(eta=eta) if showing else "")
        name = current if showing and current else ""
        if searching:
            self.current_label.setText(UI.PROGRESS_CHECKED.format(count=checked))
        else:
            self.current_label.setText(name.replace("\\", "/").rsplit("/", 1)[-1])
        self.current_label.setToolTip(UI.PROGRESS_CURRENT.format(name=name) if name else "")
        if total_bytes:
            fraction = min(1.0, done_bytes / total_bytes)
        else:
            fraction = 1.0 if total_files and done_files >= total_files else 0.0
        self.percent_label.setText(f"{int(fraction * 100)}%")
        theme.set_role(self.percent_label, "" if running or fraction else "muted")
        if state == "counting" or (searching and not done_bytes):
            self._bar_animation.stop()
            self.progress_bar.setRange(0, 0)  # busy indicator: counting, or nothing fetched yet
        else:
            self.progress_bar.setRange(0, 1000)
            self._move_bar(int(fraction * 1000))
        if self.tray is not None:
            self.tray.reflect(state, running, done_files, total_files)

    def _move_bar(self, target: int) -> None:
        """Glide to the new value from wherever the bar is now; jump when it goes back."""
        current = self.progress_bar.value()
        if not self._animate or not self.isVisible() or target <= current:
            self._bar_animation.stop()
            self.progress_bar.setValue(target)
            return
        running = self._bar_animation.state() == QPropertyAnimation.State.Running
        if running and self._bar_animation.endValue() == target:
            return
        self._bar_animation.stop()
        self._bar_animation.setStartValue(current)
        self._bar_animation.setEndValue(target)
        self._bar_animation.start()

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
