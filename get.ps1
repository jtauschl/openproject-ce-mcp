# One-liner installer for openproject-mcp (Windows PowerShell).
# Usage: irm https://raw.githubusercontent.com/jtauschl/openproject-mcp/main/get.ps1 | iex
#
# Clones the repo to %USERPROFILE%\openproject-mcp (override: $env:DIR),
# then runs the interactive setup.
$ErrorActionPreference = "Stop"

$Repo = "https://github.com/jtauschl/openproject-mcp.git"
$Dest = if ($env:DIR) { $env:DIR } else { Join-Path $env:USERPROFILE "openproject-mcp" }

# ── check git ─────────────────────────────────────────────────────────────────
if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) {
    Write-Error "git is required. Install from https://git-scm.com or via winget: winget install Git.Git"
    exit 1
}

# ── check Python 3.10+ ────────────────────────────────────────────────────────
$Python = $null
$PyArgs = @()

if (Get-Command "py" -ErrorAction SilentlyContinue) {
    if ((py -3 -c "import sys; print(sys.version_info >= (3, 10))" 2>$null) -eq "True") {
        $Python = "py"; $PyArgs = @("-3")
    }
}
if (-not $Python) {
    foreach ($p in @("python", "python3")) {
        if (Get-Command $p -ErrorAction SilentlyContinue) {
            if ((& $p -c "import sys; print(sys.version_info >= (3, 10))" 2>$null) -eq "True") {
                $Python = $p; break
            }
        }
    }
}
if (-not $Python) {
    Write-Error "Python 3.10 or later is required. Install from https://python.org or via winget: winget install Python.Python.3.13"
    exit 1
}

# ── clone or update ───────────────────────────────────────────────────────────
if (Test-Path (Join-Path $Dest ".git")) {
    Write-Host "Updating existing install at $Dest ..."
    git -C $Dest pull --ff-only
} else {
    Write-Host "Cloning into $Dest ..."
    git clone $Repo $Dest
}

# ── verify checkout ───────────────────────────────────────────────────────────
# Guard against a stale or partial Dest left by an interrupted clone/pull.
if (-not (Test-Path (Join-Path $Dest "configure_mcp.py"))) {
    Write-Error "Setup script not found at $Dest\configure_mcp.py. The checkout looks incomplete. Remove it and re-run: Remove-Item -Recurse -Force `"$Dest`""
    exit 1
}

# ── run setup ─────────────────────────────────────────────────────────────────
Set-Location $Dest
& $Python @PyArgs configure_mcp.py
