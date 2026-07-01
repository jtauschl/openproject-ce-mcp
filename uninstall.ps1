# Windows PowerShell — removes the local environment and, on request, the server
# entry from your MCP client configs. Your local .mcp.json is left untouched.
$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

# Remove the openproject entry from any client config it was registered in
# (keeps other servers and settings; backs up each file first).
$Python = $null
foreach ($p in @("python", "python3")) {
    if (Get-Command $p -ErrorAction SilentlyContinue) { $Python = $p; break }
}
if ($Python) {
    try { & $Python configure_mcp.py --uninstall } catch { }
}

# Remove local build/dev artifacts and the API-source clones (large, gitignored).
foreach ($item in @(".venv", ".pytest_cache", ".ruff_cache", ".op-sources")) {
    if (Test-Path $item) { Remove-Item -Recurse -Force $item }
}
Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Recurse -Directory -Filter "*.egg-info" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Local environment removed (.venv, caches, .op-sources)."
Write-Host "Your .mcp.json was left untouched."
Write-Host "If you registered the server globally in a client, that entry was removed"
Write-Host "above (a backup of each edited config was kept)."
