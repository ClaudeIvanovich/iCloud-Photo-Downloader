"""iCloud layer: read-only guarantee, record parsing, listing logic, error mapping."""

from __future__ import annotations

import ast
import base64
import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests
from pyicloud_ipd.exceptions import (
    PyiCloudAPIResponseException,
    PyiCloudConnectionErrorException,
    PyiCloudFailedLoginException,
    PyiCloudServiceNotActivatedException,
    PyiCloudServiceUnavailableException,
)
from pyicloud_ipd.services.photos import PhotoAsset

import ipd_app.icloud_adapter as adapter_package
from conftest import utc
from ipd_app.icloud_adapter import (
    AdvancedDataProtectionError,
    AssetFilter,
    BadCredentialsError,
    BadTwoFactorCodeError,
    ICloudClient,
    LibraryNotReadyError,
    LinkExpiredError,
    LoginStatus,
    MediaType,
    NetworkError,
    ServiceUnavailableError,
    SessionExpiredError,
    VersionKind,
    WebAccessDisabledError,
)
from ipd_app.icloud_adapter.fake_client import FakeICloudClient
from ipd_app.icloud_adapter.pyicloud_client import (
    PAGE,
    PyiCloudClient,
    asset_from_photo,
    find_start_offset,
    translate,
)

ADAPTER_DIR = Path(adapter_package.__file__).parent
FORBIDDEN = ("delete", "remove", "unlink", "rmtree", "rmdir", "modify", "expunge", "trash")


# ---------------------------------------------------------------- read-only


def test_adapter_has_no_calls_that_remove_or_change_anything() -> None:
    offenders = []
    for source in ADAPTER_DIR.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            name = None
            if isinstance(node, ast.Call):
                target = node.func
                name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", None)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if any(word in alias.name.lower() for word in FORBIDDEN):
                        offenders.append(f"{source.name}:{node.lineno} import {alias.name}")
            if name and any(word in name.lower() for word in FORBIDDEN):
                offenders.append(f"{source.name}:{node.lineno} {name}")
        text = source.read_text(encoding="utf-8")
        assert "records/modify" not in text
        assert "icloudpd.base" not in text and "autodelete" not in text
    assert offenders == []


def test_interface_exposes_only_read_operations() -> None:
    public = {name for name in vars(ICloudClient) if not name.startswith("_")}
    assert public == {
        "login",
        "submit_2fa_code",
        "request_sms_code",
        "submit_sms_code",
        "is_session_valid",
        "list_albums",
        "count_assets",
        "iter_assets",
        "download",
    }


# ------------------------------------------------------------ record parsing


def _res(size: int, uti: str, prefix: str) -> dict:
    return {
        f"{prefix}Res": {"value": {"size": size, "downloadURL": f"https://cvws/{prefix}?t=secret", "fileChecksum": "x"}},
        f"{prefix}FileType": {"value": uti},
    }


def photo(name="IMG_0001.HEIC", uti="public.heic", asset_fields=None, master_fields=None, record="ASSET-1") -> PhotoAsset:
    master = {
        "recordName": "MASTER-1",
        "fields": {
            "filenameEnc": {"value": base64.b64encode(name.encode()).decode(), "type": "ENCRYPTED_BYTES"},
            "itemType": {"value": uti},
            **_res(1000, uti, "resOriginal"),
            **(master_fields or {}),
        },
    }
    asset = {
        "recordName": record,
        "fields": {
            "masterRef": {"value": {"recordName": "MASTER-1"}},
            "assetDate": {"value": 1704004200000},  # 2023-12-31 06:30 UTC
            "addedDate": {"value": 1704100000000},
            **(asset_fields or {}),
        },
    }
    return PhotoAsset(master, asset)


def test_photo_record_is_translated() -> None:
    asset = asset_from_photo(photo(asset_fields={"timeZoneOffset": {"value": 25200}}))
    assert asset.id == "ASSET-1"  # the asset record, not the shared master
    assert asset.filename == "IMG_0001.HEIC" and asset.media_type is MediaType.PHOTO
    assert asset.asset_date == datetime(2023, 12, 31, 6, 30, tzinfo=timezone.utc)
    assert asset.tz_offset_seconds == 25200
    assert set(asset.versions) == {VersionKind.ORIGINAL}
    original = asset.versions[VersionKind.ORIGINAL]
    assert (original.size, original.extension) == (1000, ".HEIC")
    assert "secret" not in repr(asset)  # download links stay out of logs and reprs


def test_live_photo_and_edit_versions() -> None:
    asset = asset_from_photo(
        photo(
            master_fields=_res(500, "com.apple.quicktime-movie", "resOriginalVidCompl"),
            asset_fields=_res(700, "public.jpeg", "resJPEGFull"),
        )
    )
    assert asset.versions[VersionKind.LIVE_VIDEO].extension == ".MOV"
    assert (asset.versions[VersionKind.EDITED].size, asset.versions[VersionKind.EDITED].extension) == (700, ".JPG")


