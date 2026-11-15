"""State database, config, logging, password store and the CLI."""

from __future__ import annotations

import json
import logging
from datetime import datetime

import pytest

from conftest import tree
from ipd_app import cli, config
from ipd_app.accounts import SERVICE_NAME, PasswordStore
from ipd_app.icloud_adapter import VersionKind
from ipd_app.logging_setup import SecretFilter, mask_apple_id, scrub, secret_filter, setup_logging
from ipd_app.sync_engine import Capture, StateDB
from ipd_app.sync_engine import state_db as sdb


@pytest.fixture
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("IPD_APPDATA", str(tmp_path / "appdata"))
    return tmp_path / "appdata"


# ----------------------------------------------------------------- state db


def test_file_rows_and_case_insensitive_claims(tmp_path) -> None:
    db = StateDB(tmp_path / "s.sqlite")
    row = db.add_file("A1", VersionKind.ORIGINAL, "2023/03 March/Full size/IMG_1.HEIC", 10, "2023/03 March/Compact/IMG_1.jpg")
    assert (row.status, row.compact_status) == (sdb.STATUS_PLANNED, sdb.COMPACT_PENDING)
    assert db.path_owner("2023/03 march/full size/img_1.heic") == ("A1", VersionKind.ORIGINAL)
    assert db.compact_owner("2023/03 March/Compact/IMG_1.JPG") == ("A1", VersionKind.ORIGINAL)
    assert db.path_owner("2023/03 March/Full size/IMG_2.HEIC") is None
    with pytest.raises(Exception):
        db.add_file("A2", VersionKind.ORIGINAL, "2023/03 MARCH/Full size/IMG_1.heic", 10, None)
    db.set_status("A1", VersionKind.ORIGINAL, sdb.STATUS_DONE)
    db.set_compact_status("A1", VersionKind.ORIGINAL, sdb.COMPACT_ERROR, "boom")
    assert db.files_for("A1")[VersionKind.ORIGINAL].status == sdb.STATUS_DONE
    assert db.count_files(sdb.STATUS_DONE) == 1
    assert db.problems() == [("2023/03 March/Compact/IMG_1.jpg", "compact_error", "boom")]
    db.close()


def test_state_survives_reopening(tmp_path) -> None:
    db = StateDB(tmp_path / "s.sqlite")
    db.add_file("A1", VersionKind.LIVE_VIDEO, "2023/03 March/Full size/IMG_1.MOV", 10, None)
    db.set_capture("A1", Capture(datetime(2023, 3, 5, 14, 30), "file"))
    db.close()
    again = StateDB(tmp_path / "s.sqlite")
    assert again.files_for("A1")[VersionKind.LIVE_VIDEO].compact_status == sdb.COMPACT_NONE
    assert again.get_capture("A1") == Capture(datetime(2023, 3, 5, 14, 30), "file")
    assert again.get_capture("nope") is None
    again.close()


def test_one_unfinished_job_at_a_time(tmp_path) -> None:
    db = StateDB(tmp_path / "s.sqlite")
    assert db.unfinished_job() is None
    first = db.start_job("2022-01-01", "2023-12-31", {"albums": None})
    db.update_job(first, total_files=9800, done_files=4120)
    db.close_job(first, finished=False)
    pending = db.unfinished_job()
    assert (pending.id, pending.total_files, pending.done_files, pending.status) == (first, 9800, 4120, sdb.JOB_STOPPED)
    assert db.start_job("2022-01-01", "2023-12-31", {"albums": None}) == first  # resumed
    other = db.start_job("2024-01-01", "2024-12-31", {"albums": None})  # replaces it
    assert other != first and db.unfinished_job().id == other
    db.close_job(other, finished=True)
    assert db.unfinished_job() is None
    db.close()


# ------------------------------------------------------------------- config


def test_config_round_trip_and_folders(appdata) -> None:
    cfg = config.load_config()
    assert cfg.accounts == {}
    account = cfg.ensure_account("Alex@Example.com")
    account.root_dir = "D:/Photos/Alex"
    account.albums = ["Trip"]
    account.compact_long_side = 1600
    config.save_config(cfg)

    loaded = config.load_config()
    same = loaded.account("alex@example.com")
    assert same.root_dir == "D:/Photos/Alex" and same.albums == ["Trip"]
    assert loaded.active_account == config.account_id("alex@example.com")
    settings = same.to_settings()
    assert settings.album_ids == ("Trip",) and settings.compact_long_side == 1600
    assert settings.min_free_bytes == 5 * 1024**3
    assert config.session_dir("alex@example.com").parent == appdata / "sessions"
    assert "alex" not in str(config.state_db_path("alex@example.com")).lower().replace(str(appdata).lower(), "")
    assert not list(appdata.glob("*.tmp"))


