"""The period job: reconcile iCloud with the root folder and fetch what is missing.

One job = two listings of the period:
  1. plan   - count what is in the period, what is already on disk, what to fetch;
  2. fetch  - list again and download as assets stream by, so download links are
              fresh and memory use does not depend on the library size.

A link can still go stale when the job stalls for a long time (HTTP 410). Such
files are put aside and, once the listing is through, fetched with fresh links
from one more listing.

The engine knows nothing about Qt. It reports through a single callback and is
driven by pause() / resume() / stop() from any thread.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import tzinfo
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .. import strings
from ..icloud_adapter import (
    Asset,
    AssetVersion,
    DownloadCancelled,
    ICloudClient,
    ICloudError,
    LinkExpiredError,
    SessionExpiredError,
    VersionKind,
)
from . import capture as cap
from . import fs
from . import path_builder as pb
from .capture import Capture, Period
from .compact import make_compact
from .filters import Plan, SyncSettings, accepts, estimate_compact_bytes, listing_filter, wanted_kinds
from .state_db import (
    COMPACT_DONE,
    COMPACT_ERROR,
    STATUS_CONFLICT,
    STATUS_DONE,
    STATUS_ERROR,
    FileRow,
    StateDB,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
FRESH_LINK_ROUNDS = 2  # extra listings for files whose download link went stale
SPACE_CHECK_INTERVAL = 2.0

ACTION_PRESENT = "present"
ACTION_DOWNLOAD = "download"
ACTION_CONFLICT = "conflict"
ACTION_SKIP_DELETED = "skip_deleted"

EventCallback = Callable[..., None]


@dataclass(frozen=True)
class _Stale:
    """A download that failed only because its link was too old."""

    kind: VersionKind
    label: str
    failure: str
    has_row: bool


class JobStopped(Exception):
    """Unwinds a worker when the job is stopped."""


class PreflightError(Exception):
    """The job cannot start. `user_message` is ready to show."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class _SizeMismatch(Exception):
    def __init__(self, got: int | None, expected: int) -> None:
        super().__init__(strings.REASON_SIZE_MISMATCH.format(got=got or 0, expected=expected))


@dataclass
class FileTask:
    kind: VersionKind
    version: AssetVersion
    row: FileRow
    target: Path
    action: str
    compact_target: Path | None = None
    compact_needed: bool = False


@dataclass
class AssetPlan:
    asset: Asset
    in_period: bool | None  # None = decided only after reading the file
    resolved: bool
    tasks: list[FileTask] = field(default_factory=list)


@dataclass
class Report:
    downloaded: int = 0
    skipped: int = 0
    out_of_period: int = 0
    bytes_downloaded: int = 0
    compact_made: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)
    conflicts: list[tuple[str, str]] = field(default_factory=list)
    compact_errors: list[tuple[str, str]] = field(default_factory=list)
    stopped_reason: str | None = None
    plan: Plan | None = None

    @property
    def finished(self) -> bool:
        return self.stopped_reason is None


def default_backoff(attempt: int) -> float:
    """1, 2, 4, 8 seconds before attempts 2..5."""
    return float(2 ** (attempt - 1))


def _free_space(path: Path) -> int:
    return shutil.disk_usage(fs.long_path(path)).free


