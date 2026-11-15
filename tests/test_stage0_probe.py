"""Offline tests for the pure helpers of the stage 0 probe."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("stage0_probe", REPO / "scripts" / "stage0_probe.py")
probe = importlib.util.module_from_spec(SPEC)
sys.modules["stage0_probe"] = probe
SPEC.loader.exec_module(probe)


def ms(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def test_bangkok_new_year_eve_stays_in_december() -> None:
    # 31 Dec 23:30 in Bangkok (UTC+7) is 16:30 UTC.
    wall = probe.capture_wall_time(ms(2023, 12, 31, 16, 30), 7 * 3600)
    assert wall == datetime(2023, 12, 31, 23, 30)


def test_new_york_after_midnight_is_january() -> None:
    # 1 Jan 01:00 in New York (UTC-5) is 06:00 UTC.
    wall = probe.capture_wall_time(ms(2024, 1, 1, 6, 0), -5 * 3600)
    assert wall == datetime(2024, 1, 1, 1, 0)


def test_missing_or_implausible_offset_gives_none() -> None:
    assert probe.capture_wall_time(ms(2024, 1, 1, 6, 0), None) is None
    assert probe.capture_wall_time(None, 3600) is None
    assert probe.capture_wall_time(ms(2024, 1, 1, 6, 0), 15 * 3600) is None
    assert probe.capture_wall_time(ms(2024, 1, 1, 6, 0), True) is None


def test_mask_apple_id() -> None:
    assert probe.mask_apple_id("alex@example.com") == "al***@example.com"
    assert probe.mask_apple_id("a@b.c") == "a***@b.c"
    assert probe.mask_apple_id("noatsign") == "no***"


def test_account_id_is_stable_and_hides_the_address() -> None:
    first = probe.account_id("Alex@Example.com ")
    assert first == probe.account_id("alex@example.com")
    assert len(first) == 16
    assert "alex" not in first


def test_session_dir_layout() -> None:
    path = probe.session_dir("alex@example.com", appdata="X:/AppData/Roaming")
    assert path.parts[-3:] == (
        "iCloudPhotoDownloader",
        "sessions",
        probe.account_id("alex@example.com"),
    )


def test_field_value() -> None:
    record = {"fields": {"timeZoneOffset": {"value": 10800, "type": "INT64"}}}
    assert probe.field_value(record, "timeZoneOffset") == 10800
    assert probe.field_value(record, "assetDate") is None
    assert probe.field_value({}, "assetDate") is None


def test_errors_are_translated() -> None:
    assert "Сессия истекла" in probe.classify_error(Exception("Authentication required for Account."))
    assert "Веб-доступ" in probe.classify_error(
        Exception("Web access to iCloud data is disabled: enable ...")
    )
    assert "пароль" in probe.classify_error(Exception("Invalid email/password combination."))


def masked(keys: str, clipboard: str = "") -> tuple[str, str]:
    feed = iter(keys)
    shown: list[str] = []
    value = probe.read_masked(lambda: next(feed), shown.append, lambda: clipboard)
    return value, "".join(shown)


def test_masked_input_echoes_stars_and_handles_backspace() -> None:
    value, shown = masked("abX\bc\r")
    assert value == "abc"
    assert "a" not in shown and shown.count("*") == 4


def test_ctrl_v_pastes_clipboard_instead_of_control_char() -> None:
    value, shown = masked("\x16\r", clipboard="S3cret pass\r\n")
    assert value == "S3cret pass"
    assert shown == "*" * 11 + "\n"


def test_masked_input_skips_arrow_keys() -> None:
    assert masked("a\xe0Kb\x00;c\r")[0] == "abc"


class FakeResponse:
    ok = True
    status_code = 206

    def __init__(self, body: bytes) -> None:
        self.body = body

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self.body), 4):
            yield self.body[start : start + 4]


class FakeAsset:
    def __init__(self, name: str, body: bytes, declared_size: int | None = None) -> None:
        from pyicloud_ipd.asset_version import AssetVersion
        from pyicloud_ipd.item_type import AssetItemType
        from pyicloud_ipd.version_size import AssetVersionSize

        self.filename = name
        self.body = body
        self.item_type = AssetItemType.IMAGE
        self.has_asset_date = True
        self.asset_date = datetime(2023, 12, 31, 16, 30, tzinfo=timezone.utc)
        self.added_date = datetime(2024, 1, 2, 8, 0, tzinfo=timezone.utc)
        size = len(body) if declared_size is None else declared_size
        self.versions = {AssetVersionSize.ORIGINAL: AssetVersion(size, "https://x", "public.heic", "")}
        self._asset_record = {
            "fields": {
                "assetDate": {"value": ms(2023, 12, 31, 16, 30)},
                "timeZoneOffset": {"value": 25200},
            }
        }

    def download(self, session, url, start=0):
        return FakeResponse(self.body)


class FakeAlbum:
    def __init__(self, assets: list) -> None:
        self.assets = assets
        self.offset = 0

    def __len__(self) -> int:
        return len(self.assets)

    def __iter__(self):
        return iter(self.assets[self.offset :])


class FakeCloud:
    class photos:  # noqa: N801
        session = None


def test_recent_assets_starts_near_the_end() -> None:
    album = FakeAlbum([FakeAsset(f"IMG_{i:04}.HEIC", b"x") for i in range(50)])
    total, assets = probe.recent_assets(album, 20)
    assert total == 50
    assert album.offset == 30
    assert [a.filename for a in assets] == [f"IMG_{i:04}.HEIC" for i in range(30, 50)]


def test_describe_reads_timezone_offset() -> None:
    row = probe.describe(FakeAsset("IMG_0001.HEIC", b"x"))
    assert row["tz_offset_raw"] == 25200
    assert row["capture_wall_time"] == datetime(2023, 12, 31, 23, 30)
    assert row["versions"] == ["A:ORIGINAL"]


def test_download_goes_through_part_file_and_sets_mtime(tmp_path) -> None:
    asset = FakeAsset("IMG_0001.HEIC", b"0123456789")
    assert probe.download_original(FakeCloud, asset, tmp_path).startswith("OK")
    target = tmp_path / "IMG_0001.HEIC"
    assert target.read_bytes() == b"0123456789"
    assert target.stat().st_mtime == asset.asset_date.timestamp()
    assert not list(tmp_path.glob("*.part"))


def test_download_never_overwrites(tmp_path) -> None:
    (tmp_path / "IMG_0001.HEIC").write_bytes(b"mine")
    result = probe.download_original(FakeCloud, FakeAsset("IMG_0001.HEIC", b"0123456789"), tmp_path)
    assert "не трогаю" in result
    assert (tmp_path / "IMG_0001.HEIC").read_bytes() == b"mine"


def test_short_download_is_not_published(tmp_path) -> None:
    asset = FakeAsset("IMG_0001.HEIC", b"0123", declared_size=10)
    assert "не сошёлся" in probe.download_original(FakeCloud, asset, tmp_path)
    assert not (tmp_path / "IMG_0001.HEIC").exists()


def test_probe_has_no_removal_calls() -> None:
    source = (REPO / "scripts" / "stage0_probe.py").read_text(encoding="utf-8").lower()
    for word in ("delete", "unlink", "rmtree", "os.remove", "isdeleted"):
        assert word not in source
