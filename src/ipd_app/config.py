"""Application folders and config.json (versioned, migrated on load).

  %APPDATA%\\iCloudPhotoDownloader\\config.json
  %APPDATA%\\iCloudPhotoDownloader\\sessions\\<account_id>\\   iCloud session files
  %APPDATA%\\iCloudPhotoDownloader\\state\\<account_id>.sqlite  sync state
  %LOCALAPPDATA%\\iCloudPhotoDownloader\\logs\\

Passwords are never stored here; see accounts.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .sync_engine.filters import SyncSettings

APP_DIR_NAME = "iCloudPhotoDownloader"
CONFIG_VERSION = 1
GIB = 1024**3


def app_data_dir() -> Path:
    """Roaming data. IPD_APPDATA overrides it (tests, portable runs)."""
    override = os.environ.get("IPD_APPDATA")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / APP_DIR_NAME


def log_dir() -> Path:
    override = os.environ.get("IPD_APPDATA")
    if override:
        return Path(override) / "logs"
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "state")
    return Path(base) / APP_DIR_NAME / "logs"


def account_id(apple_id: str) -> str:
    """Stable folder-safe id of an Apple ID; keeps the address out of folder names."""
    return hashlib.sha256(apple_id.strip().lower().encode("utf-8")).hexdigest()[:16]


def session_dir(apple_id: str) -> Path:
    return app_data_dir() / "sessions" / account_id(apple_id)


def state_db_path(apple_id: str) -> Path:
    return app_data_dir() / "state" / f"{account_id(apple_id)}.sqlite"


@dataclass
class AccountConfig:
    apple_id: str
    root_dir: str = ""
    photos: bool = True
    videos: bool = True
    albums: list[str] | None = None
    live_video: bool = True
    edited: bool = False
    compact_enabled: bool = True
    compact_long_side: int | None = 2048
    compact_quality: int = 85
    concurrency: int = 3
    min_free_gb: float = 5.0
    restore_deleted: bool = True

    def to_settings(self) -> SyncSettings:
        return SyncSettings(
            root=Path(self.root_dir),
            photos=self.photos,
            videos=self.videos,
            album_ids=tuple(self.albums) if self.albums else None,
            live_video=self.live_video,
            edited=self.edited,
            compact_enabled=self.compact_enabled,
            compact_long_side=self.compact_long_side,
            compact_quality=self.compact_quality,
            concurrency=self.concurrency,
            min_free_bytes=int(self.min_free_gb * GIB),
            restore_deleted=self.restore_deleted,
        )


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    active_account: str | None = None  # account id
    language: str = "auto"  # "auto" (as in Windows) or a key of strings.LANGUAGES
    accounts: dict[str, AccountConfig] = field(default_factory=dict)

    def account(self, apple_id: str) -> AccountConfig | None:
        return self.accounts.get(account_id(apple_id))

    def ensure_account(self, apple_id: str) -> AccountConfig:
        key = account_id(apple_id)
        if key not in self.accounts:
            self.accounts[key] = AccountConfig(apple_id=apple_id.strip())
        if self.active_account is None:
            self.active_account = key
        return self.accounts[key]

    def drop_account(self, apple_id: str) -> None:
        key = account_id(apple_id)
        self.accounts.pop(key, None)
        if self.active_account == key:
            self.active_account = next(iter(self.accounts), None)

    def shared_roots(self, apple_id: str) -> list[str]:
        """Apple IDs of other accounts that point at the same root folder."""
        mine = self.account(apple_id)
        if mine is None or not mine.root_dir:
            return []
        own = os.path.normcase(os.path.abspath(mine.root_dir))
        return [
            other.apple_id
            for key, other in self.accounts.items()
            if key != account_id(apple_id)
            and other.root_dir
            and os.path.normcase(os.path.abspath(other.root_dir)) == own
        ]


# Each entry upgrades a raw config dict from version N to N + 1.
_MIGRATIONS: dict[int, Any] = {
    0: lambda data: {**data, "version": 1, "accounts": data.get("accounts", {})},
}


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    version = int(data.get("version", 0))
    while version < CONFIG_VERSION:
        data = _MIGRATIONS[version](data)
        version = int(data["version"])
    return data


def _account_from(raw: dict[str, Any]) -> AccountConfig:
    known = {f.name for f in fields(AccountConfig)}
    return AccountConfig(**{key: value for key, value in raw.items() if key in known})


def load_config(path: Path | None = None) -> AppConfig:
    path = path or app_data_dir() / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return AppConfig()
    data = migrate(data)
    accounts = {key: _account_from(raw) for key, raw in data.get("accounts", {}).items() if "apple_id" in raw}
    return AppConfig(
        version=CONFIG_VERSION,
        active_account=data.get("active_account"),
        language=str(data.get("language") or "auto"),
        accounts=accounts,
    )


def save_config(config: AppConfig, path: Path | None = None) -> None:
    """Atomic write: temp file, then replace (retried if another process holds it)."""
    path = path or app_data_dir() / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CONFIG_VERSION,
        "active_account": config.active_account,
        "language": config.language,
        "accounts": {key: asdict(account) for key, account in config.accounts.items()},
    }
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)
