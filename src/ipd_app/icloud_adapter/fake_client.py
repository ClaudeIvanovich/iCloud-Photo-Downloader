"""In-memory iCloud for tests and for GUI/CLI development without a real account."""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .client import ICloudClient, ProgressCallback
from .errors import (
    BadCredentialsError,
    BadTwoFactorCodeError,
    ICloudError,
    NetworkError,
    SessionExpiredError,
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

CHUNK = 64 * 1024
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class Truncate:
    """Scripted failure: write `after` bytes, then drop the connection."""

    def __init__(self, after: int) -> None:
        self.after = after


class FakeICloudClient(ICloudClient):
    def __init__(self, password: str = "secret", two_factor_code: str | None = None) -> None:
        self.password = password
        self.two_factor_code = two_factor_code
        self.session_valid = False
        self.assets: dict[str, Asset] = {}
        self.contents: dict[tuple[str, VersionKind], bytes] = {}
        self.albums: dict[str, list[str]] = {}
        # Scripted failures per file, consumed one per download attempt.
        self.failures: dict[tuple[str, VersionKind], list[Exception | Truncate]] = {}
        self.download_calls: list[tuple[str, VersionKind]] = []
        self.listings = 0
        self._pending_2fa = False

    # ----------------------------------------------------------- building

    def add(
        self,
        filename: str,
        content: bytes = b"data",
        *,
        taken: datetime | None = None,
        tz_offset: int | None = 0,
        media: MediaType | None = None,
        live: bytes | None = None,
        edited: bytes | None = None,
        edited_ext: str = ".JPG",
        album: str | None = None,
        added: datetime | None = None,
        asset_id: str | None = None,
        hidden: bool = False,
        trashed: bool = False,
    ) -> Asset:
        ext = Path(filename).suffix
        if media is None:
            media = MediaType.VIDEO if ext.lower() in (".mov", ".mp4", ".m4v") else MediaType.PHOTO
        asset_id = asset_id or f"asset-{len(self.assets) + 1:05d}"
        versions = {VersionKind.ORIGINAL: AssetVersion(VersionKind.ORIGINAL, len(content), ext)}
        self.contents[(asset_id, VersionKind.ORIGINAL)] = content
        if live is not None:
            versions[VersionKind.LIVE_VIDEO] = AssetVersion(VersionKind.LIVE_VIDEO, len(live), ".MOV")
            self.contents[(asset_id, VersionKind.LIVE_VIDEO)] = live
        if edited is not None:
            versions[VersionKind.EDITED] = AssetVersion(VersionKind.EDITED, len(edited), edited_ext)
            self.contents[(asset_id, VersionKind.EDITED)] = edited
        asset = Asset(
            id=asset_id,
            filename=filename,
            media_type=media,
            asset_date=taken,
            added_date=added if added is not None else taken,
            tz_offset_seconds=tz_offset if taken is not None else None,
            versions=versions,
            hidden=hidden,
            trashed=trashed,
        )
        self.assets[asset_id] = asset
        if album:
            self.albums.setdefault(album, []).append(asset_id)
        return asset

    def fail(self, asset: Asset, *steps: Exception | Truncate, kind: VersionKind = VersionKind.ORIGINAL) -> None:
        self.failures.setdefault((asset.id, kind), []).extend(steps)

    # -------------------------------------------------------------- login

    def login(self, apple_id: str, password: str | None) -> LoginResult:
        if password is None:
            if self.session_valid:
                return LoginResult(LoginStatus.OK)
            return LoginResult(LoginStatus.FAILED, SessionExpiredError())
        if password != self.password:
            return LoginResult(LoginStatus.FAILED, BadCredentialsError())
        if self.two_factor_code is not None:
            self._pending_2fa = True
            return LoginResult(LoginStatus.NEEDS_2FA, phones=(TrustedPhone(1, "+7 (***) ***-**-42"),))
        self.session_valid = True
        return LoginResult(LoginStatus.OK)

    def submit_2fa_code(self, code: str) -> LoginResult:
        if not self._pending_2fa or code != self.two_factor_code:
            return LoginResult(LoginStatus.FAILED, BadTwoFactorCodeError())
        self._pending_2fa = False
        self.session_valid = True
        return LoginResult(LoginStatus.OK)

    def request_sms_code(self, phone_id: int) -> None:
        return None

    def submit_sms_code(self, phone_id: int, code: str) -> LoginResult:
        return self.submit_2fa_code(code)

    def is_session_valid(self) -> bool:
        return self.session_valid

    # ------------------------------------------------------------ library

    def list_albums(self) -> list[Album]:
        self._require_session()
        return [Album(name, name) for name in sorted(self.albums)]

    def _selected(self, asset_filter: AssetFilter) -> list[Asset]:
        if asset_filter.album_ids is None:
            # "All photos" in iCloud never contains hidden or recently removed items.
            pool = [a for a in self.assets.values() if not a.hidden and not a.trashed]
        else:
            ids: list[str] = []
            for album_id in asset_filter.album_ids:
                ids.extend(self.albums.get(album_id, []))
            pool = [self.assets[i] for i in ids]
        selected = []
        for asset in pool:
            if asset.asset_date is None:
                if asset_filter.taken_from is None:
                    selected.append(asset)
                continue
            if asset_filter.taken_from and asset.asset_date < asset_filter.taken_from:
                continue
            if asset_filter.taken_to and asset.asset_date > asset_filter.taken_to:
                continue
            selected.append(asset)
        selected.sort(key=lambda a: (a.asset_date or EPOCH, a.id))
        return selected

    def count_assets(self, asset_filter: AssetFilter) -> int | None:
        return len(self._selected(asset_filter))

    def iter_assets(self, asset_filter: AssetFilter) -> Iterator[Asset]:
        self._require_session()
        self.listings += 1
        for asset in self._selected(asset_filter):
            self._require_session()
            yield asset

    def download(
        self,
        asset: Asset,
        version: VersionKind,
        dest_path: Path,
        progress_cb: ProgressCallback | None = None,
    ) -> None:
        self._require_session()
        self.download_calls.append((asset.id, version))
        content = self.contents[(asset.id, version)]
        scripted = self.failures.get((asset.id, version))
        step = scripted.pop(0) if scripted else None
        if isinstance(step, Exception):
            raise step
        limit = step.after if isinstance(step, Truncate) else len(content)
        with open(dest_path, "wb") as handle:
            for start in range(0, limit, CHUNK):
                chunk = content[start : min(start + CHUNK, limit)]
                handle.write(chunk)
                if progress_cb:
                    progress_cb(len(chunk))
        if isinstance(step, Truncate):
            raise NetworkError("connection dropped (scripted)")

    def _require_session(self) -> None:
        if not self.session_valid:
            raise SessionExpiredError()


def demo_library(count: int = 40, first_day: datetime | None = None) -> FakeICloudClient:
    """A small library with real JPEG bytes, for trying the CLI and GUI offline."""
    from PIL import Image

    client = FakeICloudClient()
    client.session_valid = True
    day = first_day or datetime(2023, 11, 20, 9, 0, tzinfo=timezone.utc)
    for index in range(count):
        seed = hashlib.sha256(str(index).encode()).digest()
        image = Image.new("RGB", (640 + index % 3 * 320, 480), tuple(seed[:3]))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=80)
        taken = day + timedelta(days=index * 2, hours=index % 7)
        if index % 5 == 4:
            client.add(f"IMG_{index:04d}.MOV", seed * 2000, taken=taken, tz_offset=10800)
        else:
            client.add(
                f"IMG_{index:04d}.JPG",
                buffer.getvalue(),
                taken=taken,
                tz_offset=10800,
                live=seed * 500 if index % 4 == 0 else None,
                album="Demo" if index % 2 == 0 else None,
            )
    return client


__all__ = ["FakeICloudClient", "ICloudError", "Truncate", "demo_library"]
