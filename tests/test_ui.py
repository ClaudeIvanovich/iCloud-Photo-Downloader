"""GUI on the offscreen Qt platform: controller flows and window behaviour."""

from __future__ import annotations

import gc
import os
import time
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from conftest import tree, utc
from ipd_app import config, strings
from ipd_app.accounts import MemoryPasswordBackend, PasswordStore
from ipd_app.icloud_adapter import ICloudError, LoginStatus
from ipd_app.icloud_adapter.fake_client import FakeICloudClient
from ipd_app.strings import UI
from ipd_app.sync_engine import Period
from ipd_app.ui import controller as ctl
from ipd_app.ui.app import SingleInstance
from ipd_app.ui.controller import Controller
from ipd_app.ui.dialogs import AccountsDialog, LogDialog, ProblemsDialog, SettingsDialog, read_log_tail
from ipd_app.ui.login_dialog import LoginDialog
from ipd_app.ui.main_window import MainWindow, format_eta

APPLE_ID = "alex@example.com"
YEAR_2023 = Period(date(2023, 1, 1), date(2023, 12, 31))


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def tidy_qt_objects(qapp):
    """Destroy leftover dialogs in the main thread after every test, instead of
    leaving them to the garbage collector or to interpreter shutdown."""
    yield
    for widget in QApplication.topLevelWidgets():
        widget.hide()
        widget.deleteLater()
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QCoreApplication.processEvents()