def test_rendition_on_the_master_is_not_an_edit() -> None:
    asset = asset_from_photo(photo(master_fields=_res(700, "public.jpeg", "resJPEGFull")))
    assert VersionKind.EDITED not in asset.versions


def test_video_record_and_missing_fields() -> None:
    asset = asset_from_photo(
        photo("CLIP.MOV", "com.apple.quicktime-movie", asset_fields={"assetDate": {}, "isHidden": {"value": 1}})
    )
    assert asset.media_type is MediaType.VIDEO and asset.asset_date is None
    assert asset.tz_offset_seconds is None and asset.hidden is True and asset.trashed is False
    assert VersionKind.LIVE_VIDEO not in asset.versions


def test_implausible_timezone_offset_is_ignored() -> None:
    assert asset_from_photo(photo(asset_fields={"timeZoneOffset": {"value": 999999}})).tz_offset_seconds is None


# ------------------------------------------------------------------ listing


def test_find_start_offset() -> None:
    dates = [None, None] + [utc(2020 + i // 100, 1 + (i % 100) % 12, 1) for i in range(500)]
    probes = []

    def date_at(rank):
        probes.append(rank)
        return dates[rank]

    target = utc(2023, 1, 1)
    first = next(i for i, d in enumerate(dates) if d and d >= target)
    assert find_start_offset(date_at, len(dates), target, back_off=0) == first
    assert find_start_offset(date_at, len(dates), target) == max(0, first - PAGE)
    assert len(probes) < 30
    assert find_start_offset(date_at, len(dates), utc(2000, 1, 1), back_off=0) == 2
    assert find_start_offset(date_at, len(dates), utc(2100, 1, 1), back_off=0) == len(dates)
    assert find_start_offset(lambda rank: None, 0, target) == 0


class StubAlbum:
    """Behaves like the library's PhotoAlbum: iterates from `offset`, counts as it goes."""

    def __init__(self, photos: list, fail_at: dict[int, Exception] | None = None) -> None:
        self.items = photos
        self.offset = 0
        self.page_size = 100
        self.fail_at = fail_at if fail_at is not None else {}
        self.started_at: list[int] = []

    def __copy__(self):
        clone = StubAlbum(self.items, self.fail_at)
        clone.started_at = self.started_at
        return clone

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        self.started_at.append(self.offset)
        while self.offset < len(self.items):
            if self.offset in self.fail_at:
                raise self.fail_at.pop(self.offset)
            item = self.items[self.offset]
            self.offset += 1
            yield item


def dated(index: int, when: datetime) -> PhotoAsset:
    return photo(
        f"IMG_{index:04d}.JPG",
        "public.jpeg",
        record=f"A{index}",
        asset_fields={"assetDate": {"value": int(when.timestamp() * 1000)}},
    )


def library(count: int = 1000) -> list[PhotoAsset]:
    # one asset a day starting 2020-01-01
    start = utc(2020, 1, 1).timestamp()
    return [dated(i, datetime.fromtimestamp(start + i * 86400, tz=timezone.utc)) for i in range(count)]


def real_client(tmp_path) -> PyiCloudClient:
    return PyiCloudClient(tmp_path / "session", sleep=lambda seconds: None)


def test_listing_yields_only_the_window_and_stops_early(tmp_path) -> None:
    album = StubAlbum(library())
    window = AssetFilter(taken_from=utc(2021, 1, 1, 0), taken_to=utc(2021, 1, 31, 23))
    assets = list(real_client(tmp_path)._iter_album(album, window))
    assert len(assets) == 31 and assets[0].asset_date.date().isoformat() == "2021-01-01"
    listing_start = album.started_at[-1]
    assert 0 < listing_start <= 366  # jumped close to the period instead of scanning from zero
    assert copy.copy(album).offset == 0


def test_newest_first_listing_as_real_icloud_returns_it(tmp_path) -> None:
    """Found on a real account: 'All photos' comes newest first. The first
    version assumed oldest first and found nothing in any period."""
    album = StubAlbum(list(reversed(library())))  # rank 0 = 2022-09-26, last = 2020-01-01
    client = real_client(tmp_path)
    window = AssetFilter(taken_from=utc(2021, 1, 1, 0), taken_to=utc(2021, 1, 31, 23))
    assets = list(client._iter_album(album, window))
    assert len(assets) == 31
    assert {a.asset_date.date().isoformat() for a in assets} == {f"2021-01-{d:02d}" for d in range(1, 32)}
    listing_start = album.started_at[-1]
    assert 300 < listing_start <= 1000 - 366 - 31 + 1  # jumped near the window, did not scan from rank 0

    probes_before = len(album.started_at)
    assert len(list(client._iter_album(album, window))) == 31  # second pass of the same job
    assert len(album.started_at) == probes_before + 1  # the start is remembered, no new search


def test_newest_first_open_ended_windows(tmp_path) -> None:
    album = StubAlbum(list(reversed(library(100))))  # 2020-01-01 .. 2020-04-09
    client = real_client(tmp_path)
    since = list(client._iter_album(album, AssetFilter(taken_from=utc(2020, 4, 1, 0))))
    assert len(since) == 9 and album.started_at[-1] == 0
    until = list(client._iter_album(album, AssetFilter(taken_to=utc(2020, 1, 10, 23))))
    assert len(until) == 10


def test_find_start_offset_newest_first() -> None:
    dates = [utc(2026, 11, 6), utc(2026, 10, 29), utc(2025, 5, 1), utc(2024, 1, 1), utc(2018, 4, 29), None]
    at = dates.__getitem__
    assert find_start_offset(at, len(dates), utc(2025, 12, 31), descending=True, back_off=0) == 2
    assert find_start_offset(at, len(dates), utc(2030, 1, 1), descending=True, back_off=0) == 0
    assert find_start_offset(at, len(dates), utc(2000, 1, 1), descending=True, back_off=0) == 5


def test_listing_without_window_returns_everything(tmp_path) -> None:
    album = StubAlbum(library(50))
    assert len(list(real_client(tmp_path)._iter_album(album, AssetFilter()))) == 50


def test_listing_resumes_after_a_network_error(tmp_path) -> None:
    album = StubAlbum(library(30), fail_at={10: requests.ConnectionError("reset")})
    assets = list(real_client(tmp_path)._iter_album(album, AssetFilter()))
    assert [a.id for a in assets] == [f"A{i}" for i in range(30)]


def test_listing_gives_up_on_a_permanent_error(tmp_path) -> None:
    album = StubAlbum(library(30), fail_at={5: PyiCloudAPIResponseException("Authentication required", "421")})
    with pytest.raises(SessionExpiredError):
        list(real_client(tmp_path)._iter_album(album, AssetFilter()))


def test_real_client_without_login_is_not_valid(tmp_path) -> None:
    client = real_client(tmp_path)
    assert client.is_session_valid() is False
    with pytest.raises(SessionExpiredError):
        client.list_albums()


# ------------------------------------------------------------ error mapping


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (requests.ConnectionError("x"), NetworkError),
        (requests.Timeout("x"), NetworkError),
        (PyiCloudConnectionErrorException("x"), NetworkError),
        (PyiCloudServiceUnavailableException("x"), ServiceUnavailableError),
        (PyiCloudAPIResponseException("Too many", "429"), ServiceUnavailableError),
        (PyiCloudAPIResponseException("Gone", "410"), LinkExpiredError),
        (PyiCloudAPIResponseException("Authentication required for Account.", "450"), SessionExpiredError),
        (PyiCloudAPIResponseException("Invalid global session", None), SessionExpiredError),
        (PyiCloudFailedLoginException("no password was provided"), SessionExpiredError),
        (PyiCloudFailedLoginException("Web access to iCloud data is disabled: ..."), WebAccessDisabledError),
        (PyiCloudServiceNotActivatedException("has not finished indexing yet", None), LibraryNotReadyError),
    ],
)
def test_library_errors_become_typed_errors(error, expected) -> None:
    translated = translate(error)
    assert type(translated) is expected
    assert translated.user_message and "{" not in translated.user_message


def test_adp_is_recognised_when_the_account_reports_it() -> None:
    denied = PyiCloudAPIResponseException("denied", "ACCESS_DENIED")
    assert type(translate(denied, adp_hint=True)) is AdvancedDataProtectionError
    assert type(translate(denied, adp_hint=False)) is ServiceUnavailableError
    assert "Advanced Data Protection" in AdvancedDataProtectionError().user_message


def test_os_errors_pass_through() -> None:
    error = PermissionError("disk")
    assert translate(error) is error


# --------------------------------------------------------------- fake client


def test_fake_login_flow() -> None:
    fake = FakeICloudClient(password="pw", two_factor_code="123456")
    assert isinstance(fake.login("a@b.c", None).error, SessionExpiredError)
    assert isinstance(fake.login("a@b.c", "wrong").error, BadCredentialsError)
    step = fake.login("a@b.c", "pw")
    assert step.status is LoginStatus.NEEDS_2FA and step.phones
    assert isinstance(fake.submit_2fa_code("000000").error, BadTwoFactorCodeError)
    assert fake.submit_2fa_code("123456").status is LoginStatus.OK
    assert fake.is_session_valid() and fake.login("a@b.c", None).status is LoginStatus.OK
