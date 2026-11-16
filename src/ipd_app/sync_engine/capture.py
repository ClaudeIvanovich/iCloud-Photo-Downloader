"""Capture wall time: the clock of the phone at the place of shooting.

Sources, in the order required by REQUIREMENTS.md 6.3:
  1. timezone offset stored with the asset in iCloud;
  2. EXIF DateTimeOriginal (+OffsetTimeOriginal) of a photo,
     com.apple.quicktime.creationdate of a video;
  3. DateTimeOriginal without an offset, taken as is;
  4. the iCloud UTC date converted to the computer's timezone.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import BinaryIO

from .. import strings
from ..icloud_adapter import Asset, MediaType

# No timezone is further than this from UTC.
MARGIN = timedelta(hours=14)

SOURCE_ICLOUD_TZ = "icloud_tz"
SOURCE_FILE = "file"
SOURCE_UTC_WINDOW = "utc_window"
SOURCE_LOCAL_TZ = "local_tz"
SOURCE_ADDED = "added_date"
SOURCE_DISK = "disk"
SOURCE_NONE = "none"


@dataclass(frozen=True)
class Period:
    """Inclusive range of capture dates. None on a side means unbounded."""

    date_from: date | None = None
    date_to: date | None = None

    def contains(self, day: date) -> bool:
        if self.date_from and day < self.date_from:
            return False
        if self.date_to and day > self.date_to:
            return False
        return True

    @property
    def unbounded(self) -> bool:
        return self.date_from is None and self.date_to is None

    def utc_window(self) -> tuple[datetime | None, datetime | None]:
        """Coarse UTC pre-filter with the +-14 h margin (6.7)."""
        from datetime import time, timezone

        start = end = None
        if self.date_from:
            start = datetime.combine(self.date_from, time.min, tzinfo=timezone.utc) - MARGIN
        if self.date_to:
            end = datetime.combine(self.date_to, time.max, tzinfo=timezone.utc) + MARGIN
        return start, end

    def label(self) -> str:
        def fmt(value: date | None) -> str:
            return value.strftime(strings.DATE_FORMAT) if value else "…"

        return f"{fmt(self.date_from)}–{fmt(self.date_to)}"


@dataclass(frozen=True)
class Capture:
    wall: datetime | None  # naive wall-clock time; None = unknown date
    source: str


@dataclass(frozen=True)
class Resolution:
    """Outcome of resolving an asset against a period without touching its file."""

    capture: Capture | None  # None = the file itself must be read first
    in_period: bool | None  # None = undecided until the file is read


def _local_wall(moment: datetime, local_tz: tzinfo | None) -> datetime:
    return moment.astimezone(local_tz).replace(tzinfo=None)


def resolve(asset: Asset, period: Period, cached: Capture | None, local_tz: tzinfo | None = None) -> Resolution:
    """Decide the month folder and period membership from metadata alone, if possible."""
    if asset.asset_date is None:
        if asset.added_date is None:
            return Resolution(Capture(None, SOURCE_NONE), period.unbounded)
        wall = _local_wall(asset.added_date, local_tz)
        return Resolution(Capture(wall, SOURCE_ADDED), period.contains(wall.date()))

    if asset.tz_offset_seconds is not None:
        wall = (asset.asset_date + timedelta(seconds=asset.tz_offset_seconds)).replace(tzinfo=None)
        return Resolution(Capture(wall, SOURCE_ICLOUD_TZ), period.contains(wall.date()))

    if cached is not None and cached.wall is not None:
        return Resolution(cached, period.contains(cached.wall.date()))

    earliest = (asset.asset_date - MARGIN).replace(tzinfo=None)
    latest = (asset.asset_date + MARGIN).replace(tzinfo=None)
    if period.date_to and earliest.date() > period.date_to:
        return Resolution(None, False)
    if period.date_from and latest.date() < period.date_from:
        return Resolution(None, False)
    same_month = (earliest.year, earliest.month) == (latest.year, latest.month)
    surely_inside = period.contains(earliest.date()) and period.contains(latest.date())
    if same_month and surely_inside:
        # Whatever the timezone was, the month and the verdict are the same.
        return Resolution(Capture(_local_wall(asset.asset_date, local_tz), SOURCE_UTC_WINDOW), True)
    return Resolution(None, True if surely_inside else None)


def candidate_months(asset: Asset) -> list[datetime]:
    """Months an asset without a known timezone can fall into (one or two)."""
    if asset.asset_date is None:
        return []
    earliest = (asset.asset_date - MARGIN).replace(tzinfo=None)
    latest = (asset.asset_date + MARGIN).replace(tzinfo=None)
    months = [earliest]
    if (earliest.year, earliest.month) != (latest.year, latest.month):
        months.append(latest)
    return months


def from_file(path: Path, media: MediaType, asset: Asset, local_tz: tzinfo | None = None) -> Capture:
    """Sources 2-4: read the downloaded file, fall back to the computer's timezone."""
    from .fs import long_path

    path = Path(long_path(path))
    wall = read_video_wall_time(path) if media is MediaType.VIDEO else read_photo_wall_time(path)
    if wall is not None:
        return Capture(wall, SOURCE_FILE)
    if asset.asset_date is not None:
        return Capture(_local_wall(asset.asset_date, local_tz), SOURCE_LOCAL_TZ)
    return Capture(None, SOURCE_NONE)


