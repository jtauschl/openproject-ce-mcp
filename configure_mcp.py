#!/usr/bin/env python3
# Thin compatibility shim. The interactive setup now lives in the package at
# src/openproject_ce_mcp/setup_cli.py so it can ship as the installed console
# command `openproject-ce-mcp configure` (and the `openproject-ce-mcp-setup`
# alias). This file stays so the source-checkout launchers — get.sh / get.ps1 /
# uninstall.sh / uninstall.ps1, which run `python3 configure_mcp.py [args]` —
# keep working without the package being installed.
#
# It puts src/ on sys.path and forwards argv to main(). Any other attribute
# (`from configure_mcp import <name>`) is delegated lazily to setup_cli via
# __getattr__, so we don't bulk-copy setup_cli's imported stdlib modules into this
# namespace, and a renamed/removed symbol raises a clear AttributeError here rather
# than silently vanishing.
"""Run the interactive setup from a source checkout: python3 configure_mcp.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from openproject_ce_mcp import setup_cli as _setup_cli  # noqa: E402

main = _setup_cli.main


def __getattr__(name: str):
    # PEP 562 module-level attribute hook: delegate to setup_cli on demand.
    try:
        return getattr(_setup_cli, name)
    except AttributeError:
        raise AttributeError(f"module 'configure_mcp' has no attribute {name!r}") from None


if __name__ == "__main__":
    main()
