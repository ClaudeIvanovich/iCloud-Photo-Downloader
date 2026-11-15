"""Folder layout and file naming (REQUIREMENTS.md, 6.3 and 6.3.1). Pure functions."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import PurePosixPath

from ..icloud_adapter import Asset, MediaType, VersionKind

# Hard-coded on purpose: folder names must not depend on the Windows locale.
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
UNKNOWN_DATE_DIR = "Unknown date"
FULL_DIR = "Full size"
COMPACT_DIR = "Compact"
INCOMING_DIR = "_incoming"
EDITED_TAG = "_edited"

# Formats that get a JPG copy in Compact. DNG and other RAW are left out in the MVP.
COMPACT_SOURCE_EXTENSIONS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_NAME_LENGTH = 180


def month_folder(month: int) -> str:
    """3 -> '03 March'."""
    return f"{month:02d} {MONTHS[month - 1]}"


def month_dir(wall: datetime | None) -> PurePosixPath:
    """Relative folder of a month: '2023/03 March', or 'Unknown date'."""
    if wall is None:
        return PurePosixPath(UNKNOWN_DATE_DIR)
    return PurePosixPath(f"{wall.year:04d}") / month_folder(wall.month)


def split_name(filename: str) -> tuple[str, str]:
    """('IMG_1', '.HEIC'). A leading dot is part of the stem."""
    dot = filename.rfind(".")
    if dot <= 0:
        return filename, ""
    return filename[:dot], filename[dot:]


def sanitize_filename(filename: str) -> str:
    """Make a name valid on Windows without changing valid names."""
    name = _INVALID.sub("_", filename).rstrip(" .")
    stem, ext = split_name(name)
    stem = stem.rstrip(" .")
    if not stem:
        stem = "_"
    if stem.upper() in _RESERVED:
        stem = "_" + stem
    if len(stem) + len(ext) > MAX_NAME_LENGTH:
        stem = stem[: MAX_NAME_LENGTH - len(ext)]
    return stem + ext


def conflict_tag(asset_id: str) -> str:
    """Short deterministic suffix derived from the asset id: '_a1b2c3'."""
    return "_" + hashlib.sha1(asset_id.encode("utf-8")).hexdigest()[:6]


def version_filename(asset: Asset, kind: VersionKind, tag: str = "") -> str:
    """Name on disk of one version of an asset.

    original   IMG_1.HEIC          (tagged: IMG_1_a1b2c3.HEIC)
    live video IMG_1.MOV           same base name as its photo
    edited     IMG_1_edited.JPG
    """
    stem, ext = split_name(sanitize_filename(asset.filename))
    stem += tag
    if kind is VersionKind.ORIGINAL:
        return stem + ext
    version_ext = asset.versions[kind].extension
    if kind is VersionKind.LIVE_VIDEO:
        return stem + (version_ext or ".MOV")
    return stem + EDITED_TAG + (version_ext or ext)


def full_path(folder: PurePosixPath, filename: str) -> PurePosixPath:
    return folder / FULL_DIR / filename


def wants_compact(asset: Asset, kind: VersionKind, filename: str) -> bool:
    """Photos in convertible formats get a JPG copy; videos and Live video parts never do."""
    if asset.media_type is not MediaType.PHOTO or kind is VersionKind.LIVE_VIDEO:
        return False
    return split_name(filename)[1].lower() in COMPACT_SOURCE_EXTENSIONS


def compact_path(folder: PurePosixPath, filename: str, with_source_ext: bool = False) -> PurePosixPath:
    """'IMG_1.HEIC' -> Compact/IMG_1.jpg, or Compact/IMG_1_heic.jpg when the plain
    name is taken by another original with the same base name."""
    stem, ext = split_name(filename)
    if with_source_ext and ext:
        stem = f"{stem}_{ext[1:].lower()}"
    return folder / COMPACT_DIR / (stem + ".jpg")


def path_key(relative: PurePosixPath | str) -> str:
    """Case-insensitive identity of a path, as Windows sees it."""
    return str(relative).replace("\\", "/").casefold()
