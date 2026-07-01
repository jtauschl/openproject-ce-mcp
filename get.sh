#!/usr/bin/env sh
# One-liner installer for openproject-mcp.
# Usage: curl -fsSL https://raw.githubusercontent.com/jtauschl/openproject-mcp/main/get.sh | sh
#
# Clones the repo to ~/openproject-mcp (override with DIR=…),
# then runs the interactive setup.
set -e

REPO="https://github.com/jtauschl/openproject-mcp.git"
DEST="${DIR:-$HOME/openproject-mcp}"

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

# ── run setup ─────────────────────────────────────────────────────────────────
cd "$DEST"
exec "$PYTHON_BIN" configure_mcp.py
