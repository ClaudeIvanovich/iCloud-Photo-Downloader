"""The privacy audit that guards the installer: it must catch what it is there to catch."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("audit_bundle", REPO / "packaging" / "audit_bundle.py")
audit_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_bundle)

NEEDLES = {
    "Apple ID #1": "alex.tester@icloud.com",
    "Windows user name": "alexpc",
    "home folder": r"C:\Users\alexpc",
}


@pytest.fixture
def bundle(tmp_path, monkeypatch) -> Path:
    monkeypatch.setattr(audit_bundle, "personal_needles", lambda: dict(NEEDLES))
    folder = tmp_path / "iCloudPhotoDownloader"
    (folder / "_internal" / "certifi").mkdir(parents=True)
    (folder / "_internal" / "certifi" / "cacert.pem").write_text("-----BEGIN CERTIFICATE-----\nMIIB\n")
    (folder / "_internal" / "lib.dll").write_bytes(b"\x00binary -----BEGIN PRIVATE KEY----- marker in code\x00")
    (folder / "_internal" / "cookiejar.pyc").write_bytes(b'magic = "#LWP-Cookies-2.0"; session_token = None')
    return folder


def test_clean_bundle_passes(bundle) -> None:
    assert audit_bundle.audit(bundle) == []


@pytest.mark.parametrize(
    ("name", "content", "expected"),
    [
        ("notes.txt", b"built by Alex.Tester@iCloud.com", "Apple ID #1"),
        ("module.pyc", "C:\\Users\\alexpc\\project\\x.py".encode("utf-16-le"), "home folder"),
        ("module2.pyc", b"co_filename C:/Users/alexpc/project/x.py", "home folder"),
        ("config.json", json.dumps({"accounts": {}}).encode(), "forbidden data file"),
        ("abc.session", b"{}", "forbidden data file"),
        ("state.sqlite", b"SQLite format 3", "forbidden data file"),
        ("app.log", b"INFO started", "forbidden data file"),
        ("jar.txt", b"#LWP-Cookies-2.0\nSet-Cookie3: X-APPLE-WEBAUTH-USER=\"v=1:s=0:d=1\"; path=/", "cookie"),
        ("s.txt", b'{"session_token": "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/=="}', "saved session tokens"),
        ("k.txt", b"-----BEGIN RSA PRIVATE KEY-----\n" + b"QUJD" * 80 + b"\n-----END RSA PRIVATE KEY-----", "private key"),
    ],
)
def test_planted_personal_data_is_caught(bundle, name, content, expected) -> None:
    (bundle / "_internal" / name).write_bytes(content)
    problems = audit_bundle.audit(bundle)
    assert problems and any(expected in line for line in problems), problems
    assert all("alex" not in line.lower() or name in line for line in problems)  # values are never printed


def test_personal_string_in_a_file_name_is_caught(bundle) -> None:
    (bundle / "alexpc-notes").mkdir()
    assert any("Windows user name" in line for line in audit_bundle.audit(bundle))


def test_exit_code_blocks_the_build(bundle, monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["audit_bundle.py", str(bundle)])
    assert audit_bundle.main() == 0
    (bundle / "leak.txt").write_bytes(b"alexpc")
    assert audit_bundle.main() == 1
    out = capsys.readouterr().out
    assert "AUDIT FAILED" in out and "alexpc" not in out.replace("leak.txt", "")
