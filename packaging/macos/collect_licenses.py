"""Collect license notices supplied in installed wheels, without local settings."""
import re
import shutil
import sys
from importlib.metadata import distributions
from pathlib import Path

destination = Path(sys.argv[1])
destination.mkdir(parents=True, exist_ok=True)
for dist in distributions():
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", dist.metadata["Name"])
    for file in dist.files or ():
        text = str(file)
        if ".dist-info/" not in text or not re.search(r"(?:license|copying)", file.name, re.IGNORECASE):
            continue
        source = Path(dist.locate_file(file))
        if source.is_file():
            folder = destination / name
            folder.mkdir(exist_ok=True)
            shutil.copy2(source, folder / file.name)
