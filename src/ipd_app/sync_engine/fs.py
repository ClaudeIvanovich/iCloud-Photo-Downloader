"""File-system helpers: long Windows paths, atomic publish, temp-file cleanup.

Safety rule of the whole app: a downloaded photo or video is never overwritten
and never removed. The only things this module removes are the app's own
temporary artefacts: `*.part` files and the empty `_incoming` folder.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path, PurePosixPath

PART_SUFFIX = ".part"
LONG_PATH_THRESHOLD = 240
_REPLACE_RETRIES = 5


def long_path(path: Path | str) -> str:
    r"""Path string that works past MAX_PATH on Windows (\\?\ prefix when needed)."""
    text = os.path.abspath(os.fspath(path))
    if sys.platform != "win32" or len(text) < LONG_PATH_THRESHOLD or text.startswith("\\\\?\\"):
        return text
    if text.startswith("\\\\"):
        return "\\\\?\\UNC\\" + text[2:]
    return "\\\\?\\" + text


def absolute(root: Path, relative: PurePosixPath | str) -> Path:
    return root.joinpath(*PurePosixPath(str(relative)).parts)


def exists(path: Path) -> bool:
    return os.path.exists(long_path(path))


def size_of(path: Path) -> int | None:
    """File size, or None when there is no such file."""
    try:
        return os.stat(long_path(path)).st_size
    except OSError:
        return None


def ensure_dir(path: Path) -> None:
    os.makedirs(long_path(path), exist_ok=True)


def part_path(target: Path) -> Path:
    return target.with_name(target.name + PART_SUFFIX)


def publish(part: Path, target: Path, mtime: float | None = None) -> bool:
    """Atomically move a finished temp file to its final name.

    Returns False, leaving both files alone, when the target already exists:
    an existing file is never replaced.
    """
    if exists(target):
        return False
    source, destination = long_path(part), long_path(target)
    for attempt in range(_REPLACE_RETRIES):
        try:
            os.rename(source, destination)  # unlike os.replace, never clobbers on Windows
            break
        except FileExistsError:
            return False
        except PermissionError:
            # Antivirus or an indexer may hold a fresh file for a moment.
            if attempt == _REPLACE_RETRIES - 1:
                raise
            time.sleep(0.2 * (attempt + 1))
    if mtime is not None:
        set_mtime(target, mtime)
    return True


def set_mtime(path: Path, mtime: float) -> None:
    try:
        os.utime(long_path(path), (mtime, mtime))
    except (OSError, OverflowError, ValueError):
        pass  # dates before 1970 or beyond the filesystem's range


def discard_part(path: Path) -> None:
    """Remove one of our own unfinished temp files. Refuses anything else."""
    if not path.name.endswith(PART_SUFFIX):
        raise ValueError(f"not a temp file: {path.name}")
    try:
        os.remove(long_path(path))
    except FileNotFoundError:
        pass


def discard_parts_in(folder: Path) -> int:
    """Remove leftover `*.part` files directly inside a folder."""
    removed = 0
    try:
        with os.scandir(long_path(folder)) as entries:
            names = [entry.name for entry in entries if entry.is_file() and entry.name.endswith(PART_SUFFIX)]
    except OSError:
        return 0
    for name in names:
        discard_part(folder / name)
        removed += 1
    return removed


def drop_empty_dir(path: Path) -> None:
    """Remove a folder only if it is empty (used for `_incoming`)."""
    try:
        os.rmdir(long_path(path))
    except OSError:
        pass


def is_writable_dir(path: Path) -> bool:
    probe = path / f".ipd_write_test_{os.getpid()}{PART_SUFFIX}"
    try:
        with open(long_path(probe), "wb"):
            pass
        discard_part(probe)
        return True
    except OSError:
        return False