# --------------------------------------------------------------------------
# File readers
# --------------------------------------------------------------------------

_EXIF_IFD = 0x8769
_DATETIME_ORIGINAL = 0x9003
_DATETIME = 0x0132


def _parse_exif_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip().rstrip("\x00")[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None


def read_photo_wall_time(path: Path) -> datetime | None:
    """EXIF DateTimeOriginal as written by the camera (already local to the place)."""
    try:
        from PIL import Image

        from .compact import register_heif

        register_heif()
        with Image.open(path) as image:
            exif = image.getexif()
            taken = _parse_exif_datetime(exif.get_ifd(_EXIF_IFD).get(_DATETIME_ORIGINAL))
            return taken or _parse_exif_datetime(exif.get(_DATETIME))
    except Exception:  # noqa: BLE001 - an unreadable file simply has no EXIF for us
        return None


_CREATION_KEY = b"com.apple.quicktime.creationdate"
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})")
_CONTAINERS = {b"moov", b"meta", b"udta", b"trak", b"mdia"}


def _atoms(handle: BinaryIO, start: int, end: int):
    position = start
    while position + 8 <= end:
        handle.seek(position)
        header = handle.read(8)
        if len(header) < 8:
            return
        size, kind = struct.unpack(">I4s", header)
        body = position + 8
        if size == 1:
            size = struct.unpack(">Q", handle.read(8))[0]
            body += 8
        elif size == 0:
            size = end - position
        if size < 8 or position + size > end:
            return
        yield kind, body, position + size
        position += size


def _find(handle: BinaryIO, start: int, end: int, path: tuple[bytes, ...]) -> tuple[int, int] | None:
    for kind, body, stop in _atoms(handle, start, end):
        if kind == path[0]:
            if len(path) == 1:
                return body, stop
            # A QuickTime 'meta' atom has no version field; an ISO one has 4 bytes of it.
            if kind == b"meta":
                handle.seek(body + 4)
                if handle.read(4) != b"hdlr":
                    body += 4
            found = _find(handle, body, stop, path[1:])
            if found:
                return found
    return None


def read_video_wall_time(path: Path) -> datetime | None:
    """com.apple.quicktime.creationdate: local time of shooting with its UTC offset."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as handle:
            keys = _find(handle, 0, size, (b"moov", b"meta", b"keys"))
            items = _find(handle, 0, size, (b"moov", b"meta", b"ilst"))
            if not keys or not items:
                return None
            handle.seek(keys[0])
            _, count = struct.unpack(">II", handle.read(8))
            names = []
            for _ in range(count):
                key_size, _namespace = struct.unpack(">I4s", handle.read(8))
                names.append(handle.read(key_size - 8))
            if _CREATION_KEY not in names:
                return None
            wanted = names.index(_CREATION_KEY) + 1
            for kind, body, stop in _atoms(handle, items[0], items[1]):
                if struct.unpack(">I", kind)[0] != wanted:
                    continue
                for data_kind, data_body, data_stop in _atoms(handle, body, stop):
                    if data_kind == b"data":
                        handle.seek(data_body + 8)
                        text = handle.read(data_stop - data_body - 8).decode("utf-8", "replace")
                        match = _ISO.search(text)
                        if match:
                            return datetime(*(int(part) for part in match.groups()))
        return None
    except (OSError, struct.error, ValueError):
        return None
