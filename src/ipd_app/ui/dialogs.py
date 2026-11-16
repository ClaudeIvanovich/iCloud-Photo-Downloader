"""Secondary windows: accounts, settings, log, errors of the last run."""

from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFontDatabase
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..strings import UI
from ..sync_engine.filters import COMPACT_SIZES
from .controller import Controller
from .login_dialog import LoginDialog


def run_dialog(dialog: QDialog) -> int:
    """Show a modal dialog and release it afterwards. A dialog with a parent is
    otherwise kept alive until the main window is destroyed."""
    try:
        return dialog.exec()
    finally:
        dialog.deleteLater()


def open_folder(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def choose_root(parent: QWidget, controller: Controller) -> bool:
    """Folder picker for the active account. Returns True when a folder was set."""
    account = controller.active()
    if account is None:
        return False
    start = account.root_dir or str(Path.home())
    chosen = QFileDialog.getExistingDirectory(parent, UI.ROOT_DIALOG, start)
    if not chosen:
        return False
    controller.update_active(root_dir=os.path.normpath(chosen))
    others = controller.shared_root_accounts()
    if others:
        QMessageBox.warning(parent, UI.APP_TITLE, UI.SHARED_ROOT_WARNING.format(others=", ".join(others)))
    return True


def add_account(parent: QWidget, controller: Controller) -> bool:
    """Sign in to a new account, then ask for its folder straight away."""
    known = {account.apple_id for account in controller.accounts()}
    if run_dialog(LoginDialog(controller, parent=parent)) != QDialog.DialogCode.Accepted:
        return False
    account = controller.active()
    if account is not None and account.apple_id not in known and not account.root_dir:
        QMessageBox.information(parent, UI.APP_TITLE, UI.CHOOSE_ROOT_FIRST)
        choose_root(parent, controller)
    return True


def sign_in_again(parent: QWidget, controller: Controller) -> bool:
    account = controller.active()
    if account is None:
        return add_account(parent, controller)
    dialog = LoginDialog(controller, account.apple_id, parent)
    dialog.start_with_saved_password()
    return run_dialog(dialog) == QDialog.DialogCode.Accepted


# --------------------------------------------------------------------------


class AccountsDialog(QDialog):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(UI.ACCOUNTS_TITLE)
        self.setMinimumSize(560, 320)
        self.list = QListWidget()
        self.add_button = QPushButton(UI.BTN_ADD)
        self.add_button.setProperty("primary", True)
        self.switch_button = QPushButton(UI.BTN_SWITCH)
        self.logout_button = QPushButton(UI.BTN_LOGOUT)
        self.remove_button = QPushButton(UI.BTN_REMOVE)
        close = QPushButton(UI.BTN_CLOSE)
        side = QVBoxLayout()
        for button in (self.add_button, self.switch_button, self.logout_button, self.remove_button):
            side.addWidget(button)
        side.addStretch(1)
        side.addWidget(close)
        layout = QHBoxLayout(self)
        layout.addWidget(self.list, 1)
        layout.addLayout(side)

        self.add_button.clicked.connect(lambda: add_account(self, controller))
        self.switch_button.clicked.connect(self._switch)
        self.logout_button.clicked.connect(self._logout)
        self.remove_button.clicked.connect(self._remove)
        close.clicked.connect(self.accept)
        self.list.currentRowChanged.connect(lambda _row: self._update_buttons())
        controller.accounts_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        selected = self.selected()
        self.list.clear()
        active = self.controller.active()
        for account in self.controller.accounts():
            is_active = active is not None and account.apple_id == active.apple_id
            label = account.apple_id + (UI.ACTIVE_MARK if is_active else "")
            item = QListWidgetItem(f"{label}\n{account.root_dir or UI.ROOT_EMPTY}")
            item.setData(Qt.ItemDataRole.UserRole, account.apple_id)
            self.list.addItem(item)
            if account.apple_id == selected or (selected is None and is_active):
                self.list.setCurrentItem(item)
        self._update_buttons()

    def selected(self) -> str | None:
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_buttons(self) -> None:
        chosen = self.selected()
        active = self.controller.active()
        is_active = chosen is not None and active is not None and chosen == active.apple_id
        self.switch_button.setEnabled(chosen is not None and not is_active)
        self.logout_button.setEnabled(chosen is not None)
        self.remove_button.setEnabled(chosen is not None)

    def _switch(self) -> None:
        chosen = self.selected()
        if chosen and not self.controller.set_active(chosen):
            QMessageBox.information(self, UI.APP_TITLE, UI.SWITCH_WHILE_RUNNING)

    def _confirm(self, text: str) -> bool:
        answer = QMessageBox.question(self, UI.APP_TITLE, text)
        return answer == QMessageBox.StandardButton.Yes

    def _logout(self) -> None:
        chosen = self.selected()
        if chosen and self._confirm(UI.CONFIRM_LOGOUT.format(account=chosen)):
            if not self.controller.sign_out(chosen):
                QMessageBox.information(self, UI.APP_TITLE, UI.SWITCH_WHILE_RUNNING)

    def _remove(self) -> None:
        chosen = self.selected()
        if chosen and self._confirm(UI.CONFIRM_REMOVE.format(account=chosen)):
            if not self.controller.remove_account(chosen):
                QMessageBox.information(self, UI.APP_TITLE, UI.SWITCH_WHILE_RUNNING)


# --------------------------------------------------------------------------


class SettingsDialog(QDialog):
    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        account = controller.active()
        assert account is not None
        self.setWindowTitle(UI.SETTINGS_TITLE.format(account=account.apple_id))
        self.setMinimumWidth(560)
        tabs = QTabWidget()

        # folder
        self.root_label = QLabel(account.root_dir or UI.ROOT_EMPTY)
        self.root_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.root_label.setWordWrap(True)
        choose = QPushButton(UI.BTN_CHOOSE)
        choose.clicked.connect(self._choose_root)
        folder = QWidget()
        folder_layout = QVBoxLayout(folder)
        folder_layout.addWidget(QLabel(UI.ROOT_LABEL))
        row = QHBoxLayout()
        row.addWidget(self.root_label, 1)
        row.addWidget(choose)
        folder_layout.addLayout(row)
        folder_layout.addWidget(self._note(UI.ROOT_NOTE))
        self.shared_warning = self._note("")
        self.shared_warning.setProperty("role", "warning")
        folder_layout.addWidget(self.shared_warning)
        folder_layout.addStretch(1)
        tabs.addTab(folder, UI.TAB_FOLDER)

        # compact
        self.compact_enabled = QCheckBox(UI.COMPACT_ENABLED)
        self.compact_enabled.setChecked(account.compact_enabled)
        self.compact_size = QComboBox()
        for size in COMPACT_SIZES:
            self.compact_size.addItem(UI.COMPACT_SIZE_ORIGINAL if size is None else UI.COMPACT_SIZE_PX.format(px=size), size)
        self.compact_size.setCurrentIndex(max(0, self.compact_size.findData(account.compact_long_side)))
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(60, 95)
        self.quality.setValue(account.compact_quality)
        self.quality_value = QLabel(str(account.compact_quality))
        self.quality.valueChanged.connect(lambda value: self.quality_value.setText(str(value)))
        quality_row = QHBoxLayout()
        quality_row.addWidget(self.quality, 1)
        quality_row.addWidget(self.quality_value)
        compact = QWidget()
        compact_form = QFormLayout(compact)
        compact_form.addRow(self.compact_enabled)
        compact_form.addRow(UI.COMPACT_SIZE, self.compact_size)
        compact_form.addRow(UI.COMPACT_QUALITY, quality_row)
        compact_form.addRow(self._note(UI.COMPACT_NOTE))
        tabs.addTab(compact, UI.TAB_COMPACT)

        # filters
        self.photos = QCheckBox(UI.MEDIA_PHOTOS)
        self.photos.setChecked(account.photos)
        self.videos = QCheckBox(UI.MEDIA_VIDEOS)
        self.videos.setChecked(account.videos)
        self.live_video = QCheckBox(UI.LIVE_VIDEO)
        self.live_video.setChecked(account.live_video)
        self.edited = QCheckBox(UI.EDITED)
        self.edited.setChecked(account.edited)
        self.source_all = QRadioButton(UI.SOURCE_ALL)
        self.source_albums = QRadioButton(UI.SOURCE_ALBUMS)
        (self.source_albums if account.albums else self.source_all).setChecked(True)
        self.albums = QListWidget()
        self.albums.setMinimumHeight(120)
        self.load_albums = QPushButton(UI.BTN_LOAD_ALBUMS)
        self.albums_status = self._note("")
        self._fill_albums(account.albums or [], set(account.albums or []))
        media_row = QHBoxLayout()
        media_row.setSpacing(24)
        media_row.addWidget(self.photos)
        media_row.addWidget(self.videos)
        media_row.addStretch(1)
        filters = QWidget()
        filters_layout = QVBoxLayout(filters)
        filters_layout.addLayout(media_row)
        filters_layout.addWidget(self.live_video)
        filters_layout.addWidget(self.edited)
        filters_layout.addSpacing(8)
        filters_layout.addWidget(self.source_all)
        filters_layout.addWidget(self.source_albums)
        filters_layout.addWidget(self.albums)
        albums_row = QHBoxLayout()
        albums_row.addWidget(self.load_albums)
        albums_row.addWidget(self.albums_status, 1)
        filters_layout.addLayout(albums_row)
        filters_layout.addWidget(self._note(UI.ALWAYS_EXCLUDED))
        tabs.addTab(filters, UI.TAB_FILTERS)
        self.source_albums.toggled.connect(self._sync_album_widgets)
        self.load_albums.clicked.connect(self._load_albums)
        controller.albums_loaded.connect(self._on_albums)
        self._sync_album_widgets()

        # download
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 8)
        self.concurrency.setValue(account.concurrency)
        self.concurrency.setMaximumWidth(140)
        self.min_free = QDoubleSpinBox()
        self.min_free.setRange(0.5, 1000.0)
        self.min_free.setDecimals(1)
        self.min_free.setSuffix(UI.GB)
        self.min_free.setValue(account.min_free_gb)
        self.min_free.setMaximumWidth(140)
        for box in (self.concurrency, self.min_free):
            box.lineEdit().setTextMargins(8, 0, 0, 0)  # the style sheet padding does not reach the inner field
        self.restore_deleted = QCheckBox(UI.RESTORE_DELETED)
        self.restore_deleted.setChecked(account.restore_deleted)
        download = QWidget()
        download_form = QFormLayout(download)
        download_form.addRow(UI.CONCURRENCY, self.concurrency)
        download_form.addRow(UI.MIN_FREE, self.min_free)
        download_form.addRow(self.restore_deleted)
        tabs.addTab(download, UI.TAB_DOWNLOAD)

        self.save_button = QPushButton(UI.BTN_SAVE)
        self.save_button.setDefault(True)
        self.save_button.setProperty("primary", True)
        cancel = QPushButton(UI.BTN_CANCEL)
        self.locked_note = self._note(UI.SETTINGS_LOCKED)
        self.locked_note.setVisible(controller.is_job_running)
        self.save_button.setEnabled(not controller.is_job_running)
        buttons = QHBoxLayout()
        buttons.addWidget(self.locked_note, 1)
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(buttons)
        self.save_button.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        self._refresh_shared_warning()

    @staticmethod
    def _note(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setProperty("role", "muted")
        return label

    def _choose_root(self) -> None:
        if choose_root(self, self.controller):
            account = self.controller.active()
            self.root_label.setText(account.root_dir if account else UI.ROOT_EMPTY)
            self._refresh_shared_warning()

    def _refresh_shared_warning(self) -> None:
        others = self.controller.shared_root_accounts()
        self.shared_warning.setText(UI.SHARED_ROOT_WARNING.format(others=", ".join(others)) if others else "")
        self.shared_warning.setVisible(bool(others))

    def _fill_albums(self, names: list[str], checked: set[str]) -> None:
        self.albums.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if name in checked else Qt.CheckState.Unchecked)
            self.albums.addItem(item)

    def _checked_albums(self) -> list[str]:
        return [
            self.albums.item(row).text()
            for row in range(self.albums.count())
            if self.albums.item(row).checkState() == Qt.CheckState.Checked
        ]

    def _sync_album_widgets(self) -> None:
        enabled = self.source_albums.isChecked()
        self.albums.setEnabled(enabled)
        self.load_albums.setEnabled(enabled)

    def _load_albums(self) -> None:
        self.albums_status.setText(UI.ALBUMS_LOADING)
        self.load_albums.setEnabled(False)
        self.controller.load_albums()

    def _on_albums(self, albums: object, error: str) -> None:
        self.load_albums.setEnabled(self.source_albums.isChecked())
        if albums is None:
            self.albums_status.setText(UI.ALBUMS_FAILED.format(message=error))
            return
        self.albums_status.setText("")
        checked = set(self._checked_albums())
        self._fill_albums([album.name for album in albums], checked)  # type: ignore[attr-defined]

    def _save(self) -> None:
        albums = self._checked_albums() if self.source_albums.isChecked() else []
        self.controller.update_active(
            photos=self.photos.isChecked(),
            videos=self.videos.isChecked(),
            live_video=self.live_video.isChecked(),
            edited=self.edited.isChecked(),
            albums=albums or None,
            compact_enabled=self.compact_enabled.isChecked(),
            compact_long_side=self.compact_size.currentData(),
            compact_quality=self.quality.value(),
            concurrency=self.concurrency.value(),
            min_free_gb=self.min_free.value(),
            restore_deleted=self.restore_deleted.isChecked(),
        )
        self.accept()

    def done(self, result: int) -> None:
        try:
            self.controller.albums_loaded.disconnect(self._on_albums)
        except (RuntimeError, TypeError):
            pass
        super().done(result)


