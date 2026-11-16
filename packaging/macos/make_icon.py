"""Build a macOS icon from the application's shared, original vector artwork."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Rendering does not need to open a window or change focus.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtGui import QGuiApplication

from ipd_app.ui.icons import render


def main() -> int:
    destination = Path(sys.argv[1])
    destination.parent.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication.instance() or QGuiApplication([])
    with tempfile.TemporaryDirectory(prefix="ipd-icon-") as temporary:
        iconset = Path(temporary) / "AppIcon.iconset"
        iconset.mkdir()
        for logical_size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                suffix = "@2x" if scale == 2 else ""
                path = iconset / f"icon_{logical_size}x{logical_size}{suffix}.png"
                if not render("idle", logical_size * scale).save(str(path), "PNG"):
                    raise RuntimeError(f"Could not render {path.name}")
        subprocess.run(["iconutil", "-c", "icns", "-o", str(destination), str(iconset)], check=True)
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
