"""Shared fixtures. Everything here is offline: FakeICloudClient, temp folders."""

from __future__ import annotations

import io
import struct
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ipd_app.icloud_adapter.fake_client import FakeICloudClient
from ipd_app.sync_engine import StateDB, SyncEngine, SyncSettings

UTC = timezone.utc


@pytest.fixture(autouse=True)
def russian_texts():
    """The language is process-wide state: every test starts and ends with the default one."""
    from ipd_app import strings

    strings.set_language(strings.DEFAULT_LANGUAGE)
    yield
    strings.set_language(strings.DEFAULT_LANGUAGE)

MOSCOW = timezone(timedelta(hours=3))


def utc(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


def make_exif(taken: str | None = None, orientation: int | None = None, gps: bool = False, model: str | None = None):
    from PIL import Image

    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    if model:
        exif[0x010F] = "Apple"
        exif[0x0110] = model
    if taken:
        exif.get_ifd(0x8769)[0x9003] = taken
    if gps:
        ifd = exif.get_ifd(0x8825)
        ifd[1] = "N"
        ifd[2] = (55.0, 45.0, 21.0)
        ifd[3] = "E"
        ifd[4] = (37.0, 37.0, 3.0)
    return exif


def image_bytes(fmt: str = "JPEG", size=(64, 48), color=(200, 30, 30), exif=None, mode: str = "RGB", **save) -> bytes:
    from PIL import Image

    from ipd_app.sync_engine.compact import register_heif

    register_heif()
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    if exif is not None:
        save["exif"] = exif.tobytes()
    image.save(buffer, fmt, **save)
    return buffer.getvalue()


def _atom(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def mov_bytes(creation: str | None = "2023-12-31T23:30:00+0700") -> bytes:
    """Smallest QuickTime file that carries com.apple.quicktime.creationdate."""
    parts = _atom(b"mvhd", b"\0" * 100)
    if creation:
        key = b"com.apple.quicktime.creationdate"
        keys = _atom(b"keys", struct.pack(">II", 0, 1) + struct.pack(">I4s", 8 + len(key), b"mdta") + key)
        data = _atom(b"data", struct.pack(">II", 1, 0) + creation.encode())
        ilst = _atom(b"ilst", struct.pack(">II", 8 + len(data), 1) + data)
        parts += _atom(b"meta", _atom(b"hdlr", b"\0" * 24) + keys + ilst)
    return _atom(b"ftyp", b"qt  " + b"\0" * 8) + _atom(b"mdat", b"x" * 500) + _atom(b"moov", parts)


@pytest.fixture
def client() -> FakeICloudClient:
    fake = FakeICloudClient()
    fake.session_valid = True
    return fake


@pytest.fixture
def root(tmp_path: Path) -> Path:
    folder = tmp_path / "root"
    folder.mkdir()
    return folder


@pytest.fixture
def make_engine(tmp_path: Path, root: Path, client: FakeICloudClient):
    opened: list[StateDB] = []

    def build(db_name: str = "state.sqlite", free_space=None, **overrides) -> SyncEngine:
        overrides.setdefault("compact_enabled", False)
        overrides.setdefault("min_free_bytes", 0)
        overrides.setdefault("compact_workers", 1)
        overrides.setdefault("root", root)
        settings = SyncSettings(**overrides)
        db = StateDB(tmp_path / db_name)
        opened.append(db)
        events: list[tuple[str, dict]] = []
        kwargs = {"free_space": free_space} if free_space else {}
        engine = SyncEngine(
            client,
            db,
            settings,
            on_event=lambda name, **data: events.append((name, data)),
            local_tz=MOSCOW,
            backoff=lambda attempt: 0.0,
            **kwargs,
        )
        engine.events = events  # type: ignore[attr-defined]
        return engine

    yield build
    for db in opened:
        db.close()


def tree(root: Path) -> list[str]:
    """Relative paths of all files under root, forward slashes, sorted."""
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
