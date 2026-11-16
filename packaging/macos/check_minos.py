"""Fail a build if any Mach-O bundled for macOS requires a newer system."""
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
limit = (13, 0)
magic = {b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf"}
errors = []
for path in root.rglob("*"):
    if not path.is_file() or path.is_symlink():
        continue
    with path.open("rb") as stream:
        if stream.read(4) not in magic:
            continue
    result = subprocess.run(["xcrun", "vtool", "-show-build", str(path)], check=False, text=True, capture_output=True)
    versions = re.findall(r"\bminos\s+(\d+)\.(\d+)", result.stdout)
    if not versions:
        # Older binaries can use LC_VERSION_MIN_MACOSX rather than LC_BUILD_VERSION.
        versions = re.findall(r"\bversion\s+(\d+)\.(\d+)", result.stdout) if "LC_VERSION_MIN_MACOSX" in result.stdout else []
    if not versions:
        errors.append(f"Cannot determine minimum macOS: {path}")
    elif any(tuple(map(int, version)) > limit for version in versions):
        errors.append(f"Requires macOS {'.'.join(max(versions, key=lambda v: tuple(map(int, v))))}: {path}")
if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print(f"Verified macOS 13 minimum for bundled Mach-O files in {root}.")