def wait_for(predicate, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for the UI")
    QCoreApplication.processEvents()


@pytest.fixture
def fake() -> FakeICloudClient:
    return FakeICloudClient(password="pw", two_factor_code="123456")


@pytest.fixture
def controller(qapp, tmp_path, monkeypatch, fake):
    monkeypatch.setenv("IPD_APPDATA", str(tmp_path / "appdata"))
    backend = MemoryPasswordBackend()
    made = Controller(client_factory=lambda apple_id: fake, passwords=PasswordStore(backend))
    made.backend = backend  # type: ignore[attr-defined]
    yield made
    made.shutdown()
    # Destroy the Qt objects here, in the main thread. Left to the garbage
    # collector, they could be destroyed from a worker thread of a later test.
    made.deleteLater()
    del made
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


def sign_in(controller: Controller, apple_id: str = APPLE_ID) -> None:
    outcomes = []
    controller.login_finished.connect(outcomes.append)
    controller.begin_login(apple_id, "pw")
    wait_for(lambda: outcomes)
    assert outcomes[-1].status is LoginStatus.NEEDS_2FA
    controller.submit_code("123456")
    wait_for(lambda: len(outcomes) == 2)
    assert outcomes[-1].status is LoginStatus.OK
    controller.login_finished.disconnect(outcomes.append)


def ready(controller: Controller, root) -> None:
    sign_in(controller)
    controller.update_active(root_dir=str(root), compact_enabled=False)


# ------------------------------------------------------------- controller


def test_login_with_2fa_saves_password_and_account(controller, tmp_path) -> None:
    outcomes = []
    controller.login_finished.connect(outcomes.append)
    controller.begin_login(APPLE_ID, "wrong")
    wait_for(lambda: outcomes)
    assert outcomes[0].status is LoginStatus.FAILED and outcomes[0].message == strings.ERR_BAD_CREDENTIALS
    assert controller.accounts() == []

    controller.begin_login(APPLE_ID, "pw")
    wait_for(lambda: len(outcomes) == 2)
    assert outcomes[1].status is LoginStatus.NEEDS_2FA and outcomes[1].phones
    controller.submit_code("000000")
    wait_for(lambda: len(outcomes) == 3)
    assert outcomes[2].message == strings.ERR_BAD_2FA_CODE
    controller.submit_code("123456")
    wait_for(lambda: len(outcomes) == 4)
    assert outcomes[3].status is LoginStatus.OK

    assert controller.active().apple_id == APPLE_ID
    assert controller.session_state()[0] == ctl.SESSION_OK
    assert controller.has_saved_password(APPLE_ID)
    saved = (tmp_path / "appdata" / "config.json").read_text(encoding="utf-8")
    assert APPLE_ID in saved and "pw" not in saved.replace(APPLE_ID, "")


def test_saved_session_is_checked_without_prompts(controller, fake) -> None:
    sign_in(controller)
    states = []
    controller.session_changed.connect(lambda state, message: states.append(state))
    controller.check_session()
    wait_for(lambda: states and states[-1] != ctl.SESSION_CHECKING)
    assert states == [ctl.SESSION_CHECKING, ctl.SESSION_OK]
    fake.session_valid = False
    controller.check_session()
    wait_for(lambda: states[-1] == ctl.SESSION_EXPIRED)


def test_job_cannot_start_without_folder_or_session(controller, tmp_path) -> None:
    assert controller.can_start() == UI.HINT_NO_ACCOUNT
    sign_in(controller)
    assert controller.can_start() == UI.HINT_NO_ROOT and controller.start_job(YEAR_2023) is False
    controller.update_active(root_dir=str(tmp_path / "photos"))
    assert controller.can_start() == ""
    controller.sign_out(APPLE_ID)
    assert controller.can_start() == UI.HINT_NO_SESSION


def test_job_runs_in_background_and_reports(controller, fake, tmp_path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    for index in range(6):
        fake.add(f"IMG_{index}.JPG", bytes([index]) * 2000, taken=utc(2023, 5, index + 1))
    ready(controller, root)
    states, plans, finished, notes = [], [], [], []
    controller.job_state.connect(states.append)
    controller.job_plan.connect(plans.append)
    controller.job_finished.connect(lambda report, error: finished.append((report, error)))
    controller.notify.connect(lambda title, text, kind: notes.append((title, kind)))

    assert controller.start_job(YEAR_2023) is True
    assert controller.is_job_running and controller.start_job(YEAR_2023) is False
    wait_for(lambda: finished)

    report, error = finished[0]
    assert error == "" and report.downloaded == 6 and not controller.is_job_running
    assert len(tree(root)) == 6
    assert states[0] == "counting" and "downloading" in states and states[-1] == "idle"
    assert plans[0].files_to_download == 6
    assert controller.progress.snapshot()[:4] == (6, 6, 12000, 12000)
    assert notes == [(UI.NOTE_DONE_TITLE, "info")]
    assert controller.unfinished_job() is None


def test_switching_account_is_refused_while_a_job_runs(controller, fake, tmp_path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    for index in range(30):
        fake.add(f"IMG_{index}.JPG", b"x" * 50_000, taken=utc(2023, 5, 1 + index % 28))
    ready(controller, root)
    sign_in(controller, "second@example.com")
    assert controller.active().apple_id == "second@example.com"  # a freshly added account becomes active
    assert controller.set_active(APPLE_ID) is True
    wait_for(lambda: controller.session_state()[0] == ctl.SESSION_OK)  # re-checked after the switch
    finished = []
    controller.job_finished.connect(lambda report, error: finished.append(report))
    assert controller.start_job(YEAR_2023) is True
    controller.pause_job()
    assert controller.set_active("second@example.com") is False
    assert controller.sign_out(APPLE_ID) is False and controller.remove_account(APPLE_ID) is False
    controller.stop_job()
    wait_for(lambda: finished)
    assert finished[0].stopped_reason == strings.STOP_USER
    assert controller.unfinished_job() is not None
    assert controller.set_active("second@example.com") is True


def test_expired_session_during_a_job_asks_for_relogin(controller, fake, tmp_path) -> None:
    from ipd_app.icloud_adapter import SessionExpiredError

    root = tmp_path / "photos"
    root.mkdir()
    doomed = fake.add("IMG_1.JPG", b"data", taken=utc(2023, 5, 1))
    fake.fail(doomed, SessionExpiredError())
    ready(controller, root)
    notes, finished = [], []
    controller.notify.connect(lambda title, text, kind: notes.append(kind))
    controller.job_finished.connect(lambda report, error: finished.append(report))
    controller.start_job(YEAR_2023)
    wait_for(lambda: finished)
    assert notes == ["relogin"] and controller.session_state()[0] == ctl.SESSION_EXPIRED
    assert controller.job_state_name == "error"


def test_preflight_failure_is_reported_not_raised(controller, tmp_path) -> None:
    sign_in(controller)
    controller.update_active(root_dir=str(tmp_path / "does-not-exist"))
    finished, notes = [], []
    controller.job_finished.connect(lambda report, error: finished.append(error))
    controller.notify.connect(lambda title, text, kind: notes.append(kind))
    controller.start_job(YEAR_2023)
    wait_for(lambda: finished)
    assert "недоступна" in finished[0] and notes == ["error"] and not controller.is_job_running


def test_sign_out_and_remove_account_keep_downloaded_files(controller, fake, tmp_path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    fake.add("IMG_1.JPG", b"data", taken=utc(2023, 5, 1))
    ready(controller, root)
    session_folder = config.session_dir(APPLE_ID)
    session_folder.mkdir(parents=True)
    (session_folder / "alexexamplecom.session").write_text("{}")
    finished = []
    controller.job_finished.connect(lambda report, error: finished.append(report))
    controller.start_job(YEAR_2023)
    wait_for(lambda: finished)
    files = tree(root)

    assert controller.remove_account(APPLE_ID) is True
    assert controller.accounts() == [] and controller.active() is None
    assert not controller.has_saved_password(APPLE_ID) and not session_folder.exists()
    assert tree(root) == files  # photos stay
    assert config.state_db_path(APPLE_ID).exists()  # so a re-added account does not start over


def test_two_accounts_on_one_folder_are_reported(controller, tmp_path) -> None:
    sign_in(controller)
    controller.update_active(root_dir=str(tmp_path / "photos"))
    sign_in(controller, "second@example.com")
    controller.set_active("second@example.com")
    controller.update_active(root_dir=str(tmp_path / "photos"))
    assert controller.shared_root_accounts() == [APPLE_ID]


# ---------------------------------------------------------------- windows


@pytest.fixture
def window(controller):
    made = MainWindow(controller, use_tray=False)
    yield made
    made.timer.stop()
    made._quitting = True
    made.close()  # while its controller is still alive
    made.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_main_window_guides_the_user_to_a_startable_state(window, controller, tmp_path) -> None:
    assert not window.start_button.isEnabled() and window.hint.text() == UI.HINT_NO_ACCOUNT
    assert not window.sign_in_button.isHidden()
    sign_in(controller)
    assert window.account_combo.currentText() == APPLE_ID
    assert window.session_label.text() == UI.SESSION_OK and window.sign_in_button.isHidden()
    assert window.hint.text() == UI.HINT_NO_ROOT and not window.start_button.isEnabled()
    controller.update_active(root_dir=str(tmp_path))
    assert window.start_button.isEnabled() and window.hint.text() == ""


def test_period_validation_and_presets(window, controller, tmp_path) -> None:
    sign_in(controller)
    controller.update_active(root_dir=str(tmp_path))
    window.set_period(date(2023, 6, 1), date(2023, 5, 1))
    assert window.period() is None
    assert not window.start_button.isEnabled() and window.hint.text() == UI.HINT_BAD_PERIOD
    window.set_period(date(2022, 1, 1), date(2023, 12, 31))
    assert window.period() == Period(date(2022, 1, 1), date(2023, 12, 31)) and window.start_button.isEnabled()

    today = date.today()
    window.preset_last_year.click()
    assert window.period() == Period(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
    window.preset_30_days.click()
    assert window.period() == Period(today - timedelta(days=30), today)
    window.all_time.setChecked(True)
    assert window.period() == Period() and not window.date_from.isEnabled()


def test_window_runs_a_job_and_shows_the_result(window, controller, fake, tmp_path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    bad = fake.add("BAD.JPG", b"0123456789", taken=utc(2023, 5, 1))
    fake.fail(bad, ICloudError("gone"))  # a permanent error: reported at once, no retries
    for index in range(4):
        fake.add(f"IMG_{index}.JPG", b"y" * 3000, taken=utc(2023, 6, index + 1))
    ready(controller, root)
    window.set_period(date(2023, 1, 1), date(2023, 12, 31))
    assert not window.errors_button.isEnabled()
    window.start_button.click()
    assert controller.is_job_running
    assert not window.start_button.isEnabled() and window.stop_button.isEnabled()
    assert not window.account_combo.isEnabled() and not window.date_from.isEnabled()
    wait_for(lambda: not controller.is_job_running)
    window._tick()

    assert "Скачано: 4" in window.last_label.text() and "Ошибок: 1" in window.last_label.text()
    assert "К загрузке: 5" in window.plan_label.text()
    assert window.files_label.text() == UI.PROGRESS_FILES.format(done=4, total=5)
    assert window.start_button.isEnabled() and not window.stop_button.isEnabled()
    assert window.errors_button.isEnabled()
    problems = ProblemsDialog(controller.problems())
    assert problems.table.rowCount() == 1 and "BAD.JPG" in problems.table.item(0, 0).text()
    assert problems.table.item(0, 1).text() == UI.KIND_ERROR


def test_pause_button_toggles(window, controller, fake, tmp_path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    for index in range(40):
        fake.add(f"IMG_{index}.JPG", b"z" * 100_000, taken=utc(2023, 5, 1 + index % 28))
    ready(controller, root)
    controller.update_active(concurrency=1)
    window.set_period(date(2023, 1, 1), date(2023, 12, 31))
    window.start_button.click()
    wait_for(lambda: controller.job_state_name == "downloading")
    window.pause_button.click()
    wait_for(lambda: controller.job_state_name == "paused")
    assert window.pause_button.text() == UI.BTN_RESUME
    assert strings.STATUS_PAUSED in window.status_label.text()
    window.pause_button.click()
    wait_for(lambda: controller.job_state_name == "downloading")
    window.stop_button.click()
    wait_for(lambda: not controller.is_job_running)
    assert "Остановлено" in window.last_label.text()


def test_close_hides_to_tray_and_exit_goes_through_the_menu(window, controller, fake, tmp_path) -> None:
    from ipd_app.ui.main_window import Tray

    root = tmp_path / "photos"
    root.mkdir()
    for index in range(40):
        fake.add(f"IMG_{index}.JPG", b"z" * 100_000, taken=utc(2023, 5, 1 + index % 28))
    ready(controller, root)
    controller.update_active(concurrency=1)
    window.tray = Tray(window)  # the offscreen platform has no system tray, the object still works
    announced = []
    window.tray.announce = lambda title, text, kind: announced.append((title, kind))
    window.show()

    window.set_period(date(2023, 1, 1), date(2023, 12, 31))
    window.start_button.click()
    wait_for(lambda: controller.job_state_name == "downloading")
    window.close()  # the cross: hide, keep working
    assert not window.isVisible() and controller.is_job_running
    assert announced == [(UI.APP_TITLE, "info")]
    window._tick()
    assert window.tray.pause_action.isEnabled() and window.tray.stop_action.isEnabled()
    assert "загрузка" in window.tray.toolTip()

    window.tray.pause_action.trigger()
    wait_for(lambda: controller.job_state_name == "paused")
    window._tick()
    assert window.tray.pause_action.text() == UI.BTN_RESUME
    window.tray.open_action.trigger()
    assert window.isVisible()
    window.tray.stop_action.trigger()
    wait_for(lambda: not controller.is_job_running)
    window._tick()
    assert not window.tray.stop_action.isEnabled() and window.tray.toolTip() == UI.TRAY_TIP_IDLE
    assert announced[-1] == (UI.NOTE_STOPPED_TITLE, "info")

    window.tray.exit_action.trigger()  # no job running: exits without questions
    assert window._quitting and not window.isVisible()


def test_only_the_buttons_that_can_act_are_on_screen(window, controller, fake, tmp_path) -> None:
    root = tmp_path / "photos"
    root.mkdir()
    for index in range(40):
        fake.add(f"IMG_{index}.JPG", b"z" * 100_000, taken=utc(2023, 5, 1 + index % 28))
    ready(controller, root)
    controller.update_active(concurrency=1)
    window.set_period(date(2023, 1, 1), date(2023, 12, 31))
    assert not window.start_button.isHidden() and window.pause_button.isHidden() and window.stop_button.isHidden()
    assert window.percent_label.text() == "0%"
    window.start_button.click()
    wait_for(lambda: controller.job_state_name == "downloading")
    assert window.start_button.isHidden() and not window.pause_button.isHidden() and not window.stop_button.isHidden()
    window.stop_button.click()
    wait_for(lambda: not controller.is_job_running)
    assert not window.start_button.isHidden() and window.pause_button.isHidden()


def test_long_file_name_loses_its_middle(qapp) -> None:
    from ipd_app.ui.main_window import ElidedLabel

    label = ElidedLabel()
    label.show()  # resize events only reach a widget that is on screen
    label.resize(300, 20)
    name = "свадьба александра и ирины в городе москва.mov"
    label.setText(name)
    assert label.full_text() == name and label.text() != name
    assert label.text().startswith("св") and label.text().endswith("mov") and "…" in label.text()
    label.resize(900, 20)
    assert label.text() == name
    label.setText("IMG_1.JPG")
    assert label.text() == "IMG_1.JPG"


def test_the_chip_of_the_shown_period_is_lit(window, controller, tmp_path) -> None:
    sign_in(controller)
    controller.update_active(root_dir=str(tmp_path))
    window.preset_last_year.click()
    assert window.preset_last_year.isChecked() and not window.preset_30_days.isChecked()
    window.set_period(date(2020, 2, 3), date(2020, 4, 5))  # dates typed by hand match no chip
    assert not window.preset_last_year.isChecked() and not window.preset_30_days.isChecked()
    window.preset_30_days.click()
    assert window.preset_30_days.isChecked()
    window.all_time.setChecked(True)
    assert not window.preset_30_days.isChecked() and window.period() == Period()


@pytest.mark.parametrize("dark", [False, True])
def test_theme_dresses_the_application_in_both_schemes(dark, qapp, monkeypatch, tmp_path) -> None:
    from ipd_app.ui import theme

    monkeypatch.setenv("IPD_APPDATA", str(tmp_path))
    before = (qapp.style().objectName(), qapp.styleSheet(), qapp.palette(), qapp.font())
    try:
        assert theme.apply_theme(qapp, dark=dark) is dark
        palette = theme.DARK if dark else theme.LIGHT
        assert theme.colors() is palette and palette["accent"] in qapp.styleSheet()
        assert set(theme.LIGHT) == set(theme.DARK)
        assert (tmp_path / "theme" / f"check_{'dark' if dark else 'light'}.png").is_file()
        label = QLabel("x")
        theme.set_role(label, "danger")
        assert label.property("role") == "danger"
    finally:
        qapp.setStyleSheet(before[1])
        qapp.setStyle(before[0])
        qapp.setPalette(before[2])
        qapp.setFont(before[3])


def test_login_dialog_walks_through_code_page(controller, qapp) -> None:
    dialog = LoginDialog(controller)
    dialog._login()
    assert dialog.message.text() == UI.LOGIN_NEED_FIELDS
    dialog.apple_id.setText(APPLE_ID)
    dialog.password.setText("pw")
    dialog._login()
    wait_for(lambda: dialog.pages.currentIndex() == 1)
    assert not dialog.sms_button.isHidden() and "42" in dialog.sms_button.text()
    dialog.code.setText("12")
    dialog._confirm()
    assert dialog.message.text() == UI.CODE_NEED_6
    dialog.code.setText("999999")
    dialog._confirm()
    wait_for(lambda: dialog.message.text() == strings.ERR_BAD_2FA_CODE)
    dialog.sms_button.click()
    assert "SMS отправлено" in dialog.code_prompt.text()
    dialog.code.setText("123456")
    dialog._confirm()
    wait_for(lambda: dialog.result() == QDialog.DialogCode.Accepted)
    assert dialog.password.text() == "" and controller.active().apple_id == APPLE_ID


def test_cancelled_login_adds_nothing(controller) -> None:
    dialog = LoginDialog(controller)
    dialog.apple_id.setText(APPLE_ID)
    dialog.password.setText("pw")
    dialog._login()
    wait_for(lambda: dialog.pages.currentIndex() == 1)
    dialog.reject()
    controller.submit_code("123456")  # ignored: the attempt was cancelled
    QCoreApplication.processEvents()
    assert controller.accounts() == []


def test_settings_dialog_saves_account_settings(controller, tmp_path, fake) -> None:
    fake.albums = {"Trip": [], "Family": []}
    sign_in(controller)
    controller.update_active(root_dir=str(tmp_path))
    dialog = SettingsDialog(controller)
    dialog.compact_size.setCurrentIndex(dialog.compact_size.findData(1600))
    dialog.quality.setValue(70)
    dialog.videos.setChecked(False)
    dialog.edited.setChecked(True)
    dialog.concurrency.setValue(6)
    dialog.min_free.setValue(12.5)
    dialog.restore_deleted.setChecked(False)
    dialog.source_albums.setChecked(True)
    dialog._load_albums()
    wait_for(lambda: dialog.albums.count() == 2)
    dialog.albums.item(1).setCheckState(dialog.albums.item(1).checkState().Checked)
    dialog._save()

    account = controller.active()
    assert (account.compact_long_side, account.compact_quality) == (1600, 70)
    assert (account.videos, account.edited, account.concurrency) == (False, True, 6)
    assert account.min_free_gb == 12.5 and account.restore_deleted is False
    assert account.albums == ["Trip"]
    assert config.load_config().account(APPLE_ID).albums == ["Trip"]


def test_accounts_dialog_lists_and_switches(controller, tmp_path) -> None:
    sign_in(controller)
    sign_in(controller, "second@example.com")
    controller.set_active(APPLE_ID)
    dialog = AccountsDialog(controller)
    assert dialog.list.count() == 2 and UI.ACTIVE_MARK in dialog.list.item(0).text()
    dialog.list.setCurrentRow(1)
    assert dialog.switch_button.isEnabled()
    dialog._switch()
    assert controller.active().apple_id == "second@example.com"
    assert UI.ACTIVE_MARK in dialog.list.item(1).text()


def test_log_tail_filters_by_level(tmp_path, monkeypatch, qapp) -> None:
    monkeypatch.setenv("IPD_APPDATA", str(tmp_path))
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app.log").write_text(
        "2026-11-15 10:00:00,000 INFO    a: started\n"
        "2026-11-15 10:00:01,000 WARNING b: slow\n"
        "2026-11-15 10:00:02,000 ERROR   c: failed\nTraceback (most recent call last):\n  boom\n"
        "2026-11-15 10:00:03,000 INFO    a: done\n",
        encoding="utf-8",
    )
    assert len(read_log_tail(logs / "app.log", "DEBUG")) == 6
    errors = read_log_tail(logs / "app.log", "ERROR")
    assert errors == ["2026-11-15 10:00:02,000 ERROR   c: failed", "Traceback (most recent call last):", "  boom"]
    dialog = LogDialog()
    dialog.level.setCurrentIndex(2)
    assert "slow" in dialog.text.toPlainText() and "started" not in dialog.text.toPlainText()


def test_second_instance_wakes_the_first(qapp) -> None:
    first = SingleInstance("ipd-test-instance")
    assert first.notify_running(100) is False
    assert first.listen() is True
    raised = []
    first.raise_requested.connect(lambda: raised.append(True))
    second = SingleInstance("ipd-test-instance")
    assert second.notify_running() is True
    wait_for(lambda: raised)
    first.server.close()


def test_eta_format() -> None:
    assert format_eta(42) == "42 с" and format_eta(125) == "2 мин 5 с" and format_eta(3725) == "1 ч 2 мин"


# ---------------------------------------------------------------- languages

def visible_texts(widget) -> list[str]:
    """Every text a widget tree shows: labels, buttons, titles, tabs, list and table items."""
    from PySide6.QtWidgets import QComboBox, QGroupBox, QTableWidget, QTabWidget, QWidget

    found = [widget.windowTitle()]
    for child in [widget, *widget.findChildren(QWidget)]:
        if child.objectName() == "language_combo":
            continue  # lists every language under its own name
        for getter in ("text", "title", "toolTip", "placeholderText", "suffix"):
            value = getattr(child, getter, None)
            if callable(value):
                try:
                    found.append(str(value()))
                except TypeError:
                    pass
        if isinstance(child, QGroupBox):
            found.append(child.title())
        if isinstance(child, QTabWidget):
            found += [child.tabText(index) for index in range(child.count())]
        if isinstance(child, QComboBox):
            found += [child.itemText(index) for index in range(child.count())]
        if isinstance(child, QTableWidget):
            found += [child.horizontalHeaderItem(index).text() for index in range(child.columnCount())]
            found += [
                child.item(row, 1).text() for row in range(child.rowCount()) if child.item(row, 1) is not None
            ]
    return [text for text in found if text]


@pytest.mark.parametrize("code", ["en", "es", "pt_BR", "zh_CN", "ja"])
def test_no_russian_text_is_left_in_any_window(code, controller, fake, tmp_path, qapp) -> None:
    import re

    from ipd_app.ui.app import apply_language

    assert apply_language(qapp, code) == code
    try:
        made = MainWindow(controller, use_tray=False)
        root = tmp_path / "photos"
        root.mkdir()
        bad = fake.add("BAD.JPG", b"0123456789", taken=utc(2023, 5, 1))
        fake.fail(bad, ICloudError("gone"))
        fake.add("IMG_1.JPG", b"y" * 3000, taken=utc(2023, 6, 1))
        ready(controller, root)
        made.set_period(date(2023, 1, 1), date(2023, 12, 31))
        made.start_button.click()
        wait_for(lambda: not controller.is_job_running)
        made._tick()
        windows = [
            made,
            LoginDialog(controller, parent=made),
            SettingsDialog(controller, made),
            AccountsDialog(controller, made),
            ProblemsDialog(controller.problems(), made),
            LogDialog(made),
        ]
        texts = [text for window in windows for text in visible_texts(window)]
        assert len(texts) > 80
        russian = [text for text in texts if re.search("[А-Яа-яЁё]", text)]
        assert not russian, russian
        made.timer.stop()
        made._quitting = True
        made.close()
    finally:
        apply_language(qapp, "ru")


def test_choosing_a_language_is_saved_for_the_next_start(window, controller, monkeypatch) -> None:
    told = []
    monkeypatch.setattr("ipd_app.ui.main_window.QMessageBox.information", lambda *args: told.append(args[-1]))
    assert window.language_combo.currentData() == strings.AUTO
    index = window.language_combo.findData("es")
    window.language_combo.setCurrentIndex(index)
    window._language_chosen(index)
    assert config.load_config().language == "es"
    assert told == [UI.LANGUAGE_RESTART]  # the running window stays in the old language
    assert [window.language_combo.itemText(i) for i in range(1, window.language_combo.count())] == list(strings.LANGUAGES.values())
