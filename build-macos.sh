#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
    printf '%s\n' 'Build on an Apple Silicon Mac.' >&2; exit 1
fi
PYTHON="${IPD_PYTHON:-python3.12}"
"$PYTHON" -m venv --clear .venv-macos
.venv-macos/bin/python -m pip install -r requirements-dev.txt -e .
.venv-macos/bin/python -m pytest -q
.venv-macos/bin/pyinstaller --noconfirm --clean packaging/macos/bridge.spec
APP="${IPD_MACOS_APP:-dist/iCloud Photo Downloader.app}"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp packaging/macos/Info.plist "$APP/Contents/Info.plist"
.venv-macos/bin/python packaging/macos/make_icon.py "$APP/Contents/Resources/AppIcon.icns"
rm -rf "$APP/Contents/Resources/engine"
cp -R dist/ipd-bridge "$APP/Contents/Resources/engine"
mkdir -p "$APP/Contents/Resources/Licenses"
cp LICENSE "$APP/Contents/Resources/Licenses/PROJECT-LICENSE"
cp packaging/macos/licenses/* "$APP/Contents/Resources/Licenses/"
.venv-macos/bin/python packaging/macos/collect_licenses.py "$APP/Contents/Resources/Licenses"
xcrun swiftc -swift-version 5 -target arm64-apple-macosx13.0 -parse-as-library macos/Sources/App.swift -o "$APP/Contents/MacOS/iCloudPhotoDownloader"
.venv-macos/bin/python packaging/macos/check_minos.py "$APP"
"$APP/Contents/Resources/engine/ipd-bridge" --self-check
APP_DIR="$(cd "$APP" && pwd -P)"
IPD_BRIDGE_PROGRAM="$APP_DIR/Contents/Resources/engine/ipd-bridge" .venv-macos/bin/python -m pytest -q tests/test_macos_bridge.py
.venv-macos/bin/python packaging/audit_bundle.py "$APP/Contents/Resources/engine"
# Ad-hoc signing is for local execution, not Developer ID distribution.
codesign --force --deep --sign - "$APP"
printf '\nBuilt: %s\n' "$APP"
