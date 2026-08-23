# One-liner installer for openproject-ce-mcp (Windows PowerShell).
# Usage: irm https://raw.githubusercontent.com/jtauschl/openproject-ce-mcp/main/get.ps1 | iex
#
# Clones the repo to %USERPROFILE%\openproject-ce-mcp (override: $env:DIR),
# installs its dependencies, then runs the interactive setup.
#
# Everything runs inside Main and reports failure via a $script:ExitCode
# variable, never `exit` -- `exit` inside a script block executed through
# `iex` (as this one is, per the usage line above) terminates the ENCLOSING
# PowerShell host process, not just this script, silently closing the user's
# terminal window on any error path with no chance to read the message that
# was just printed. Every native command this function runs (git, uv, pip,
# python) writes to PowerShell's own output stream when its result isn't
# captured -- assigning Main's own call site (`$ExitCode = Main`) would
# collect ALL of that output into one array instead of just the intended
# integer, corrupting the exit-code check below. Using a $script:-scoped
# variable instead of `return` sidesteps that entirely: Main is called
# without capturing its return value at all, so every native command's
# output streams straight to the console as the user expects, and the exit
# code travels out through the variable instead of the pipeline.
function Main {
    $ErrorActionPreference = "Stop"

    $Repo = "https://github.com/jtauschl/openproject-ce-mcp.git"
    $Dest = if ($env:DIR) { $env:DIR } else { Join-Path $env:USERPROFILE "openproject-ce-mcp" }

    # ── check git ─────────────────────────────────────────────────────────────
    if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) {
        Write-Error "git is required. Install from https://git-scm.com or via winget: winget install Git.Git"
        $script:ExitCode = 1
        return
    }

    # ── check Python 3.10+ ───────────────────────────────────────────────────
    # A fresh Windows install's PATH resolves `python`/`python3`/`py` to the
    # built-in Microsoft Store app-execution-alias stub when no real Python is
    # installed -- Get-Command finds it (it's a real file), but running it
    # exits non-zero and writes to stderr instead of executing any code. With
    # $ErrorActionPreference = "Stop" (set above), that non-zero exit from a
    # native executable raises a terminating NativeCommandError that skips
    # past `2>$null` entirely (that redirect only silences the process's own
    # stderr stream, not PowerShell's own error-record handling of the
    # failure) -- untrapped, that aborts this whole function instead of
    # falling through to the "Python 3.10 or later is required" message
    # below. Wrap every native Python probe in try/catch so a stub (or any
    # other non-zero exit) is treated as "not usable" and detection
    # continues, not a fatal error.
    $Python = $null
    $PyArgs = @()

    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        try {
            if ((py -3 -c "import sys; print(sys.version_info >= (3, 10))" 2>$null) -eq "True") {
                $Python = "py"; $PyArgs = @("-3")
            }
        } catch {}
    }
    if (-not $Python) {
        foreach ($p in @("python", "python3")) {
            if (Get-Command $p -ErrorAction SilentlyContinue) {
                try {
                    if ((& $p -c "import sys; print(sys.version_info >= (3, 10))" 2>$null) -eq "True") {
                        $Python = $p; break
                    }
                } catch {}
            }
        }
    }
    if (-not $Python) {
        Write-Error "Python 3.10 or later is required. Install from https://python.org or via winget: winget install Python.Python.3.13"
        $script:ExitCode = 1
        return
    }

    # ── clone or update ──────────────────────────────────────────────────────
    if (Test-Path (Join-Path $Dest ".git")) {
        Write-Host "Updating existing install at $Dest ..."
        git -C $Dest pull --ff-only
    } else {
        Write-Host "Cloning into $Dest ..."
        git clone $Repo $Dest
    }

    # ── verify checkout ──────────────────────────────────────────────────────
    # Guard against a stale or partial Dest left by an interrupted clone/pull.
    if (-not (Test-Path (Join-Path $Dest "configure_mcp.py"))) {
        Write-Error "Setup script not found at $Dest\configure_mcp.py. The checkout looks incomplete. Remove it and re-run: Remove-Item -Recurse -Force `"$Dest`""
        $script:ExitCode = 1
        return
    }

    # ── install dependencies ─────────────────────────────────────────────────
    # configure_mcp.py runs against src/ directly (no package install), so it
    # needs this checkout's own dependencies (httpx, etc.) on the interpreter
    # it's run with -- neither the bare `py`/`python` from the check above nor
    # a fresh clone provide those. uninstall.ps1 already expects and removes a
    # .venv here, so create one via `uv sync` if uv is available (matching the
    # rest of this project's tooling, and installing from the committed
    # uv.lock rather than re-resolving against pyproject.toml's version
    # ranges), falling back to a plain venv + pip install otherwise. --no-dev
    # skips the dev-only extras (ruff, pytest, mypy) this end-user setup
    # doesn't need. The uv branch is NOT wrapped in try/catch: a real `uv
    # sync` failure (network, lockfile) should stop the script with its own
    # error, not silently fall through to the pip path and mask it -- only
    # uv's absence should trigger the fallback.
    Set-Location $Dest
    if (Get-Command "uv" -ErrorAction SilentlyContinue) {
        Write-Host "Installing dependencies with uv ..."
        uv sync --no-dev
        $Python = "uv"; $PyArgs = @("run", "python")
    } else {
        Write-Host "Installing dependencies with venv + pip ..."
        & $Python @PyArgs -m venv .venv
        & ".venv\Scripts\python.exe" -m pip install --upgrade pip
        & ".venv\Scripts\python.exe" -m pip install -e .
        $Python = ".venv\Scripts\python.exe"; $PyArgs = @()
    }

    # ── run setup ─────────────────────────────────────────────────────────────
    & $Python @PyArgs configure_mcp.py
    $script:ExitCode = $LASTEXITCODE
}

# $MyInvocation.InvocationName is empty when this script runs inline via
# `iex` (the documented usage) and set to the script's own path when it runs
# as a file (`pwsh -File get.ps1`, or a test harness) -- only in the latter
# case is `exit` safe: it terminates just this script's own process, since
# there's no enclosing interactive host session to accidentally take down
# with it (see Main's own docstring above for why `exit` is never called
# from inside Main itself).
$IsFileExecution = [bool]$MyInvocation.InvocationName

$ExitCode = 0
Main
if ($ExitCode -ne 0) {
    Write-Host "Setup did not complete (exit code $ExitCode)." -ForegroundColor Yellow
}
if ($IsFileExecution) {
    exit $ExitCode
}
