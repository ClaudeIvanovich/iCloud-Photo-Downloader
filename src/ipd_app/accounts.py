"""Saved passwords: Windows Credential Manager through `keyring`, nowhere else."""

from __future__ import annotations

from typing import Protocol

from .config import account_id
from .logging_setup import secret_filter

SERVICE_NAME = "iCloudPhotoDownloader"


class PasswordBackend(Protocol):
    def get_password(self, service: str, username: str) -> str | None: ...
    def set_password(self, service: str, username: str, password: str) -> None: ...
    def delete_password(self, service: str, username: str) -> None: ...


def _system_backend() -> PasswordBackend:
    """Windows Credential Manager, explicitly.

    keyring's automatic choice would also consider the `keyrings.alt` backends
    that icloudpd pulls in, and some of those keep passwords in a plain file.
    """
    import sys

    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()  # type: ignore[return-value]
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring

        return Keyring()  # Explicitly exclude plaintext fallback backends.
    import keyring

    return keyring  # type: ignore[return-value]


class PasswordStore:
    """The key is the account id, so the Apple ID itself is not the entry name."""

    def __init__(self, backend: PasswordBackend | None = None) -> None:
        self._backend = backend or _system_backend()

    def get(self, apple_id: str) -> str | None:
        password = self._backend.get_password(SERVICE_NAME, account_id(apple_id))
        secret_filter.add_secret(password)
        return password

    def save(self, apple_id: str, password: str) -> None:
        secret_filter.add_secret(password)
        self._backend.set_password(SERVICE_NAME, account_id(apple_id), password)

    def forget(self, apple_id: str) -> None:
        """Drop the saved password (sign-out / account removal)."""
        try:
            self._backend.delete_password(SERVICE_NAME, account_id(apple_id))
        except Exception:  # noqa: BLE001 - nothing was saved
            pass


class MemoryPasswordBackend:
    """Keeps passwords in memory only. Used by the demo mode and by tests."""

    def __init__(self) -> None:
        self._saved: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._saved.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._saved[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self._saved.pop((service, username), None)


def forget_session(apple_id: str) -> None:
    """Remove the saved iCloud session of an account: its cookie and token files.

    Only files inside the account's own session folder are touched.
    """
    from .config import session_dir

    folder = session_dir(apple_id)
    if not folder.is_dir():
        return
    for entry in folder.iterdir():
        if entry.is_file():
            entry.unlink()
    try:
        folder.rmdir()
    except OSError:
        pass
