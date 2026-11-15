"""Entry point of the packaged application. Kept tiny: everything lives in ipd_app."""

import sys

from ipd_app.cli import main

if __name__ == "__main__":
    sys.exit(main())
