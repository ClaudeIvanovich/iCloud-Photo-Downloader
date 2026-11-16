"""Exercise the native bridge with an isolated, entirely fake iCloud library."""
import json
import os
import queue
import subprocess
import sys
import threading
import time

import pytest

from ipd_app import strings
from ipd_app.macos_bridge import localized
from ipd_app.sync_engine import fs


def test_localized_engine_errors_keep_dynamic_values():
    message = strings.ERR_ROOT_UNAVAILABLE.format(path="/tmp/photos")
    assert localized(message)["en"] == "The folder /tmp/photos is unavailable. Check the disk or network connection."
    assert localized(strings.ERR_BAD_CREDENTIALS)["ru"] == strings.ERR_BAD_CREDENTIALS


def test_publish_does_not_replace_even_if_existence_check_races(tmp_path, monkeypatch):
    target = tmp_path / "photo.jpg"
    partial = tmp_path / "photo.jpg.part"
    target.write_bytes(b"existing photo")
    partial.write_bytes(b"new photo")
    monkeypatch.setattr(fs, "exists", lambda _: False)
    assert fs.publish(partial, target) is False
    assert target.read_bytes() == b"existing photo"
    assert partial.read_bytes() == b"new photo"


def test_bridge_demo_login_preview_download_and_repeat(tmp_path):
    env = dict(os.environ, IPD_DEMO_APPDATA=str(tmp_path / "appdata"), IPD_DEMO_2FA="123456")
    binary = os.environ.get("IPD_BRIDGE_PROGRAM")
    invocation = [binary, "--fake", "4"] if binary else [sys.executable, "-m", "ipd_app.macos_bridge", "--fake", "4"]
    proc = subprocess.Popen(invocation,
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, bufsize=1, env=env)
    events = queue.Queue()
    def read():
        for line in proc.stdout:
            events.put(json.loads(line))
    threading.Thread(target=read, daemon=True).start()
    def send(action, **values):
        proc.stdin.write(json.dumps({"action": action, **values}) + "\n")
        proc.stdin.flush()
    def wait(event, predicate=lambda x: True):
        end = time.monotonic() + 25
        while time.monotonic() < end:
            try:
                item = events.get(timeout=max(.01, end - time.monotonic()))
            except queue.Empty:
                break
            if item.get("event") == event and predicate(item):
                return item
        pytest.fail(f"Timed out waiting for {event}; process exit: {proc.poll()}")
    try:
        wait("ready")
        send("login", apple_id="demo@example.invalid", password="wrong")
        assert wait("login")["message"]["en"] == "Incorrect Apple ID or password."
        send("login", apple_id="demo@example.invalid", password="secret")
        assert wait("login")["status"] == "needs_2fa"
        send("code", code="111111")
        assert wait("login")["message"]["en"] == "The verification code was not accepted."
        send("code", code="123456")
        assert wait("login")["status"] == "ok"
        output = tmp_path / "photos"
        output.mkdir()
        send("settings", values={"root_dir": str(output), "min_free_gb": 0})
        wait("accounts", lambda item: item["accounts"] and item["accounts"][0]["root_dir"] == str(output))
        send("preview")
        assert wait("count_progress", lambda item: item["scanned"] == 4)["scanned"] == 4
        assert wait("plan")["plan"]["files_to_download"] > 0
        wait("job_state", lambda item: item["state"] == "idle")
        assert not list(output.rglob("*.JPG"))
        send("start")
        first = wait("finished")["report"]
        assert first["downloaded"] > 0 and not first["errors"]
        original = next(output.rglob("*.JPG"))
        contents = original.read_bytes()
        send("start")
        second = wait("finished")["report"]
        assert second["downloaded"] == 0
        assert original.read_bytes() == contents
    finally:
        if proc.poll() is None:
            send("quit")
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
