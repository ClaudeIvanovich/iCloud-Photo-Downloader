"""Sign-in: Apple ID and password, then the 6-digit code (device or SMS)."""

from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..icloud_adapter import LoginStatus, TrustedPhone
from ..strings import UI
from .controller import Controller, LoginOutcome


class LoginDialog(QDialog):
    def __init__(self, controller: Controller, apple_id: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._sms_phone: TrustedPhone | None = None
        self._phones: tuple[TrustedPhone, ...] = ()
        self.setWindowTitle(UI.LOGIN_TITLE)
        self.setMinimumWidth(440)

        # page 1: credentials
        self.apple_id = QLineEdit(apple_id)
        self.apple_id.setPlaceholderText("name@example.com")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_button = QPushButton(UI.BTN_LOGIN)
        self.login_button.setDefault(True)
        cancel = QPushButton(UI.BTN_CANCEL)
        form = QFormLayout()
        form.addRow(UI.APPLE_ID, self.apple_id)
        form.addRow(UI.PASSWORD, self.password)
        note = QLabel(UI.REQUIREMENTS_NOTE)
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.login_button)
        buttons.addWidget(cancel)
        credentials = QWidget()
        layout = QVBoxLayout(credentials)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addStretch(1)
        layout.addLayout(buttons)

        # page 2: code
        self.code_prompt = QLabel(UI.CODE_PROMPT)
        self.code_prompt.setWordWrap(True)
        self.code = QLineEdit()
        self.code.setMaxLength(6)
        self.code.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,6}")))
        self.code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.code.font()
        font.setPointSize(font.pointSize() + 6)
        font.setLetterSpacing(font.SpacingType.AbsoluteSpacing, 6)
        self.code.setFont(font)
        self.confirm_button = QPushButton(UI.BTN_CONFIRM)
        self.sms_button = QPushButton()
        code_cancel = QPushButton(UI.BTN_CANCEL)
        code_form = QFormLayout()
        code_form.addRow(UI.CODE_FIELD, self.code)
        code_buttons = QHBoxLayout()
        code_buttons.addWidget(self.sms_button)
        code_buttons.addStretch(1)
        code_buttons.addWidget(self.confirm_button)
        code_buttons.addWidget(code_cancel)
        code_page = QWidget()
        code_layout = QVBoxLayout(code_page)
        code_layout.addWidget(self.code_prompt)
        code_layout.addLayout(code_form)
        code_layout.addStretch(1)
        code_layout.addLayout(code_buttons)

        self.pages = QStackedWidget()
        self.pages.addWidget(credentials)
        self.pages.addWidget(code_page)
        self.message = QLabel()
        self.message.setWordWrap(True)
        outer = QVBoxLayout(self)
        outer.addWidget(self.pages)
        outer.addWidget(self.message)

        self.login_button.clicked.connect(self._login)
        self.password.returnPressed.connect(self._login)
        self.confirm_button.clicked.connect(self._confirm)
        self.code.returnPressed.connect(self._confirm)
        self.sms_button.clicked.connect(self._send_sms)
        cancel.clicked.connect(self.reject)
        code_cancel.clicked.connect(self.reject)
        controller.login_finished.connect(self._on_outcome)
        self.finished.connect(self._on_closed)

        if apple_id:
            self.apple_id.setReadOnly(True)
            self.password.setFocus()

    def start_with_saved_password(self) -> None:
        """Re-login of a known account: skip the password page if we have it."""
        if self.controller.has_saved_password(self.apple_id.text()):
            self._busy(UI.LOGIN_WAIT)
            self.controller.begin_login(self.apple_id.text(), None)

    # ------------------------------------------------------------ actions

    def _busy(self, text: str) -> None:
        self._show_message(text, error=False)
        for widget in (self.login_button, self.confirm_button, self.sms_button):
            widget.setEnabled(False)

    def _ready(self) -> None:
        for widget in (self.login_button, self.confirm_button):
            widget.setEnabled(True)
        self.sms_button.setEnabled(bool(self._phones))

    def _show_message(self, text: str, error: bool) -> None:
        self.message.setText(text)
        self.message.setStyleSheet("color: #C8443C;" if error else "")

    def _login(self) -> None:
        if not self.apple_id.text().strip() or not self.password.text():
            self._show_message(UI.LOGIN_NEED_FIELDS, error=True)
            return
        self._busy(UI.LOGIN_WAIT)
        self.controller.begin_login(self.apple_id.text(), self.password.text())

    def _confirm(self) -> None:
        code = self.code.text()
        if len(code) != 6:
            self._show_message(UI.CODE_NEED_6, error=True)
            return
        self._busy(UI.CODE_WAIT)
        if self._sms_phone is not None:
            self.controller.submit_sms_code(self._sms_phone.id, code)
        else:
            self.controller.submit_code(code)

    def _send_sms(self) -> None:
        if not self._phones:
            return
        self._sms_phone = self._phones[0]
        self.controller.request_sms(self._sms_phone.id)
        self.code_prompt.setText(UI.SMS_SENT.format(number=self._sms_phone.masked_number))
        self.code.clear()
        self.code.setFocus()

    def _on_outcome(self, outcome: LoginOutcome) -> None:
        if outcome.status is LoginStatus.OK:
            self.password.clear()
            self.accept()
            return
        if outcome.status is LoginStatus.NEEDS_2FA:
            self._phones = outcome.phones
            self.sms_button.setVisible(bool(self._phones))
            if self._phones:
                self.sms_button.setText(UI.BTN_SEND_SMS.format(number=self._phones[0].masked_number))
            self.pages.setCurrentIndex(1)
            self._show_message("", error=False)
            self._ready()
            self.code.setFocus()
            return
        self._ready()
        self._show_message(outcome.message, error=True)
        if self.pages.currentIndex() == 1:
            self.code.clear()
            self.code.setFocus()

    def _on_closed(self, _result: int) -> None:
        self.password.clear()
        self.code.clear()
        try:
            self.controller.login_finished.disconnect(self._on_outcome)
        except (RuntimeError, TypeError):
            pass
        if self.result() != QDialog.DialogCode.Accepted:
            self.controller.cancel_login()
