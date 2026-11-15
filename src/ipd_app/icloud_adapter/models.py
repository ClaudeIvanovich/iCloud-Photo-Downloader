"""Plain data passed between the iCloud layer and the sync engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping

from .errors import ICloudError


class MediaType(Enum):
    PHOTO = "photo"
    VIDEO = "video"


class VersionKind(Enum):
    ORIGINAL = "original"
    EDITED = "edited"
    LIVE_VIDEO = "live"


@dataclass(frozen=True)
class AssetVersion:
    kind: VersionKind
    size: int
    extension: str  # with the dot, as it should appear on disk: ".HEIC", ".MOV"
    handle: Any = field(default=None, repr=False, compare=False)  # opaque, adapter-private


@dataclass(frozen=True)
class Asset:
    id: str
    filename: str  # original name from iCloud, not yet sanitised for Windows
    media_type: MediaType
    asset_date: datetime | None  # capture instant, timezone-aware UTC
    added_date: datetime | None  # when it was added to iCloud, timezone-aware UTC
    tz_offset_seconds: int | None  # capture timezone, seconds east of UTC
    versions: Mapping[VersionKind, AssetVersion]
    hidden: bool = False
    trashed: bool = False


@dataclass(frozen=True)
class Album:
    id: str
    name: str


@dataclass(frozen=True)
class AssetFilter:
    """What to enumerate. The window is a coarse pre-filter on the iCloud UTC date;
    the engine makes the final decision by capture wall time."""

    album_ids: tuple[str, ...] | None = None  # None = whole personal library
    taken_from: datetime | None = None  # inclusive, UTC
    taken_to: datetime | None = None  # inclusive, UTC


class LoginStatus(Enum):
    OK = "ok"
    NEEDS_2FA = "needs_2fa"
    FAILED = "failed"


@dataclass(frozen=True)
class TrustedPhone:
    id: int
    masked_number: str


@dataclass(frozen=True)
class LoginResult:
    status: LoginStatus
    error: ICloudError | None = None
    phones: tuple[TrustedPhone, ...] = ()
