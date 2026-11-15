"""Offline self-check of an installation: are all the parts the app needs present
and working? Used by the build to test the packaged exe, which has no console.

    iCloudPhotoDownloader.exe selfcheck C:\\Temp\\report.txt

Touches no account, no network and no user data; works in a temp folder.
"""

from __future__ import annotations

import io
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Callable


def _check_icloud_library() -> str:
    import importlib.metadata

    import certifi
    import pyicloud_ipd.base  # noqa: F401
    from pyicloud_ipd.services.photos import PhotoLibrary

    assert Path(certifi.where()).is_file(), "CA bundle is missing"
    return f"icloudpd {importlib.metadata.version('icloudpd')}, list {PhotoLibrary.WHOLE_COLLECTION['list_type'][:20]}..."


def _check_tls() -> str:
    import ssl

    import certifi

    context = ssl.create_default_context(cafile=certifi.where())
    return f"{ssl.OPENSSL_VERSION}, {len(context.get_ca_certs())} CA certificates"


def _check_timezones() -> str:
    import pytz
    from tzlocal import get_localzone

    return f"local zone {get_localzone()}, Bangkok offset {pytz.timezone('Asia/Bangkok').utcoffset(None) or 'ok'}"


def _check_keyring() -> str:
    from .accounts import _system_backend

    backend = _system_backend()
    name = type(backend).__name__
    if sys.platform == "win32":
        assert name == "WinVaultKeyring", f"unexpected password store: {name}"
        # Reading a name that does not exist proves the Credential Manager API answers.
        assert backend.get_password("iCloudPhotoDownloader-selfcheck", "nobody") is None
    return name


def _check_heic_and_compact() -> str:
    from PIL import Image

    from .sync_engine.compact import make_compact, register_heif

    register_heif()
    with tempfile.TemporaryDirectory(prefix="ipd-selfcheck-") as folder:
        source = Path(folder) / "probe.HEIC"
        buffer = io.BytesIO()
        Image.new("RGB", (640, 480), (30, 120, 200)).save(buffer, "HEIF")
        source.write_bytes(buffer.getvalue())
        target = Path(folder) / "Compact" / "probe.jpg"
        assert make_compact(source, target, long_side=320), "copy was not created"
        with Image.open(target) as copy:
            assert copy.format == "JPEG" and copy.size == (320, 240), (copy.format, copy.size)
            assert copy.info.get("icc_profile"), "sRGB profile is missing"
    return "HEIC decoded, JPEG 320x240 with sRGB profile written"


def _check_state_db() -> str:
    import sqlite3

    from .icloud_adapter import VersionKind
    from .sync_engine import StateDB

    with tempfile.TemporaryDirectory(prefix="ipd-selfcheck-") as folder:
        db = StateDB(Path(folder) / "state.sqlite")
        db.add_file("A", VersionKind.ORIGINAL, "2023/03 March/Full size/x.HEIC", 1, None)
        assert db.path_owner("2023/03 MARCH/full size/X.heic") is not None
        db.close()
    return f"SQLite {sqlite3.sqlite_version}"


def _check_engine() -> str:
    from datetime import date

    from .icloud_adapter.fake_client import demo_library
    from .sync_engine import Period, StateDB, SyncEngine, SyncSettings

    with tempfile.TemporaryDirectory(prefix="ipd-selfcheck-") as folder:
        root = Path(folder) / "root"
        root.mkdir()
        db = StateDB(Path(folder) / "state.sqlite")
        try:
            engine = SyncEngine(demo_library(6), db, SyncSettings(root=root, min_free_bytes=0))
            report = engine.run(Period(date(2023, 11, 1), date(2023, 12, 31)))
        finally:
            db.close()
        assert report.finished and report.downloaded > 0 and not report.errors, report
        assert not report.compact_errors and report.compact_made > 0, report
    return f"{report.downloaded} files downloaded, {report.compact_made} copies made"


def _check_qt() -> str:
    from PySide6.QtCore import qVersion
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from .ui import icons

    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert not icons.render("active", 64).isNull(), "icon did not render"
    platform = app.platformName()
    tray = QSystemTrayIcon.isSystemTrayAvailable()
    return f"Qt {qVersion()}, platform {platform}, system tray {'available' if tray else 'not available'}"


CHECKS: list[tuple[str, Callable[[], str]]] = [
    ("iCloud library", _check_icloud_library),
    ("TLS", _check_tls),
    ("timezones", _check_timezones),
    ("password store", _check_keyring),
    ("HEIC and Compact", _check_heic_and_compact),
    ("state database", _check_state_db),
    ("sync engine", _check_engine),
    ("Qt", _check_qt),
]


def run_selfcheck(report_path: Path | None = None) -> int:
    from . import __version__

    lines = [f"iCloud Photo Downloader {__version__}, Python {sys.version.split()[0]}, frozen={getattr(sys, 'frozen', False)}"]
    failed = 0
    for name, check in CHECKS:
        try:
            lines.append(f"OK    {name}: {check()}")
        except Exception:  # noqa: BLE001 - report every failure, do not stop at the first
            failed += 1
            lines.append(f"FAIL  {name}: {traceback.format_exc().strip().splitlines()[-1]}")
            lines.append(traceback.format_exc())
    lines.append(f"RESULT: {'all checks passed' if not failed else f'{failed} check(s) failed'}")
    text = "\n".join(lines) + "\n"
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8")
    if sys.stdout is not None:
        print(text, end="")
    return 1 if failed else 0