class SyncEngine:
    def __init__(
        self,
        client: ICloudClient,
        db: StateDB,
        settings: SyncSettings,
        *,
        on_event: EventCallback | None = None,
        local_tz: tzinfo | None = None,
        backoff: Callable[[int], float] = default_backoff,
        free_space: Callable[[Path], int] = _free_space,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.client = client
        self.db = db
        self.settings = settings
        self._on_event = on_event
        self._local_tz = local_tz
        self._backoff = backoff
        self._free_space = free_space
        self._max_attempts = max_attempts

        self._run_lock = threading.Lock()
        self._assign_lock = threading.Lock()
        self._report_lock = threading.Lock()
        self._stop = threading.Event()
        self._running = threading.Event()  # cleared while paused
        self._running.set()
        self._stop_reason: str | None = None
        self._last_space_check = 0.0
        self._report = Report()
        self._period = Period()
        self._compact_pool: ThreadPoolExecutor | None = None
        self._compact_slots: threading.BoundedSemaphore | None = None
        # Files put aside because their link went stale: asset id -> what failed.
        self._stale: dict[str, list[_Stale]] = {}
        self._last_round = False

    # ------------------------------------------------------------ control

    def pause(self) -> None:
        self._running.clear()
        self._emit("status", state="paused")

    def resume(self) -> None:
        self._running.set()
        self._emit("status", state="downloading")

    def stop(self, reason: str | None = None) -> None:
        if self._stop_reason is None:
            self._stop_reason = reason or strings.STOP_USER
        self._stop.set()
        self._running.set()

    @property
    def is_running(self) -> bool:
        return self._run_lock.locked()

    def _emit(self, name: str, **payload: Any) -> None:
        if self._on_event is None:
            return
        try:
            self._on_event(name, **payload)
        except Exception:  # noqa: BLE001 - a listener must never break a job
            log.exception("Event listener failed on %s", name)

    def _checkpoint(self) -> None:
        """Block while paused; unwind when stopped."""
        while not self._running.wait(0.2):
            if self._stop.is_set():
                break
        if self._stop.is_set():
            raise JobStopped

    def _wait(self, seconds: float) -> None:
        if seconds > 0 and self._stop.wait(seconds):
            raise JobStopped

    # ---------------------------------------------------------- preflight

    def preflight(self, period: Period) -> None:
        if period.date_from and period.date_to and period.date_from > period.date_to:
            raise PreflightError(strings.ERR_BAD_PERIOD)
        root = self.settings.root
        if not str(root) or str(root) == ".":
            raise PreflightError(strings.ERR_NO_ROOT)
        if not os.path.isdir(fs.long_path(root)):
            raise PreflightError(strings.ERR_ROOT_UNAVAILABLE.format(path=root))
        if not fs.is_writable_dir(root):
            raise PreflightError(strings.ERR_ROOT_NOT_WRITABLE.format(path=root))
        self._require_space(0)
        if not self.client.is_session_valid():
            raise SessionExpiredError()

    def _require_space(self, upcoming_bytes: int) -> None:
        free = self._free_space(self.settings.root)
        if free - upcoming_bytes < self.settings.min_free_bytes:
            raise PreflightError(
                strings.ERR_LOW_SPACE.format(
                    free=strings.format_size(free),
                    need=strings.format_size(self.settings.min_free_bytes + upcoming_bytes),
                )
            )

    def _check_space(self) -> None:
        now = time.monotonic()
        if now - self._last_space_check < SPACE_CHECK_INTERVAL:
            return
        self._last_space_check = now
        free = self._free_space(self.settings.root)
        if free < self.settings.min_free_bytes:
            self.stop(
                strings.ERR_LOW_SPACE.format(
                    free=strings.format_size(free),
                    need=strings.format_size(self.settings.min_free_bytes),
                )
            )
            raise JobStopped

    # ----------------------------------------------------------- planning

    def _abs(self, relative: str | PurePosixPath) -> Path:
        return fs.absolute(self.settings.root, relative)

    def _capture_for(self, asset: Asset, period: Period, rows: dict[VersionKind, FileRow]) -> cap.Resolution:
        """Resolve the capture time without the network: metadata, cache, then
        files that are already on disk."""
        resolution = cap.resolve(asset, period, self.db.get_capture(asset.id), self._local_tz)
        if resolution.capture is not None or resolution.in_period is False:
            return resolution

        original = asset.versions[VersionKind.ORIGINAL]
        found: Capture | None = None
        if VersionKind.ORIGINAL in rows:
            local = self._abs(rows[VersionKind.ORIGINAL].rel_path)
            if fs.size_of(local) == original.size:
                found = cap.from_file(local, asset.media_type, asset, self._local_tz)
        else:
            # The database knows nothing (new or rebuilt): look where an earlier
            # run could have placed the file.
            for month in cap.candidate_months(asset):
                folder = pb.month_dir(month)
                for tag in ("", pb.conflict_tag(asset.id)):
                    name = pb.version_filename(asset, VersionKind.ORIGINAL, tag)
                    local = self._abs(pb.full_path(folder, name))
                    if fs.size_of(local) != original.size:
                        continue
                    found = cap.from_file(local, asset.media_type, asset, self._local_tz)
                    if found.wall is None or (found.wall.year, found.wall.month) != (month.year, month.month):
                        # The folder the file already sits in wins over a re-read.
                        found = Capture(month, cap.SOURCE_DISK)
                    break
                if found:
                    break
        if found is None or found.wall is None:
            return resolution
        self.db.set_capture(asset.id, found)
        return cap.resolve(asset, period, found, self._local_tz)

    def _assign(self, asset: Asset, kinds: list[VersionKind], rows: dict[VersionKind, FileRow], capture: Capture) -> dict[VersionKind, FileRow]:
        """Give every wanted file of the asset a stable relative path."""
        missing = [kind for kind in kinds if kind not in rows]
        if not missing:
            return rows
        with self._assign_lock:
            rows = self.db.files_for(asset.id)
            missing = [kind for kind in kinds if kind not in rows]
            if not missing:
                return rows
            own_tag = pb.conflict_tag(asset.id)
            if VersionKind.ORIGINAL in rows:
                existing = PurePosixPath(rows[VersionKind.ORIGINAL].rel_path)
                folder = existing.parent.parent
                tag = "" if existing.name == pb.version_filename(asset, VersionKind.ORIGINAL) else own_tag
            else:
                folder = pb.month_dir(capture.wall)
                tag = ""
                for kind in kinds:
                    owner = self.db.path_owner(str(pb.full_path(folder, pb.version_filename(asset, kind))))
                    if owner is not None and owner[0] != asset.id:
                        tag = own_tag
                        break
                if not tag:
                    tagged = pb.full_path(folder, pb.version_filename(asset, VersionKind.ORIGINAL, own_tag))
                    if fs.size_of(self._abs(tagged)) == asset.versions[VersionKind.ORIGINAL].size:
                        tag = own_tag  # an earlier run already resolved a name clash this way
            for kind in missing:
                name = pb.version_filename(asset, kind, tag)
                relative = pb.full_path(folder, name)
                compact_rel: str | None = None
                if pb.wants_compact(asset, kind, name):
                    for with_ext in (False, True):
                        option = str(pb.compact_path(folder, name, with_ext))
                        if self.db.compact_owner(option) is None:
                            compact_rel = option
                            break
                self.db.add_file(asset.id, kind, str(relative), asset.versions[kind].size, compact_rel)
            return self.db.files_for(asset.id)

    def _plan_asset(self, asset: Asset, period: Period) -> AssetPlan | None:
        """Decide what to do with one asset. Touches the database and the local
        disk only; never the network."""
        if not accepts(asset, self.settings):
            return None
        kinds = wanted_kinds(asset, self.settings)
        rows = self.db.files_for(asset.id)
        resolution = self._capture_for(asset, period, rows)
        if resolution.in_period is False:
            return AssetPlan(asset, False, True)
        if resolution.capture is None:
            return AssetPlan(asset, resolution.in_period, False)

        rows = self._assign(asset, kinds, rows, resolution.capture)
        plan = AssetPlan(asset, True, True)
        for kind in kinds:
            row, version = rows[kind], asset.versions[kind]
            target = self._abs(row.rel_path)
            on_disk = fs.size_of(target)
            if on_disk == version.size:
                action = ACTION_PRESENT
                if row.status != STATUS_DONE:
                    self.db.set_status(asset.id, kind, STATUS_DONE)
            elif on_disk is not None:
                action = ACTION_CONFLICT
                if row.status != STATUS_CONFLICT:
                    self.db.set_status(asset.id, kind, STATUS_CONFLICT, strings.REASON_SAME_SIZE_CONFLICT)
            elif row.status == STATUS_DONE and not self.settings.restore_deleted:
                action = ACTION_SKIP_DELETED
            else:
                action = ACTION_DOWNLOAD
            if row.size != version.size:
                self.db.set_size(asset.id, kind, version.size)
            task = FileTask(kind, version, row, target, action)
            if (
                self.settings.compact_enabled
                and row.compact_path
                and action in (ACTION_PRESENT, ACTION_DOWNLOAD)
            ):
                task.compact_target = self._abs(row.compact_path)
                task.compact_needed = not fs.exists(task.compact_target)
            plan.tasks.append(task)
        return plan

    def _listing(self, period: Period):
        seen: set[str] = set()
        for asset in self.client.iter_assets(listing_filter(self.settings, period)):
            if asset.id in seen:  # the same asset can be in several albums
                continue
            seen.add(asset.id)
            yield asset

    def plan(self, period: Period) -> Plan:
        """Pass 1: what is in the period and how much of it is already on disk."""
        plan = Plan()
        for asset in self._listing(period):
            self._checkpoint()
            item = self._plan_asset(asset, period)
            if item is None or item.in_period is False:
                continue
            if not item.resolved:
                kinds = wanted_kinds(asset, self.settings)
                size = sum(asset.versions[kind].size for kind in kinds)
                if item.in_period is None:
                    plan.boundary_assets += 1
                else:
                    plan.files_in_period += len(kinds)
                    plan.files_to_download += len(kinds)
                plan.bytes_to_download += size
                name = pb.version_filename(asset, VersionKind.ORIGINAL)
                if self.settings.compact_enabled and pb.wants_compact(asset, VersionKind.ORIGINAL, name):
                    plan.compact_to_make += 1
                    plan.compact_bytes += estimate_compact_bytes(asset.versions[VersionKind.ORIGINAL].size, self.settings)
                continue
            for task in item.tasks:
                plan.files_in_period += 1
                if task.action == ACTION_PRESENT:
                    plan.files_present += 1
                elif task.action == ACTION_DOWNLOAD:
                    plan.files_to_download += 1
                    plan.bytes_to_download += task.version.size
                elif task.action == ACTION_SKIP_DELETED:
                    plan.skipped_deleted += 1
                else:
                    plan.conflicts.append((task.row.rel_path, strings.REASON_SAME_SIZE_CONFLICT))
                if task.compact_needed:
                    plan.compact_to_make += 1
                    plan.compact_bytes += estimate_compact_bytes(task.version.size, self.settings)
        return plan

    def preview(self, period: Period) -> Plan:
        """Dry run: checks and the plan, no downloads."""
        self._reset()
        self.preflight(period)
        self._emit("status", state="counting")
        try:
            return self.plan(period)
        finally:
            self._clear_controls()
            self._emit("status", state="idle")

    # ---------------------------------------------------------------- run

    def _reset(self) -> None:
        # pause() / stop() called before the job thread got here must not be lost,
        # so the control flags are cleared when a run ends, not when it starts.
        self._last_space_check = 0.0
        self._report = Report()
        self._stale = {}
        self._last_round = False

    def _clear_controls(self) -> None:
        self._stop.clear()
        self._running.set()
        self._stop_reason = None

    def run(self, period: Period) -> Report:
        """Run a job to the end, or until it is stopped. Never raises for
        problems with individual files; those go into the report."""
        if not self._run_lock.acquire(blocking=False):
            raise PreflightError(strings.ERR_JOB_RUNNING)
        try:
            self._reset()
            self._period = period
            report = self._report
            self.preflight(period)
            job_id = self.db.start_job(
                period.date_from.isoformat() if period.date_from else None,
                period.date_to.isoformat() if period.date_to else None,
                {"albums": list(self.settings.album_ids) if self.settings.album_ids else None},
            )
            workers = self.settings.compact_workers or max(1, (os.cpu_count() or 2) // 2)
            self._compact_pool = ThreadPoolExecutor(workers, thread_name_prefix="compact")
            self._compact_slots = threading.BoundedSemaphore(workers * 4)
            try:
                self._emit("status", state="counting")
                self._cleanup_parts(period)
                report.plan = self.plan(period)
                log.info(
                    "Plan for %s: %d in period, %d present, %d to download (%d bytes), %d boundary, %d conflicts",
                    period.label(),
                    report.plan.files_in_period,
                    report.plan.files_present,
                    report.plan.files_to_download,
                    report.plan.bytes_to_download,
                    report.plan.boundary_assets,
                    len(report.plan.conflicts),
                )
                self._emit("plan", plan=report.plan)
                self.db.update_job(job_id, total_files=report.plan.files_in_period)
                self._require_space(report.plan.required_bytes)
                self._emit("status", state="downloading")
                self._fetch(period)
            except JobStopped:
                pass
            except PreflightError as error:
                self._stop_reason = self._stop_reason or error.user_message
            except SessionExpiredError:
                self._stop_reason = self._stop_reason or strings.STOP_SESSION
            except ICloudError as error:
                log.error("Job aborted by an iCloud error: %s", error)
                self._stop_reason = self._stop_reason or error.user_message
            finally:
                stopped = self._stop_reason is not None
                self._compact_pool.shutdown(wait=True, cancel_futures=stopped)
                self._compact_pool = None
                fs.drop_empty_dir(self.settings.root / pb.INCOMING_DIR)
                report.stopped_reason = self._stop_reason
                self.db.update_job(job_id, done_files=report.downloaded + report.skipped)
                self.db.close_job(job_id, finished=not stopped)
                log.info(
                    "Job %s: downloaded %d, skipped %d, errors %d, conflicts %d, copies %d (%d failed)%s",
                    "stopped" if stopped else "finished",
                    report.downloaded,
                    report.skipped,
                    len(report.errors),
                    len(report.conflicts),
                    report.compact_made,
                    len(report.compact_errors),
                    f"; reason: {self._stop_reason}" if stopped else "",
                )
                self._emit("status", state="error" if stopped and self._stop_reason != strings.STOP_USER else "idle")
                self._emit("report", report=report)
            return report
        finally:
            self._clear_controls()
            self._run_lock.release()

    def _month_dirs(self, period: Period) -> list[Path]:
        """Existing month folders that the period covers."""
        root = self.settings.root
        result: list[Path] = []
        try:
            years = [entry for entry in os.scandir(fs.long_path(root)) if entry.is_dir()]
        except OSError:
            return result
        for year_entry in years:
            if year_entry.name == pb.UNKNOWN_DATE_DIR:
                result.append(root / year_entry.name)
                continue
            if not re.fullmatch(r"\d{4}", year_entry.name):
                continue
            year = int(year_entry.name)
            try:
                months = [entry.name for entry in os.scandir(year_entry.path) if entry.is_dir()]
            except OSError:
                continue
            for name in months:
                if not re.fullmatch(r"\d{2} [A-Za-z]+", name):
                    continue
                key = (year, int(name[:2]))
                if period.date_from and key < (period.date_from.year, period.date_from.month):
                    continue
                if period.date_to and key > (period.date_to.year, period.date_to.month):
                    continue
                result.append(root / year_entry.name / name)
        return result

    def _cleanup_parts(self, period: Period) -> None:
        """Leftovers of an interrupted run are dropped and fetched again."""
        removed = fs.discard_parts_in(self.settings.root / pb.INCOMING_DIR)
        for month in self._month_dirs(period):
            for sub in (pb.FULL_DIR, pb.COMPACT_DIR):
                removed += fs.discard_parts_in(month / sub)
        if removed:
            log.info("Removed %d unfinished temp files", removed)

    def _fetch(self, period: Period) -> None:
        """Pass 2: download while listing, then go back for the files whose link went stale."""
        self._fetch_pass(period, self._listing(period), None)
        for round_number in range(1, FRESH_LINK_ROUNDS + 1):
            with self._report_lock:
                stale, self._stale = self._stale, {}
            if not stale:
                break
            self._last_round = round_number == FRESH_LINK_ROUNDS
            log.info("Download links of %d assets went stale; listing again for fresh ones", len(stale))
            left = dict(stale)
            try:
                self._fetch_pass(period, self._relisted(period, left), stale)
            finally:
                # Not met in the new listing (or the listing broke): say so. After a
                # stop nothing is reported - the next run takes these files anyway.
                if not self._stop.is_set():
                    for asset_id, items in left.items():
                        for item in items:
                            self._fail(asset_id, item.kind, item.label, item.failure, item.has_row)

    def _relisted(self, period: Period, left: dict[str, list[_Stale]]):
        """Assets from `left` as a new listing returns them; stops as soon as all are found."""
        for asset in self._listing(period):
            if left.pop(asset.id, None) is not None:
                yield asset
                if not left:
                    return
            else:
                self._emit("checked")  # the window shows that the job is alive

    def _fetch_pass(self, period: Period, assets, stale: dict[str, list[_Stale]] | None) -> None:
        """Download the assets with a bounded number of them in flight."""
        slots = threading.BoundedSemaphore(self.settings.concurrency * 2)
        pool = ThreadPoolExecutor(self.settings.concurrency, thread_name_prefix="download")

        def work(asset: Asset) -> None:
            try:
                only = None
                if stale is not None and all(item.has_row for item in stale[asset.id]):
                    only = {item.kind for item in stale[asset.id]}
                self._process(asset, period, only)
            except JobStopped:
                pass
            except Exception as error:  # noqa: BLE001 - one bad asset must not end the job
                log.exception("Unexpected failure on %s", asset.filename)
                self._record_error(asset.filename, f"{type(error).__name__}: {error}")
            finally:
                slots.release()

        try:
            for asset in assets:
                self._checkpoint()
                while not slots.acquire(timeout=0.2):
                    self._checkpoint()
                pool.submit(work, asset)
        finally:
            pool.shutdown(wait=True)
        if self._stop.is_set():
            raise JobStopped

    # --------------------------------------------------------- one asset

    def _process(self, asset: Asset, period: Period, only: set[VersionKind] | None = None) -> None:
        """`only` narrows the work to some versions: the others were dealt with in an earlier pass."""
        self._checkpoint()
        plan = self._plan_asset(asset, period)
        if plan is None or plan.in_period is False:
            return
        placed: set[VersionKind] = set()
        if not plan.resolved:
            plan = self._fetch_unresolved(asset, period, placed)
            if plan is None:
                return
        for task in plan.tasks:
            if only is not None and task.kind not in only:
                continue
            self._checkpoint()
            ready = False
            if task.kind in placed:
                ready = True
            elif task.action == ACTION_PRESENT:
                ready = True
                self._count("skipped")
                self._emit("file", path=task.row.rel_path, result="present")
            elif task.action == ACTION_SKIP_DELETED:
                self._count("skipped")
            elif task.action == ACTION_CONFLICT:
                self._record_conflict(task.row.rel_path)
            else:
                ready = self._download_task(asset, task)
            if ready and task.compact_needed and task.compact_target is not None:
                self._submit_compact(asset, task)

    def _mtime(self, asset: Asset) -> float | None:
        return asset.asset_date.timestamp() if asset.asset_date else None

    def _download_task(self, asset: Asset, task: FileTask) -> bool:
        fs.ensure_dir(task.target.parent)
        part = fs.part_path(task.target)
        self._emit("file", path=task.row.rel_path, result="started", size=task.version.size)
        if not self._download_to(asset, task.kind, part, task.version.size, task.row.rel_path, has_row=True):
            return False
        if not fs.publish(part, task.target, self._mtime(asset)):
            fs.discard_part(part)
            self.db.set_status(asset.id, task.kind, STATUS_CONFLICT, strings.REASON_SAME_SIZE_CONFLICT)
            self._record_conflict(task.row.rel_path)
            return False
        self._mark_downloaded(asset, task)
        return True

    def _mark_downloaded(self, asset: Asset, task: FileTask) -> None:
        self.db.set_status(asset.id, task.kind, STATUS_DONE)
        with self._report_lock:
            self._report.downloaded += 1
            self._report.bytes_downloaded += task.version.size
        self._emit("file", path=task.row.rel_path, result="downloaded", size=task.version.size)

    def _fetch_unresolved(self, asset: Asset, period: Period, placed: set[VersionKind]) -> AssetPlan | None:
        """The capture time is only in the file: fetch it into `_incoming`,
        read the time, then either file it into its month or drop the temp copy."""
        version = asset.versions[VersionKind.ORIGINAL]
        incoming = self.settings.root / pb.INCOMING_DIR
        fs.ensure_dir(incoming)
        name = pb.version_filename(asset, VersionKind.ORIGINAL, pb.conflict_tag(asset.id))
        part = fs.part_path(incoming / name)
        self._emit("file", path=asset.filename, result="started", size=version.size)
        if not self._download_to(asset, VersionKind.ORIGINAL, part, version.size, asset.filename, has_row=False):
            return None
        found = cap.from_file(part, asset.media_type, asset, self._local_tz)
        self.db.set_capture(asset.id, found)
        if found.wall is None or not period.contains(found.wall.date()):
            fs.discard_part(part)
            self._count("out_of_period")
            return None
        plan = self._plan_asset(asset, period)
        if plan is None or not plan.resolved or plan.in_period is False:
            fs.discard_part(part)
            return None
        task = next(t for t in plan.tasks if t.kind is VersionKind.ORIGINAL)
        if task.action == ACTION_DOWNLOAD:
            fs.ensure_dir(task.target.parent)
            if fs.publish(part, task.target, self._mtime(asset)):
                self._mark_downloaded(asset, task)
                placed.add(VersionKind.ORIGINAL)
                return plan
            task.action = ACTION_CONFLICT
        fs.discard_part(part)
        return plan

    def _on_bytes(self, count: int) -> None:
        try:
            self._checkpoint()
        except JobStopped:
            raise DownloadCancelled from None
        self._emit("bytes", count=count)

    def _download_to(
        self, asset: Asset, kind: VersionKind, part: Path, expected: int, label: str, has_row: bool
    ) -> bool:
        """Download into a temp file with retries. True when the temp file is
        complete; on failure the temp file is gone and the error is recorded."""
        for attempt in range(1, self._max_attempts + 1):
            self._checkpoint()
            self._check_space()
            failure: str
            retry = False
            stale = False
            try:
                self.client.download(asset, kind, Path(fs.long_path(part)), self._on_bytes)
                got = fs.size_of(part)
                if got != expected:
                    raise _SizeMismatch(got, expected)
                return True
            except DownloadCancelled:
                fs.discard_part(part)
                raise JobStopped from None
            except SessionExpiredError:
                fs.discard_part(part)
                self.stop(strings.STOP_SESSION)
                raise JobStopped from None
            except ICloudError as error:
                failure, retry = error.user_message, error.transient
                stale = isinstance(error, LinkExpiredError) and not self._last_round
                log.warning("Download of %s failed (attempt %d): %s", label, attempt, error)
            except _SizeMismatch as error:
                failure, retry = str(error), True
                log.warning("Download of %s is incomplete (attempt %d)", label, attempt)
            except OSError as error:
                failure = f"{type(error).__name__}: {error.strerror or error}"
                log.error("Cannot write %s: %s", label, error)
            try:
                fs.discard_part(part)
            except OSError:
                pass
            if retry and attempt < self._max_attempts:
                self._wait(self._backoff(attempt))
                continue
            if stale:  # a fresh link is all it needs: put the file aside for the next listing
                with self._report_lock:
                    self._stale.setdefault(asset.id, []).append(_Stale(kind, label, failure, has_row))
                return False
            self._fail(asset.id, kind, label, failure, has_row)
            return False
        return False

    def _fail(self, asset_id: str, kind: VersionKind, label: str, failure: str, has_row: bool) -> None:
        if has_row:
            self.db.set_status(asset_id, kind, STATUS_ERROR, failure)
        self._record_error(label, failure)

    # ------------------------------------------------------------ compact

    def _submit_compact(self, asset: Asset, task: FileTask) -> None:
        pool, slots = self._compact_pool, self._compact_slots
        if pool is None or slots is None or task.compact_target is None:
            return
        while not slots.acquire(timeout=0.2):
            self._checkpoint()
        source, target = task.target, task.compact_target
        asset_id, kind, label, mtime = asset.id, task.kind, task.row.compact_path or "", self._mtime(asset)

        def convert() -> None:
            try:
                if self._stop.is_set():
                    return
                made = make_compact(
                    source, target, self.settings.compact_long_side, self.settings.compact_quality, mtime
                )
                self.db.set_compact_status(asset_id, kind, COMPACT_DONE)
                if made:
                    self._count("compact_made")
            except Exception as error:  # noqa: BLE001 - the original stays; retried on the next run
                message = f"{type(error).__name__}: {error}"
                log.warning("Compact copy failed for %s: %s", label, message)
                self.db.set_compact_status(asset_id, kind, COMPACT_ERROR, message)
                with self._report_lock:
                    self._report.compact_errors.append((label, message))
            finally:
                slots.release()

        try:
            pool.submit(convert)
        except RuntimeError:  # pool already shut down by a stop
            slots.release()

    # ------------------------------------------------------------- report

    def _count(self, name: str) -> None:
        with self._report_lock:
            setattr(self._report, name, getattr(self._report, name) + 1)

    def _record_error(self, label: str, message: str) -> None:
        with self._report_lock:
            self._report.errors.append((label, message))
        self._emit("file", path=label, result="error", message=message)

    def _record_conflict(self, label: str) -> None:
        with self._report_lock:
            self._report.conflicts.append((label, strings.REASON_SAME_SIZE_CONFLICT))
        self._emit("file", path=label, result="conflict", message=strings.REASON_SAME_SIZE_CONFLICT)