def test_config_migrates_old_files_and_ignores_unknown_keys(appdata) -> None:
    appdata.mkdir(parents=True)
    key = config.account_id("a@b.c")
    old = {"accounts": {key: {"apple_id": "a@b.c", "root_dir": "X:/p", "from_the_future": 1}}}
    (appdata / "config.json").write_text(json.dumps(old), encoding="utf-8")
    cfg = config.load_config()
    assert cfg.version == config.CONFIG_VERSION and cfg.account("a@b.c").root_dir == "X:/p"


def test_two_accounts_on_one_folder_are_reported(appdata) -> None:
    cfg = config.AppConfig()
    cfg.ensure_account("a@b.c").root_dir = "D:/Photos"
    cfg.ensure_account("x@y.z").root_dir = "d:/photos/"
    cfg.ensure_account("solo@y.z").root_dir = "D:/Other"
    assert cfg.shared_roots("a@b.c") == ["x@y.z"] and cfg.shared_roots("solo@y.z") == []


def test_settings_are_clamped() -> None:
    account = config.AccountConfig("a@b.c", concurrency=99, compact_quality=10, compact_long_side=123)
    settings = account.to_settings()
    assert (settings.concurrency, settings.compact_quality, settings.compact_long_side) == (8, 60, 2048)


# ------------------------------------------------------------------ logging


def test_apple_id_is_masked() -> None:
    assert mask_apple_id("alex@example.com") == "al***@example.com"
    assert scrub("login for alex.p@icloud.com failed") == "login for al***@icloud.com failed"


@pytest.mark.parametrize(
    "line",
    [
        "POST /signin {'accountName': 'u', 'password': 'Hunter2-secret'}",
        'headers: {"X-Apple-Session-Token": "TOKEN-abc123", "scnt": "SCNT-xyz"}',
        "Set-Cookie: X-APPLE-WEBAUTH-TOKEN=v=1:t=COOKIEVALUE; Path=/",
        "session_token=TOKEN-abc123 trust_token: TRUST-777",
        "verifying securityCode: {'code': '123456'}",
        "entered code 654321 for device",
        "GET https://cvws.icloud-content.com/B/abc/IMG_1.HEIC?o=SIGNATURE&k=KEY",
        'dsWebAuthToken": "WEBTOKEN-1"',
    ],
)
def test_secrets_never_survive_scrubbing(line: str) -> None:
    cleaned = scrub(line)
    for secret in ("Hunter2-secret", "TOKEN-abc123", "SCNT-xyz", "COOKIEVALUE", "TRUST-777", "123456", "654321", "SIGNATURE", "KEY", "WEBTOKEN-1"):
        assert secret not in cleaned


def test_error_codes_stay_readable() -> None:
    assert "-20283" in scrub('"code" : "-20283", "message" : "Check the account information"')
    assert "(401)" in scrub("Invalid email/password combination. (401)")


def test_log_file_has_no_secrets(tmp_path) -> None:
    log_file = setup_logging(tmp_path / "logs")
    try:
        secret_filter.add_secret("My$ecretPassw0rd")
        log = logging.getLogger("pyicloud_ipd.base")
        log.info("Authenticating %s with %s", "alex@example.com", "My$ecretPassw0rd")
        log.warning("request body: %s", {"password": "another-one", "trustTokens": ["T1"]})
        try:
            raise ValueError("bad password=My$ecretPassw0rd for alex@example.com")
        except ValueError:
            logging.getLogger("ipd_app").exception("login failed")
        for handler in logging.getLogger().handlers:
            handler.flush()
        text = log_file.read_text(encoding="utf-8")
    finally:
        setup_logging(tmp_path / "logs2")  # release the file handle on Windows
    assert "al***@example.com" in text and "login failed" in text and "ValueError" in text
    for secret in ("My$ecretPassw0rd", "another-one", "alex@example.com"):
        assert secret not in text


def test_filter_handles_broken_format_arguments() -> None:
    record = logging.LogRecord("x", logging.INFO, "f", 1, "value %d", ("not-a-number",), None)
    assert SecretFilter().filter(record) is True and "value" in record.getMessage()


# ---------------------------------------------------------------- passwords


