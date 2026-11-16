"""ICloudClient on top of pyicloud_ipd (the library inside icloudpd).

Everything that depends on the library's internals lives in this file, so an
Apple protocol change or a library upgrade touches one place. Private attributes
of the library that we rely on (see docs/DECISIONS.md, D5):
  PhotoAsset._asset_record / _master_record, PhotoAlbum.offset / page_size.
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import requests
from pyicloud_ipd.base import PyiCloudService
from pyicloud_ipd.exceptions import (
    PyiCloud2SARequiredException,
    PyiCloudAPIResponseException,
    PyiCloudConnectionErrorException,
    PyiCloudFailedLoginException,
    PyiCloudFailedMFAException,
    PyiCloudServiceNotActivatedException,
    PyiCloudServiceUnavailableException,
)
from pyicloud_ipd.item_type import AssetItemType
from pyicloud_ipd.services.photos import download_asset

from .client import ICloudClient, ProgressCallback
from .errors import (
    AdvancedDataProtectionError,
    BadCredentialsError,
    BadTwoFactorCodeError,
    DownloadCancelled,
    ICloudError,
    LibraryNotReadyError,
    LinkExpiredError,
    NetworkError,
    SecurityKeyRequiredError,
    ServiceUnavailableError,
    SessionExpiredError,
    WebAccessDisabledError,
)
from .models import (
    Album,
    Asset,
    AssetFilter,
    AssetVersion,
    LoginResult,
    LoginStatus,
    MediaType,
    TrustedPhone,
    VersionKind,
)

log = logging.getLogger(__name__)

CHUNK = 256 * 1024
MAX_TZ_OFFSET = 14 * 3600
# iCloud returns pages of up to 200 records. We stop a listing only after a whole
# page of assets past the end of the window, in case the order is not strict.
PAGE = 200
LISTING_RETRIES = 4
OFFSET_CACHE_SECONDS = 600.0
EXCLUDED_ALBUMS = {"Hidden", "Recently Deleted"}

UTI_EXTENSIONS = {
    "public.heic": ".HEIC",
    "public.heif": ".HEIF",
    "public.jpeg": ".JPG",
    "public.png": ".PNG",
    "public.jpeg-xl": ".JXL",
    "public.mpeg-4": ".MP4",
    "com.apple.quicktime-movie": ".MOV",
    "com.apple.m4v-video": ".M4V",
    "com.adobe.raw-image": ".DNG",
}
RETRYABLE_CODES = {"429", "500", "502", "503", "504"}
SESSION_CODES = {"401", "421", "450"}


# --------------------------------------------------------------------------
# Pure helpers
# --------------------------------------------------------------------------


def _value(fields: dict[str, Any], name: str) -> Any:
    field = fields.get(name)
    return field.get("value") if isinstance(field, dict) else None


def _utc(milliseconds: Any) -> datetime | None:
    if isinstance(milliseconds, bool) or not isinstance(milliseconds, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(milliseconds / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _resource(fields: dict[str, Any], prefix: str, kind: VersionKind, fallback_ext: str) -> AssetVersion | None:
    res = _value(fields, f"{prefix}Res")
    if not isinstance(res, dict) or "downloadURL" not in res or "size" not in res:
        return None
    uti = _value(fields, f"{prefix}FileType")
    extension = UTI_EXTENSIONS.get(uti, fallback_ext)
    return AssetVersion(kind, int(res["size"]), extension, handle=res["downloadURL"])


def asset_from_photo(photo: Any) -> Asset:
    """Translate a library PhotoAsset into our model. Raises KeyError/ValueError
    on records we do not understand; the caller skips those."""
    record = photo._asset_record  # noqa: SLF001
    master_fields = photo._master_record["fields"]  # noqa: SLF001
    asset_fields = record["fields"]
    filename = photo.filename
    media = MediaType.VIDEO if photo.item_type == AssetItemType.MOVIE else MediaType.PHOTO
    own_ext = Path(filename).suffix

    versions: dict[VersionKind, AssetVersion] = {}
    original = _resource(master_fields, "resOriginal", VersionKind.ORIGINAL, own_ext)
    if original is not None:
        # The file keeps its own name and extension, whatever the declared type is.
        versions[VersionKind.ORIGINAL] = AssetVersion(
            VersionKind.ORIGINAL, original.size, own_ext or original.extension, original.handle
        )
    if media is MediaType.PHOTO:
        live = _resource(asset_fields, "resOriginalVidCompl", VersionKind.LIVE_VIDEO, ".MOV") or _resource(
            master_fields, "resOriginalVidCompl", VersionKind.LIVE_VIDEO, ".MOV"
        )
        if live is not None:
            versions[VersionKind.LIVE_VIDEO] = live
        # An edit is stored on the asset record only; the master never has it.
        edited = _resource(asset_fields, "resJPEGFull", VersionKind.EDITED, ".JPG")
    else:
        edited = _resource(asset_fields, "resVidFull", VersionKind.EDITED, ".MOV")
    if edited is not None:
        versions[VersionKind.EDITED] = edited

    offset = _value(asset_fields, "timeZoneOffset")
    if isinstance(offset, bool) or not isinstance(offset, (int, float)) or abs(offset) > MAX_TZ_OFFSET:
        offset = None

    return Asset(
        id=str(record["recordName"]),
        filename=filename,
        media_type=media,
        asset_date=_utc(_value(asset_fields, "assetDate")),
        added_date=_utc(_value(asset_fields, "addedDate")),
        tz_offset_seconds=int(offset) if offset is not None else None,
        versions=versions,
        hidden=bool(_value(asset_fields, "isHidden")),
        trashed=bool(_value(asset_fields, "isDeleted")),
    )


def find_start_offset(
    date_at: Callable[[int], datetime | None],
    total: int,
    target: datetime,
    descending: bool = False,
    back_off: int = PAGE,
) -> int:
    """Rank to start listing from so that nothing inside the window is skipped.

    The list is ordered by capture date. Oldest first: the first rank dated
    >= target (the start of the window); undated items sort first. Newest
    first: the first rank dated <= target (the end of the window); undated
    items sort last. `back_off` steps back one page as a margin against a
    not-quite-strict order.
    """
    low, high = 0, max(total, 0)
    while low < high:
        middle = (low + high) // 2
        value = date_at(middle)
        if descending:
            before_window = value is not None and value > target
        else:
            before_window = value is None or value < target
        if before_window:
            low = middle + 1
        else:
            high = middle
    return max(0, low - back_off)


def translate(error: BaseException, adp_hint: bool = False) -> Exception:
    """Map a library / transport exception to an ICloudError. OS errors pass through."""
    if isinstance(error, (ICloudError, DownloadCancelled, OSError)) and not isinstance(
        error, requests.RequestException
    ):
        return error  # type: ignore[return-value]
    text = str(error)
    if isinstance(error, (PyiCloudConnectionErrorException, requests.RequestException)):
        return NetworkError(text)
    if isinstance(error, PyiCloudServiceUnavailableException):
        return ServiceUnavailableError(text)
    if isinstance(error, PyiCloudFailedMFAException):
        return BadTwoFactorCodeError(text)
    if "Web access to iCloud data is disabled" in text:
        return WebAccessDisabledError(text)
    if isinstance(error, (PyiCloudFailedLoginException, PyiCloud2SARequiredException)):
        return SessionExpiredError(text)
    if isinstance(error, PyiCloudServiceNotActivatedException):
        if "indexing" in text:
            return LibraryNotReadyError(text)
        return AdvancedDataProtectionError(text) if adp_hint else LibraryNotReadyError(text)
    if isinstance(error, PyiCloudAPIResponseException):
        code = str(error.code or "")
        if code in RETRYABLE_CODES:
            return ServiceUnavailableError(text)
        if code == "410":
            return LinkExpiredError(text)
        if code == "ACCESS_DENIED":
            return AdvancedDataProtectionError(text) if adp_hint else ServiceUnavailableError(text)
        if (
            code in SESSION_CODES
            or "Authentication required" in text
            or "Invalid global session" in text
            or "X-APPLE-WEBAUTH-TOKEN" in text
        ):
            return SessionExpiredError(text)
    return ICloudError(f"{type(error).__name__}: {text}")


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class PyiCloudClient(ICloudClient):
    def __init__(
        self,
        session_dir: Path,
        domain: str = "com",
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._session_dir = Path(session_dir)
        self._domain = domain
        self._sleep = sleep
        self._service: PyiCloudService | None = None
        self._ready = False
        # The library rewrites the session and cookie files after every request,
        # so requests must not start concurrently. Bodies still stream in parallel.
        self._lock = threading.RLock()
        # A job lists the same window twice (plan, fetch); remember where it starts.
        self._offsets: dict[tuple[str, str], tuple[float, int, bool]] = {}

    # -------------------------------------------------------------- login

    def login(self, apple_id: str, password: str | None) -> LoginResult:
        self._ready = False
        self._service = None
        self._session_dir.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock:
                service = PyiCloudService(
                    self._domain,
                    apple_id,
                    lambda: password,
                    cookie_directory=str(self._session_dir),
                )
        except PyiCloudFailedLoginException as error:
            text = str(error)
            if password is None or "no password was provided" in text:
                return LoginResult(LoginStatus.FAILED, SessionExpiredError(text))
            if "Invalid email/password" in text or "Failed to initiate srp" in text:
                return LoginResult(LoginStatus.FAILED, BadCredentialsError(text))
            return LoginResult(LoginStatus.FAILED, ICloudError(text))
        except Exception as error:  # noqa: BLE001 - everything becomes a typed result
            return LoginResult(LoginStatus.FAILED, self._as_icloud_error(error))
        # Never keep the password reachable after sign-in: a later silent
        # re-authentication must fail and surface as "session expired".
        service.password_provider = lambda: None
        self._service = service
        return self._after_auth()

    def _after_auth(self) -> LoginResult:
        service = self._require_service()
        try:
            with self._lock:
                if service.requires_2fa:
                    phones = tuple(
                        TrustedPhone(p.id, p.obfuscated_number)
                        for p in service.get_trusted_phone_numbers()
                    )
                    if not phones and service.get_security_key_challenge():
                        return LoginResult(LoginStatus.FAILED, SecurityKeyRequiredError())
                    if not service.trigger_push_notification():
                        log.warning("Could not trigger the 2FA push; the code may still arrive")
                    return LoginResult(LoginStatus.NEEDS_2FA, phones=phones)
                if service.requires_2sa:
                    return LoginResult(
                        LoginStatus.FAILED,
                        ICloudError("legacy two-step verification (2SA) is not supported"),
                    )
        except Exception as error:  # noqa: BLE001
            return LoginResult(LoginStatus.FAILED, self._as_icloud_error(error))
        if self._flag("isWebAccessAllowed") is False:
            return LoginResult(LoginStatus.FAILED, WebAccessDisabledError())
        self._ready = True
        return LoginResult(LoginStatus.OK)

    def submit_2fa_code(self, code: str) -> LoginResult:
        service = self._require_service()
        try:
            with self._lock:
                accepted = service.validate_2fa_code(code)
        except Exception as error:  # noqa: BLE001
            return LoginResult(LoginStatus.FAILED, self._as_icloud_error(error))
        if not accepted:
            return LoginResult(LoginStatus.FAILED, BadTwoFactorCodeError())
        return self._after_auth()

    def request_sms_code(self, phone_id: int) -> None:
        service = self._require_service()
        try:
            with self._lock:
                sent = service.send_2fa_code_sms(phone_id)
        except Exception as error:  # noqa: BLE001
            raise self._as_icloud_error(error) from error
        if not sent:
            raise ICloudError("the SMS code was not sent")

    def submit_sms_code(self, phone_id: int, code: str) -> LoginResult:
        service = self._require_service()
        try:
            with self._lock:
                accepted = service.validate_2fa_code_sms(phone_id, code)
        except Exception as error:  # noqa: BLE001
            return LoginResult(LoginStatus.FAILED, self._as_icloud_error(error))
        if not accepted:
            return LoginResult(LoginStatus.FAILED, BadTwoFactorCodeError())
        return self._after_auth()

    def is_session_valid(self) -> bool:
        if self._service is None or not self._ready:
            return False
        try:
            with self._lock:
                self._service.authenticate()
            return True
        except (PyiCloudFailedLoginException, PyiCloud2SARequiredException):
            self._ready = False
            return False
        except Exception as error:  # noqa: BLE001
            translated = self._as_icloud_error(error)
            if isinstance(translated, SessionExpiredError):
                self._ready = False
                return False
            raise translated from error

    # ------------------------------------------------------------ library

    def list_albums(self) -> list[Album]:
        return [Album(name, name) for name in self._albums() if name not in EXCLUDED_ALBUMS]

    def count_assets(self, asset_filter: AssetFilter) -> int | None:
        if asset_filter.taken_from or asset_filter.taken_to:
            return None  # iCloud cannot count a date range without listing it
        try:
            with self._lock:
                return sum(len(album) for album in self._source_albums(asset_filter))
        except Exception as error:  # noqa: BLE001
            raise self._as_icloud_error(error) from error

    def iter_assets(self, asset_filter: AssetFilter) -> Iterator[Asset]:
        for album in self._source_albums(asset_filter):
            yield from self._iter_album(album, asset_filter)

    def _iter_album(self, base_album: Any, asset_filter: AssetFilter) -> Iterator[Asset]:
        position, descending = self._start_offset(base_album, asset_filter)
        beyond = 0
        failures = 0
        while True:
            album = copy.copy(base_album)
            album.offset = position
            iterator = iter(album)
            try:
                while True:
                    with self._lock:
                        photo = next(iterator, None)
                    if photo is None:
                        return
                    position = album.offset
                    failures = 0
                    try:
                        asset = asset_from_photo(photo)
                    except (KeyError, TypeError, ValueError) as error:
                        log.warning("Skipping an asset with an unexpected record shape: %r", error)
                        continue
                    taken = asset.asset_date
                    if taken is None:
                        if asset_filter.taken_from is None:
                            yield asset
                        continue
                    too_new = asset_filter.taken_to is not None and taken > asset_filter.taken_to
                    too_old = asset_filter.taken_from is not None and taken < asset_filter.taken_from
                    # In listing order, one side of the window is "not there yet"
                    # and the other is "already past it".
                    if too_old if descending else too_new:
                        beyond += 1
                        if beyond >= PAGE:
                            return
                        continue
                    beyond = 0
                    if too_new or too_old:
                        continue
                    yield asset
            except Exception as error:  # noqa: BLE001
                translated = self._as_icloud_error(error)
                failures += 1
                if not getattr(translated, "transient", False) or failures > LISTING_RETRIES:
                    raise translated from error
                log.warning("Listing failed at rank %d (%s), retrying", position, translated)
                self._sleep(2.0**failures)

    def _start_offset(self, base_album: Any, asset_filter: AssetFilter) -> tuple[int, bool]:
        """(rank to start from, whether the album lists the newest first)."""

        def date_at(rank: int) -> datetime | None:
            probe = copy.copy(base_album)
            probe.offset = rank
            probe.page_size = 1
            with self._lock:
                photo = next(iter(probe), None)
            if photo is None:
                return None
            return _utc(_value(photo._asset_record["fields"], "assetDate"))  # noqa: SLF001

        key = (str(getattr(base_album, "name", "")), f"{asset_filter.taken_from}|{asset_filter.taken_to}")
        cached = self._offsets.get(key)
        if cached and time.monotonic() - cached[0] < OFFSET_CACHE_SECONDS:
            return cached[1], cached[2]
        try:
            with self._lock:
                total = len(base_album)
            # Which way the list runs is the server's business: look, do not assume.
            # Real iCloud returns the newest first.
            first, last = date_at(0), date_at(total - 1) if total > 1 else None
            descending = True if first is None or last is None else first >= last
            target = asset_filter.taken_to if descending else asset_filter.taken_from
            offset = 0 if target is None else find_start_offset(date_at, total, target, descending)
        except Exception as error:  # noqa: BLE001 - an optimisation only; fall back to a full scan
            log.warning("Could not locate the period in the list, scanning from the beginning: %r", error)
            return 0, True
        log.info("Listing %d assets from rank %d, %s first", total, offset, "newest" if descending else "oldest")
        self._offsets[key] = (time.monotonic(), offset, descending)
        return offset, descending

    def download(
        self,
        asset: Asset,
        version: VersionKind,
        dest_path: Path,
        progress_cb: ProgressCallback | None = None,
    ) -> None:
        service = self._require_service()
        url = asset.versions[version].handle
        response = None
        try:
            with self._lock:
                response = download_asset(service.photos.session, url)
            if not response.ok:
                raise PyiCloudAPIResponseException(response.reason or "", str(response.status_code))
            with open(dest_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=CHUNK):
                    if chunk:
                        handle.write(chunk)
                        if progress_cb:
                            progress_cb(len(chunk))
        except Exception as error:  # noqa: BLE001
            translated = self._as_icloud_error(error)
            if translated is error:
                raise
            raise translated from error
        finally:
            if response is not None:
                response.close()

    # ------------------------------------------------------------ helpers

    def _require_service(self) -> PyiCloudService:
        if self._service is None:
            raise SessionExpiredError("not signed in")
        return self._service

    def _flag(self, name: str) -> Any:
        data = self._service.data if self._service is not None else {}
        if name in data:
            return data[name]
        return data.get("dsInfo", {}).get(name)

    def _as_icloud_error(self, error: BaseException) -> Exception:
        return translate(error, adp_hint=bool(self._flag("iCDPEnabled")))

    def _photos(self) -> Any:
        if not self._ready:
            raise SessionExpiredError("not signed in")
        try:
            with self._lock:
                return self._require_service().photos
        except Exception as error:  # noqa: BLE001
            raise self._as_icloud_error(error) from error

    def _albums(self) -> dict[str, Any]:
        photos = self._photos()
        try:
            with self._lock:
                return dict(photos.albums)
        except Exception as error:  # noqa: BLE001
            raise self._as_icloud_error(error) from error

    def _source_albums(self, asset_filter: AssetFilter) -> list[Any]:
        if asset_filter.album_ids is None:
            return [self._photos().all]
        albums = self._albums()
        return [
            albums[album_id]
            for album_id in asset_filter.album_ids
            if album_id in albums and album_id not in EXCLUDED_ALBUMS
        ]
