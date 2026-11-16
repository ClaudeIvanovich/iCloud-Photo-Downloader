from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

ROOT = Path(SPECPATH).parent.parent
datas = collect_data_files("certifi") + collect_data_files("tzdata") + copy_metadata("keyring") + copy_metadata("icloudpd")
binaries = collect_dynamic_libs("pillow_heif")
a = Analysis(
    [str(ROOT / "packaging/macos/launcher.py")], pathex=[str(ROOT / "src")],
    datas=datas, binaries=binaries,
    hiddenimports=["keyring.backends.macOS", "pillow_heif", "PIL.JpegImagePlugin", "PIL.PngImagePlugin", "PIL.TiffImagePlugin", "pyicloud_ipd"],
    excludes=["keyrings.alt", "pytest", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWidgets", "PySide6.QtSql", "PySide6.QtTest"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ipd-bridge", console=True, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ipd-bridge")