class MemoryKeyring:
    def __init__(self) -> None:
        self.saved: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str):
        return self.saved.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.saved[(service, username)] = password


def test_password_lives_only_in_the_keyring(appdata) -> None:
    backend = MemoryKeyring()
    store = PasswordStore(backend)
    assert store.get("alex@example.com") is None
    store.save("alex@example.com", "pass-word-1")
    assert store.get("Alex@Example.com") == "pass-word-1"
    assert list(backend.saved) == [(SERVICE_NAME, config.account_id("alex@example.com"))]
    assert not appdata.exists() or "pass-word-1" not in "".join(
        p.read_text(errors="ignore") for p in appdata.rglob("*") if p.is_file()
    )
    assert scrub("typed pass-word-1", tuple(secret_filter._secrets)) == "typed ***"


# ---------------------------------------------------------------------- cli


def _typed(keys: str, clipboard: str = "") -> tuple[str, str]:
    feed, shown = iter(keys), []
    return cli.read_masked(lambda: next(feed), shown.append, lambda: clipboard), "".join(shown)


def test_masked_password_input() -> None:
    assert _typed("abX\bc\r") == ("abc", "***\b \b*\n")
    assert _typed("\x16\r", clipboard="S3cret pass\r\n") == ("S3cret pass", "*" * 11 + "\n")
    assert _typed("a\xe0Kb\x00;c\r")[0] == "abc"


def test_cli_sync_on_a_generated_library(appdata, tmp_path, capsys) -> None:
    target = tmp_path / "photos"
    args = ["sync", "--fake", "30", "--root", str(target), "--from", "2023-11-01", "--to", "2023-12-31"]
    assert cli.main([*args, "--dry-run"]) == 0
    assert "К загрузке" in capsys.readouterr().out and tree(target) == []

    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "Скачано:" in out and "Ошибок: 0" in out
    files = tree(target)
    assert files and all(p.startswith(("2023/11 November/", "2023/12 December/")) for p in files)
    assert any("/Compact/" in p and p.endswith(".jpg") for p in files)
    assert any(p.endswith(".MOV") for p in files)

    assert cli.main(args) == 0
    assert "Скачано: 0." in capsys.readouterr().out and tree(target) == files


def test_selfcheck_passes_and_writes_a_report(appdata, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    report = tmp_path / "out" / "report.txt"
    assert cli.main(["selfcheck", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    assert "RESULT: all checks passed" in text and "FAIL" not in text
    assert text.count("\nOK ") == 8 and "sRGB profile" in text


def test_selfcheck_reports_a_broken_part(monkeypatch, tmp_path) -> None:
    from ipd_app import selfcheck

    def broken() -> str:
        raise RuntimeError("libheif is missing")

    monkeypatch.setattr(selfcheck, "CHECKS", [("HEIC and Compact", broken), ("state database", selfcheck._check_state_db)])
    report = tmp_path / "report.txt"
    assert selfcheck.run_selfcheck(report) == 1
    text = report.read_text(encoding="utf-8")
    assert "FAIL  HEIC and Compact: RuntimeError: libheif is missing" in text
    assert "OK    state database" in text and "1 check(s) failed" in text


def test_forget_credentials_removes_sessions_only(appdata, tmp_path, monkeypatch) -> None:
    from ipd_app import accounts

    backend = MemoryKeyring()
    backend.delete_password = lambda service, user: backend.saved.pop((service, user))
    monkeypatch.setattr(accounts, "_system_backend", lambda: backend)
    cfg = config.AppConfig()
    cfg.ensure_account("a@b.c").root_dir = str(tmp_path / "photos")
    config.save_config(cfg)
    PasswordStore().save("a@b.c", "pass-word-2")
    session = config.session_dir("a@b.c")
    session.mkdir(parents=True)
    (session / "abc.session").write_text("{}")
    photo = tmp_path / "photos" / "2023" / "IMG.JPG"
    photo.parent.mkdir(parents=True)
    photo.write_bytes(b"x")

    assert cli.main(["forget-credentials"]) == 0
    assert backend.saved == {} and not session.exists()
    assert photo.exists() and config.load_config().account("a@b.c") is not None


def test_cli_reports_bad_input(appdata, capsys) -> None:
    assert cli.main(["sync", "--fake", "3"]) == 2
    assert cli.main(["sync"]) == 2
    assert cli.main(["sync", "--fake", "3", "--root", "x", "--from", "not-a-date"]) == 2
    assert cli.main(["accounts"]) == 0
    assert "Аккаунтов нет" in capsys.readouterr().out
