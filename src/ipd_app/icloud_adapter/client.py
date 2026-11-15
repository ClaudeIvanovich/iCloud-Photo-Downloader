"""The only interface the rest of the app uses to talk to iCloud.

Read-only by design: there is no method that changes or removes anything in
iCloud, and none may be added (REQUIREMENTS.md, sections 5 and 11).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable, Iterator

from .models import Album, Asset, AssetFilter, LoginResult, VersionKind

ProgressCallback = Callable[[int], None]  # called with the number of bytes just written


class ICloudClient(ABC):
    @abstractmethod
    def login(self, apple_id: str, password: str | None) -> LoginResult:
        """Sign in. With password=None only a saved session is tried."""

    @abstractmethod
    def submit_2fa_code(self, code: str) -> LoginResult:
        """Finish sign-in with a code shown on a trusted device."""

    @abstractmethod
    def request_sms_code(self, phone_id: int) -> None:
        """Ask Apple to send the code by SMS to one of LoginResult.phones."""

    @abstractmethod
    def submit_sms_code(self, phone_id: int, code: str) -> LoginResult:
        """Finish sign-in with a code received by SMS."""

    @abstractmethod
    def is_session_valid(self) -> bool:
        """True when requests can be made without asking the user for anything."""

    @abstractmethod
    def list_albums(self) -> list[Album]:
        """Albums of the personal library. Never includes Hidden, Recently Deleted,
        shared albums or the shared library."""

    @abstractmethod
    def count_assets(self, asset_filter: AssetFilter) -> int | None:
        """Cheap size hint for progress display; None when unknown."""

    @abstractmethod
    def iter_assets(self, asset_filter: AssetFilter) -> Iterator[Asset]:
        """Stream assets page by page, ordered by capture date. The direction is
        the server's choice (real iCloud lists the newest first); callers must
        not rely on it."""

    @abstractmethod
    def download(
        self,
        asset: Asset,
        version: VersionKind,
        dest_path: Path,
        progress_cb: ProgressCallback | None = None,
    ) -> None:
        """Write one version of an asset to dest_path (overwriting it).

        The caller owns naming, temp files and verification. progress_cb may raise
        DownloadCancelled to abort.
        """
