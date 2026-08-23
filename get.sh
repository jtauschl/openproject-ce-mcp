#!/usr/bin/env sh
# One-liner installer for openproject-ce-mcp.
# Usage: curl -fsSL https://raw.githubusercontent.com/jtauschl/openproject-ce-mcp/main/get.sh | sh
#
# Clones the repo to ~/openproject-ce-mcp (override with DIR=…),
# then runs the interactive setup.
set -e

REPO="https://github.com/jtauschl/openproject-ce-mcp.git"
DEST="${DIR:-$HOME/openproject-ce-mcp}"

# ── check git ─────────────────────────────────────────────────────────────────
if ! command -v git >/dev/null 2>&1; then
    echo "git is required. Install from https://git-scm.com" >&2
    exit 1
fi

# ── check Python 3.10+ ────────────────────────────────────────────────────────
PYTHON_BIN=""
for p in python3 python; do
    if command -v "$p" >/dev/null 2>&1; then
        if "$p" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            PYTHON_BIN="$p"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "Python 3.10 or later is required." >&2
    echo "macOS: brew install python3 | Windows: https://python.org" >&2
    exit 1
fi

# ── clone or update ───────────────────────────────────────────────────────────
if [ -d "$DEST/.git" ]; then
    echo "Updating existing install at $DEST …"
    git -C "$DEST" pull --ff-only
else
    echo "Cloning into $DEST …"
    git clone "$REPO" "$DEST"
fi

# ── verify checkout ───────────────────────────────────────────────────────────
# Guard against a stale or partial DEST left by an interrupted clone/pull.
if [ ! -f "$DEST/configure_mcp.py" ]; then
    echo "Setup script not found at $DEST/configure_mcp.py." >&2
    echo "The checkout at $DEST looks incomplete. Remove it and re-run:" >&2
    echo "  rm -rf \"$DEST\"" >&2
    exit 1
fi

# ── install dependencies ────────────────────────────────────────────────────────
# configure_mcp.py runs against src/ directly (no package install), so it needs
# this checkout's own dependencies (httpx, etc.) on the interpreter it's run
# with -- the bare $PYTHON_BIN found above has neither. uninstall.sh already
# expects and removes a .venv here, so create one via `uv sync` if uv is
# available (matching the rest of this project's tooling, and installing from
# the committed uv.lock rather than re-resolving against pyproject.toml's
# version ranges), falling back to a plain venv + pip install otherwise.
# --no-dev skips the dev-only extras (ruff, pytest, mypy) this end-user setup
# doesn't need. The uv branch is not guarded by a fallback-on-failure: a real
# `uv sync` failure (network, lockfile) should stop the script with its own
# error, not silently fall through to the pip path and mask it -- only uv's
# absence should trigger the fallback.
cd "$DEST"
if command -v uv >/dev/null 2>&1; then
    echo "Installing dependencies with uv …"
    uv sync --no-dev
    PYTHON_BIN="uv"
    set -- run python configure_mcp.py
else
    echo "Installing dependencies with venv + pip …"
    "$PYTHON_BIN" -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -e .
    PYTHON_BIN=".venv/bin/python"
    set -- configure_mcp.py
fi

# ── run setup ─────────────────────────────────────────────────────────────────
# When invoked as `curl … | sh`, this script's stdin is the pipe, not the
# terminal, so the interactive setup would get EOF on the first prompt. Attach
# the controlling terminal (/dev/tty) if there is one; otherwise the setup falls
# back to defaults on its own.
if [ -e /dev/tty ] && [ -r /dev/tty ]; then
    exec "$PYTHON_BIN" "$@" </dev/tty
else
    exec "$PYTHON_BIN" "$@"
fi
