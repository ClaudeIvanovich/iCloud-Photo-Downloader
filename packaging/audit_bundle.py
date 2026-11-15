"""Privacy audit of a built program folder, run by build.ps1 before the installer is made.

The installer packs exactly one folder (dist/iCloudPhotoDownloader). This script
fails the build if that folder contains anything that belongs to the person who
built it:

  * their Apple IDs (read from the local config; never printed),
  * their Windows user name, home folder, computer name, git identity,
  * the folder the project was built in,
  * session, config, state or log files, or anything shaped like a credential.

It looks inside the Python archive embedded in the exe as well, in UTF-8 and UTF-16.

Usage: python packaging/audit_bundle.py dist/iCloudPhotoDownloader
"""

from __future__ import annotations

import getpass
import os
import re
import socket
import subprocess
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Files of the app's own data folders. None of them may ever be shipped.
FORBIDDEN_NAMES = re.compile(
    r"(^config\.json$|\.session$|\.sqlite(-wal|-shm)?$|^app\.log(\.\d+)?$|^\.env$|\.pem$|\.key$|\.pfx$|\.p12$|^id_rsa)",
    re.IGNORECASE,
)
# The public CA bundle of the `certifi` package: certificates, no keys, same for everyone.
ALLOWED_FILES = {"_internal/certifi/cacert.pem"}
# Shapes of real credentials: an actual key body or cookie value, not the marker
# strings that libraries keep in their code to recognise such files.
SECRET_SHAPES = {
    "private key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----\s+[A-Za-z0-9+/=\r\n]{200,}-----END"),
    "Apple session cookie": re.compile(rb"X-APPLE-WEBAUTH-(?:TOKEN|USER|HSA-TRUST)=\"?v=\d"),
    "saved cookie jar": re.compile(rb"#LWP-Cookies-\d\.\d\s+Set-Cookie3:"),
    "saved session tokens": re.compile(rb"\"(?:session_token|trust_token)\"\s*:\s*\"[A-Za-z0-9+/=_-]{20,}\""),
}
MIN_NEEDLE = 4


def personal_needles() -> dict[str, str]:
    """label -> string that must not appear. Labels are safe to print, values are not."""
    needles: dict[str, str] = {}

    def add(label: str, value: str | None) -> None:
        if value and len(value.strip()) >= MIN_NEEDLE:
            needles[label] = value.strip()

    add("Windows user name", getpass.getuser())
    add("home folder", str(Path.home()))
    add("computer name", socket.gethostname())
    add("build folder", str(ROOT))
    for key in ("user.email", "user.name"):
        try:
            value = subprocess.run(
                ["git", "-C", str(ROOT), "config", key], capture_output=True, text=True, timeout=10
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            value = ""
        add(f"git {key}", value)
    try:
        saved = os.environ.pop("IPD_APPDATA", None)  # the builder's real config, not a test one
        from ipd_app import config

        for number, account in enumerate(config.load_config().accounts.values(), 1):
            add(f"Apple ID #{number}", account.apple_id)
            add(f"Apple ID #{number} (name part)", account.apple_id.split("@")[0])
            add(f"download folder of account #{number}", account.root_dir)
            add(f"account id #{number}", config.account_id(account.apple_id))
        if saved is not None:
            os.environ["IPD_APPDATA"] = saved
    except Exception as error:  # noqa: BLE001 - the audit must not pass silently on a broken config
        print(f"WARNING: could not read the local config for Apple IDs: {type(error).__name__}")
    return needles


def encodings(value: str) -> list[bytes]:
    variants = {value, value.replace("\\", "/"), value.replace("\\", "\\\\")}
    result = []
    for variant in variants:
        lowered = variant.lower()
        result.append(lowered.encode("utf-8"))
        result.append(lowered.encode("utf-16-le"))
    return result


def embedded_archive_members(exe: Path):
    """(name, bytes) of every module inside the exe's Python archive."""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    archive = CArchiveReader(str(exe))
    for name in archive.toc:
        data = archive.extract(name)
        yield f"{exe.name}!{name}", data
        if name.lower().endswith(".pyz"):
            temp = exe.parent / "_audit_temp.pyz"
            temp.write_bytes(data)
            try:
                pyz = ZlibArchiveReader(str(temp))
                for module in pyz.toc:
                    try:
                        yield f"{exe.name}!{name}!{module}", pyz.extract(module, raw=True) or b""
                    except (zlib.error, TypeError, ValueError):
                        continue
            finally:
                temp.unlink()


def audit(folder: Path) -> list[str]:
    needles = personal_needles()
    patterns = {label: encodings(value) for label, value in needles.items()}
    problems: list[str] = []
    scanned = 0

    def scan(where: str, data: bytes) -> None:
        nonlocal scanned
        scanned += 1
        lowered = data.lower()
        for label, variants in patterns.items():
            if any(variant in lowered for variant in variants):
                problems.append(f"{label} found in {where}")
        for label, shape in SECRET_SHAPES.items():
            if shape.search(data):
                problems.append(f"{label} found in {where}")

    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder).as_posix()
        scan(f"name of {relative}", relative.encode("utf-8"))
        if not path.is_file():
            continue
        if FORBIDDEN_NAMES.search(path.name) and relative not in ALLOWED_FILES:
            problems.append(f"forbidden data file: {relative}")
        scan(relative, path.read_bytes())
        if path.suffix.lower() == ".exe":
            try:
                for name, data in embedded_archive_members(path):
                    scan(name, data)
            except Exception as error:  # noqa: BLE001
                problems.append(f"could not open the archive inside {relative}: {type(error).__name__}: {error}")
    print(f"Privacy audit: {scanned} items scanned for {len(needles)} personal strings and {len(SECRET_SHAPES)} secret shapes")
    print("Checked for: " + ", ".join(sorted(needles)))
    return problems


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    folder = Path(sys.argv[1]).resolve()
    if not folder.is_dir():
        print(f"ERROR: no such folder: {folder}")
        return 2
    problems = audit(folder)
    if problems:
        print(f"AUDIT FAILED: {len(problems)} problem(s). The installer must not be built from this folder.")
        for line in sorted(set(problems))[:60]:
            print("  " + line)
        return 1
    print("AUDIT PASSED: nothing personal in the program folder")
    return 0


if __name__ == "__main__":
    sys.exit(main())
