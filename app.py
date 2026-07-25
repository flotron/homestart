#!/usr/bin/env python3
"""Backward-compatible HomeStart entry point."""

try:
    from homestart.server import main
except ModuleNotFoundError as error:
    if error.name not in {"homestart", "homestart.server"}:
        raise
    # Releases keep this bridge copy under scripts/ so updaters older than
    # 20260725-2500 can install the modular server before they know that the
    # top-level homestart/ directory is an allowed update target.
    from scripts.homestart.server import main


if __name__ == "__main__":
    main()
