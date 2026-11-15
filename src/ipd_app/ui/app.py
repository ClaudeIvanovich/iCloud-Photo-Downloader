"""GUI entry point: single instance, global error handler, main window."""

from __future__ import annotations

import getpass
import hashlib
import logging
import os
import sys
import tempfile
import threading
import traceback

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import __version__
from ..accounts import MemoryPasswordBackend, PasswordStore
from ..logging_setup import setup_logging
from ..strings import UI
from . import icons
from .controller import Controller
from .main_window import MainWindow

log = logging.getLogger("ipd_app.ui")


def instance_name() -> str:
    """One instance per Windows user (and per data folder, for the demo mode)."""
    seed = f"{getpass.getuser()}|{os.environ.get('IPD_APPDATA', '')}"
    return "iCloudPhotoDownloader-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


class SingleInstance(QObject):
    """The first instance listens; a second one asks it to show its window and exits."""

    raise_requested = Signal()

    def __init__(self, name: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.name = name
        self.server: QLocalServer | None = None

    def notify_running(self, timeout_ms: int = 500) -> bool:
        """True when another instance is already running (and has been told to show up)."""
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(timeout_ms):
            return False
        socket.write(b"show\n")
        socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return True

    def listen(self) -> bool:
        QLocalServer.removeServer(self.name)  # a stale name left by a crash
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._on_connection)
        return self.server.listen(self.name)

    def _on_connection(self) -> None:
        assert self.server is not None
        # The connection itself is the message: someone started a second copy.
        while self.server.hasPendingConnections():
            connection = self.server.nextPendingConnection()
            connection.disconnected.connect(connection.deleteLater)
            self.raise_requested.emit()


class ErrorReporter(QObject):
    """Shows an unhandled exception from any thread in the UI thread."""

    reported = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.reported.connect(self._show)
        self._open = False

    def install(self) -> None:
        def hook(exc_type, exc, trace) -> None:
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc, trace)
                return
            log.critical("Unhandled exception", exc_info=(exc_type, exc, trace))
            self.reported.emit("".join(traceback.format_exception_only(exc_type, exc)).strip())

        sys.excepthook = hook
        threading.excepthook = lambda args: hook(args.exc_type, args.exc_value, args.exc_traceback)

    def _show(self, detail: str) -> None:
        if self._open:  # one dialog at a time, even for a burst of errors
            return
        self._open = True
        try:
            QMessageBox.critical(None, UI.UNHANDLED_TITLE, UI.UNHANDLED_TEXT.format(detail=detail[:500]))
        finally:
            self._open = False


def build_controller(fake: int | None) -> Controller:
    if fake is None:
        return Controller()
    from ..icloud_adapter.fake_client import demo_library

    library = demo_library(fake)
    library.session_valid = False  # the demo starts signed out: any Apple ID, password "secret"
    return Controller(client_factory=lambda apple_id: library, passwords=PasswordStore(MemoryPasswordBackend()))


def run_gui(fake: int | None = None, start_hidden: bool = False) -> int:
    if fake is not None:
        # Keep the demo away from the real settings, sessions and state.
        os.environ["IPD_APPDATA"] = os.path.join(tempfile.gettempdir(), "iCloudPhotoDownloader-demo")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(UI.APP_TITLE)
    app.setApplicationVersion(__version__)
    app.setWindowIcon(icons.icon("idle"))
    app.setQuitOnLastWindowClosed(False)

    single = SingleInstance(instance_name())
    if single.notify_running():
        return 0
    single.listen()

    setup_logging()
    reporter = ErrorReporter()
    reporter.install()
    log.info("Starting %s %s", UI.APP_TITLE, __version__)

    controller = build_controller(fake)
    window = MainWindow(controller)
    single.raise_requested.connect(window.show_from_tray)
    if not (start_hidden and window.tray is not None):
        window.show()
    if controller.active() is None:
        window.sign_in()
    else:
        controller.check_session()
    code = app.exec()
    # Tear down in a fixed order in the UI thread; left to interpreter shutdown,
    # Qt objects can be destroyed after the application object.
    controller.shutdown()
    window.timer.stop()
    if window.tray is not None:
        window.tray.hide()
    window.deleteLater()
    controller.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    return code
