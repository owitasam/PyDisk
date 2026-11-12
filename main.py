"""Compatibility wrapper for running PyDisk Analyzer from a source checkout.

The real implementation lives in :mod:`pydisk.cli`. Installed users get a
``pydisk`` command, while this file keeps ``python main.py ...`` working.
"""

from __future__ import annotations

import sys

from pydisk.cli import main

if __name__ == "__main__":
    sys.exit(main())
