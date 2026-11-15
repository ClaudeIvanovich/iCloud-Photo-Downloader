"""Which assets and which of their files a job downloads (REQUIREMENTS.md, 6.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..icloud_adapter import Asset, AssetFilter, MediaType, VersionKind
from .capture import Period

COMPACT_SIZES = (None, 4096, 2048, 1600)  # None = keep the original size


@dataclass
class SyncSettings:
    """Per-account settings the engine works with."""

    root: Path
    photos: bool = True
    videos: bool = True
    album_ids: tuple[str, ...] | None = None  # None = whole personal library
    live_video: bool = True
    edited: bool = False
    compact_enabled: bool = True
    compact_long_side: int | None = 2048
    compact_quality: int = 85
    concurrency: int = 3
    min_free_bytes: int = 5 * 1024**3
    restore_deleted: bool = True
    compact_workers: int | None = None  # None = half of the CPU cores

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.concurrency = min(8, max(1, int(self.concurrency)))
        self.compact_quality = min(95, max(60, int(self.compact_quality)))
        if self.compact_long_side not in COMPACT_SIZES:
            self.compact_long_side = 2048


def accepts(asset: Asset, settings: SyncSettings) -> bool:
    """Hidden and recently removed items are always excluded, whatever the source."""
    if asset.hidden or asset.trashed:
        return False
    if VersionKind.ORIGINAL not in asset.versions:
        return False
    if asset.media_type is MediaType.PHOTO:
        return settings.photos
    return settings.videos


def wanted_kinds(asset: Asset, settings: SyncSettings) -> list[VersionKind]:
    """Files to fetch for an accepted asset. The original always comes first."""
    kinds = [VersionKind.ORIGINAL]
    if settings.live_video and VersionKind.LIVE_VIDEO in asset.versions:
        kinds.append(VersionKind.LIVE_VIDEO)
    if settings.edited and VersionKind.EDITED in asset.versions:
        kinds.append(VersionKind.EDITED)
    return kinds


def listing_filter(settings: SyncSettings, period: Period) -> AssetFilter:
    taken_from, taken_to = period.utc_window()
    return AssetFilter(album_ids=settings.album_ids, taken_from=taken_from, taken_to=taken_to)


# Rough size of one JPG copy, by long side. Used only for the free-space estimate.
_COMPACT_BYTES = {None: 3_500_000, 4096: 2_500_000, 2048: 800_000, 1600: 500_000}


def estimate_compact_bytes(original_size: int, settings: SyncSettings) -> int:
    """Approximate size of one JPG copy; a copy is not larger than a typical
    file of its resolution and rarely larger than its original."""
    per_file = _COMPACT_BYTES.get(settings.compact_long_side, 800_000)
    return min(int(per_file * (settings.compact_quality / 85)), max(original_size, 1))


@dataclass
class Plan:
    """What a job is about to do. Shown to the user before downloading starts."""

    files_in_period: int = 0
    files_present: int = 0
    files_to_download: int = 0
    bytes_to_download: int = 0
    boundary_assets: int = 0  # period membership known only after reading the file
    skipped_deleted: int = 0  # removed by hand, not restored by the user's choice
    compact_to_make: int = 0
    compact_bytes: int = 0
    conflicts: list[tuple[str, str]] = field(default_factory=list)

    @property
    def required_bytes(self) -> int:
        return self.bytes_to_download + self.compact_bytes
