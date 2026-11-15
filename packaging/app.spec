# PyInstaller spec: one-folder build (starts faster and trips antivirus less than one-file).
# Run through build.ps1, or:  pyinstaller packaging/app.spec --noconfirm
# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

ROOT = Path(SPECPATH).parent
APP_NAME = "iCloudPhotoDownloader"

datas = []
datas += collect_data_files("certifi")  # CA bundle for HTTPS to iCloud
datas += collect_data_files("tzdata")  # timezone database used by the iCloud library
datas += copy_metadata("keyring")  # keyring finds its Windows backend through entry points
datas += copy_metadata("icloudpd")

binaries = collect_dynamic_libs("pillow_heif")  # libheif stays a separate DLL (LGPL)

hiddenimports = [
    "keyring.backends.Windows",
    "win32ctypes.core",
    "pillow_heif",
    "PIL.JpegImagePlugin",
    "PIL.PngImagePlugin",
    "PIL.TiffImagePlugin",
]

# Parts of icloudpd and of the standard library that the app never touches.
excludes = [
    "flask",
    "waitress",
    "werkzeug",
    "jinja2",
    "tqdm",
    "keyrings.alt",  # file-based password stores; the app uses Credential Manager only
    "tkinter",  # only the debug console prompt uses it, and the exe has no console
    "icloudpd.base",
    "icloudpd.cli",
    "icloudpd.autodelete",
    "icloudpd.server",
    "pytest",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtSql",
    "PySide6.QtTest",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,  # a windowed app: no console window behind it
    icon=str(ROOT / "packaging" / "icon.ico"),
    version=str(ROOT / "build" / "version_info.txt"),
    upx=False,  # UPX-packed executables are a classic antivirus false positive
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=APP_NAME)
