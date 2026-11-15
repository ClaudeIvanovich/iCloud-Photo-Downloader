"""Per-account sync state in SQLite.

The root folder is the source of truth; this database is a cache that makes
re-runs fast and keeps file-name assignments stable. If it is lost or damaged,
a new one is created and refilled from what is on disk.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..icloud_adapter import VersionKind
from .capture import Capture
from .path_builder import path_key

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

STATUS_PLANNED = "planned"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_CONFLICT = "conflict"

COMPACT_NONE = "none"  # no copy is made for this file
COMPACT_PENDING = "pending"
COMPACT_DONE = "done"
COMPACT_ERROR = "error"

JOB_RUNNING = "running"
JOB_STOPPED = "stopped"
JOB_FINISHED = "finished"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS files (
    asset_id       TEXT NOT NULL,
    kind           TEXT NOT NULL,
    rel_path       TEXT NOT NULL,
    path_key       TEXT NOT NULL UNIQUE,
    size           INTEGER NOT NULL,
    status         TEXT NOT NULL,
    error          TEXT,
    downloaded_at  TEXT,
    compact_path   TEXT,
    compact_key    TEXT UNIQUE,
    compact_status TEXT NOT NULL DEFAULT 'none',
    compact_error  TEXT,
    PRIMARY KEY (asset_id, kind)
);
CREATE TABLE IF NOT EXISTS captures (
    asset_id TEXT PRIMARY KEY,
    wall     TEXT,
    source   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date_from   TEXT,
    date_to     TEXT,
    params      TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    finished_at TEXT,
    total_files INTEGER NOT NULL DEFAULT 0,
    done_files  INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass(frozen=True)
class FileRow:
    asset_id: str
    kind: VersionKind
    rel_path: str
    size: int
    status: str
    error: str | None
    compact_path: str | None
    compact_status: str


@dataclass(frozen=True)
class JobRow:
    id: int
    date_from: str | None
    date_to: str | None
    params: dict[str, Any]
    status: str
    total_files: int
    done_files: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StateDB:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path) if str(path) != ":memory:" else None
        self.recovered_from: Path | None = None
        self._lock = threading.RLock()
        self._conn = self._open(str(path))

    def _open(self, target: str) -> sqlite3.Connection:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            return self._connect(target)
        except sqlite3.DatabaseError as error:
            if self.path is None:
                raise
            # Keep the damaged file for inspection and start over; the next
            # reconciliation refills the state from the root folder.
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            aside = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
            self.path.rename(aside)
            for suffix in ("-wal", "-shm"):  # stale journals must not attach to the new file
                journal = self.path.with_name(self.path.name + suffix)
                if journal.exists():
                    journal.rename(aside.with_name(aside.name + suffix))
            self.recovered_from = aside
            log.error("State database was damaged (%s); moved it aside to %s", error, aside.name)
            return self._connect(target)

    def _connect(self, target: str) -> sqlite3.Connection:
        conn = sqlite3.connect(target, check_same_thread=False, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise sqlite3.DatabaseError("integrity check failed")
            if self.path is not None:
                conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(_SCHEMA)
            conn.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            return conn
        except sqlite3.DatabaseError:
            conn.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -------------------------------------------------------------- files

    @staticmethod
    def _file(row: sqlite3.Row) -> FileRow:
        return FileRow(
            asset_id=row["asset_id"],
            kind=VersionKind(row["kind"]),
            rel_path=row["rel_path"],
            size=row["size"],
            status=row["status"],
            error=row["error"],
            compact_path=row["compact_path"],
            compact_status=row["compact_status"],
        )

    def files_for(self, asset_id: str) -> dict[VersionKind, FileRow]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM files WHERE asset_id = ?", (asset_id,)).fetchall()
        return {self._file(row).kind: self._file(row) for row in rows}

    def path_owner(self, rel_path: str) -> tuple[str, VersionKind] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT asset_id, kind FROM files WHERE path_key = ?", (path_key(rel_path),)
            ).fetchone()
        return (row["asset_id"], VersionKind(row["kind"])) if row else None

    def compact_owner(self, rel_path: str) -> tuple[str, VersionKind] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT asset_id, kind FROM files WHERE compact_key = ?", (path_key(rel_path),)
            ).fetchone()
        return (row["asset_id"], VersionKind(row["kind"])) if row else None

    def add_file(
        self,
        asset_id: str,
        kind: VersionKind,
        rel_path: str,
        size: int,
        compact_path: str | None,
    ) -> FileRow:
        with self._lock:
            self._conn.execute(
                "INSERT INTO files (asset_id, kind, rel_path, path_key, size, status,"
                " compact_path, compact_key, compact_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    asset_id,
                    kind.value,
                    rel_path,
                    path_key(rel_path),
                    size,
                    STATUS_PLANNED,
                    compact_path,
                    path_key(compact_path) if compact_path else None,
                    COMPACT_PENDING if compact_path else COMPACT_NONE,
                ),
            )
        return self.files_for(asset_id)[kind]

    def set_status(self, asset_id: str, kind: VersionKind, status: str, error: str | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE files SET status = ?, error = ?,"
                " downloaded_at = CASE WHEN ? = 'done' THEN COALESCE(downloaded_at, ?) ELSE downloaded_at END"
                " WHERE asset_id = ? AND kind = ?",
                (status, error, status, _now(), asset_id, kind.value),
            )

    def set_size(self, asset_id: str, kind: VersionKind, size: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE files SET size = ? WHERE asset_id = ? AND kind = ?", (size, asset_id, kind.value)
            )

    def set_compact_status(
        self, asset_id: str, kind: VersionKind, status: str, error: str | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE files SET compact_status = ?, compact_error = ? WHERE asset_id = ? AND kind = ?",
                (status, error, asset_id, kind.value),
            )

    def count_files(self, status: str | None = None) -> int:
        with self._lock:
            if status is None:
                return self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
            return self._conn.execute("SELECT COUNT(*) FROM files WHERE status = ?", (status,)).fetchone()[0]

    def problems(self) -> list[tuple[str, str, str]]:
        """(relative path, status, message) of files in error or conflict, plus failed copies."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT rel_path, status, COALESCE(error, '') AS message FROM files"
                " WHERE status IN ('error', 'conflict')"
                " UNION ALL SELECT compact_path, 'compact_error', COALESCE(compact_error, '') FROM files"
                " WHERE compact_status = 'error' ORDER BY 1"
            ).fetchall()
        return [(row[0], row[1], row[2]) for row in rows]

    # ----------------------------------------------------------- captures

    def get_capture(self, asset_id: str) -> Capture | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT wall, source FROM captures WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            return None
        wall = datetime.fromisoformat(row["wall"]) if row["wall"] else None
        return Capture(wall, row["source"])

    def set_capture(self, asset_id: str, capture: Capture) -> None:
        wall = capture.wall.isoformat() if capture.wall else None
        with self._lock:
            self._conn.execute(
                "INSERT INTO captures (asset_id, wall, source) VALUES (?, ?, ?)"
                " ON CONFLICT(asset_id) DO UPDATE SET wall = excluded.wall, source = excluded.source",
                (asset_id, wall, capture.source),
            )

    # --------------------------------------------------------------- jobs

    @staticmethod
    def _job(row: sqlite3.Row) -> JobRow:
        return JobRow(
            id=row["id"],
            date_from=row["date_from"],
            date_to=row["date_to"],
            params=json.loads(row["params"]),
            status=row["status"],
            total_files=row["total_files"],
            done_files=row["done_files"],
        )

    def unfinished_job(self) -> JobRow | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM jobs WHERE status != ? ORDER BY id DESC LIMIT 1", (JOB_FINISHED,)
            ).fetchone()
        return self._job(row) if row else None

    def start_job(self, date_from: str | None, date_to: str | None, params: dict[str, Any]) -> int:
        """Open a job, reusing an unfinished one for the same period. Any other
        unfinished job is closed: only one job exists at a time."""
        with self._lock:
            current = self.unfinished_job()
            if current and (current.date_from, current.date_to) == (date_from, date_to):
                self._conn.execute(
                    "UPDATE jobs SET status = ?, params = ? WHERE id = ?",
                    (JOB_RUNNING, json.dumps(params), current.id),
                )
                return current.id
            self._conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ? WHERE status != ?",
                (JOB_FINISHED, _now(), JOB_FINISHED),
            )
            cursor = self._conn.execute(
                "INSERT INTO jobs (date_from, date_to, params, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (date_from, date_to, json.dumps(params), JOB_RUNNING, _now()),
            )
            return int(cursor.lastrowid)

    def update_job(self, job_id: int, total_files: int | None = None, done_files: int | None = None) -> None:
        with self._lock:
            if total_files is not None:
                self._conn.execute("UPDATE jobs SET total_files = ? WHERE id = ?", (total_files, job_id))
            if done_files is not None:
                self._conn.execute("UPDATE jobs SET done_files = ? WHERE id = ?", (done_files, job_id))

    def close_job(self, job_id: int, finished: bool) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ? WHERE id = ?",
                (JOB_FINISHED if finished else JOB_STOPPED, _now() if finished else None, job_id),
            )
