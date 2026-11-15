"""Generate build inputs from the source of truth:

  packaging/icon.ico              drawn by ipd_app.ui.icons (no third-party artwork)
  build/version_info.txt          Windows version resource, from ipd_app.__version__

Usage: python packaging/make_assets.py
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

from ipd_app import __version__  # noqa: E402
from ipd_app.ui import icons  # noqa: E402

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)

VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers=({major}, {minor}, {patch}, 0), prodvers=({major}, {minor}, {patch}, 0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', ''),
      StringStruct('FileDescription', 'iCloud Photo Downloader'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'iCloudPhotoDownloader'),
      StringStruct('OriginalFilename', 'iCloudPhotoDownloader.exe'),
      StringStruct('ProductName', 'iCloud Photo Downloader'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def pixmap_to_image(size: int) -> Image.Image:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    icons.render("idle", size).save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    largest = pixmap_to_image(max(ICON_SIZES))
    largest.save(
        HERE / "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in ICON_SIZES],
        append_images=[pixmap_to_image(s) for s in ICON_SIZES[:-1]],
    )
    major, minor, patch = (int(part) for part in __version__.split(".")[:3])
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    (build / "version_info.txt").write_text(
        VERSION_TEMPLATE.format(major=major, minor=minor, patch=patch, version=__version__), encoding="utf-8"
    )
    print(f"icon.ico and version_info.txt written for version {__version__}")
    del app
    return 0


if __name__ == "__main__":
    sys.exit(main())