# --------------------------------------------------------------------------

_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
_LEVEL_IN_LINE = re.compile(r"^\S+ \S+ (DEBUG|INFO|WARNING|ERROR|CRITICAL)\b")
MAX_LOG_LINES = 2000


def read_log_tail(path: Path, minimum: str = "DEBUG", limit: int = MAX_LOG_LINES) -> list[str]:
    """Last `limit` records of the log at or above a level. A traceback stays
    with the record it belongs to."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()[-limit * 4 :]
    except OSError:
        return []
    threshold = _LEVELS.index(minimum)
    result: list[str] = []
    keep = True
    for line in lines:
        match = _LEVEL_IN_LINE.match(line)
        if match:
            keep = _LEVELS.index(match.group(1)) >= threshold
        if keep:
            result.append(line)
    return result[-limit:]


class LogDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(UI.LOG_TITLE)
        self.resize(900, 520)
        self.level = QComboBox()
        for label, level in zip(UI.LOG_LEVELS, ("DEBUG", "INFO", "WARNING", "ERROR")):
            self.level.addItem(label, level)
        self.level.setCurrentIndex(1)
        refresh = QPushButton(UI.BTN_REFRESH)
        open_logs = QPushButton(UI.BTN_OPEN_LOGS)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        top = QHBoxLayout()
        top.addWidget(QLabel(UI.LOG_LEVEL))
        top.addWidget(self.level)
        top.addWidget(refresh)
        top.addStretch(1)
        top.addWidget(open_logs)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.text)
        self.level.currentIndexChanged.connect(lambda _index: self.refresh())
        refresh.clicked.connect(self.refresh)
        open_logs.clicked.connect(lambda: open_folder(config.log_dir()))
        self.refresh()

    def refresh(self) -> None:
        lines = read_log_tail(config.log_dir() / "app.log", self.level.currentData())
        self.text.setPlainText("\n".join(lines))
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())


class ProblemsDialog(QDialog):
    def __init__(self, rows: list[tuple[str, str, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(UI.ERRORS_TITLE)
        self.resize(820, 420)
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(list(UI.ERRORS_COLUMNS))
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        for row, values in enumerate(rows):
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(value))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        close = QPushButton(UI.BTN_CLOSE)
        close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(close, alignment=Qt.AlignmentFlag.AlignRight)
