# sync_and_check.ps1 - one run: fetch repair + baseline, check out and update the repair branch, install, run the
# certifier, the registry-readiness check against your DEV database, and (with -Tests) the full suites.
# Usage (from anywhere):  powershell -ExecutionPolicy Bypass -File <repo>\tools\sync_and_check.ps1
#   -Repo <folder>   the clone (default: the folder above this script)
#   -Tests           also run pytest tests + tests_postgres (needs TEST_DATABASE_URL in .env, name ending _test)
# Reads DATABASE_URL (the dev database, NOT the _test one) from .env. Prints no secrets. Pushes nothing:
# everything on the branch is already pushed; this only pulls.

param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [switch]$Tests
)

$ErrorActionPreference = "Stop"
Set-Location $Repo
$env:PYTHONUTF8 = "1"   # the tests read source files with the default codec; Windows would use cp1252

$dirty = git status --porcelain
if ($dirty) { Write-Host "Uncommitted changes here; commit or stash them first:" -ForegroundColor Red; $dirty; exit 1 }

git fetch origin s0-s11-repair s0-s11-baseline
git checkout s0-s11-repair
git pull origin s0-s11-repair
Write-Host "repair  : $(git rev-parse --short HEAD)"
Write-Host "baseline: $(git rev-parse --short origin/s0-s11-baseline)"

if (Test-Path ".\.venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }
python -c "import pytest, asyncpg, httpx, cryptography" 2>$null
if ($LASTEXITCODE -ne 0) { pip install -e ".[dev]" }

if (-not (Test-Path ".env")) { throw ".env not found in $Repo." }
$envText = Get-Content ".env" -Raw
function Get-EnvValue($name) {
    if ($envText -match "(?m)^\s*$name\s*=\s*(\S+)") { return $Matches[1].Trim('"').Trim("'") }
    return $null
}

$failed = @()

Write-Host "`n== Certifier ==" -ForegroundColor Cyan
python tools\owner_certify.py
if ($LASTEXITCODE -ne 0) { $failed += "certifier" }

Write-Host "`n== Registry readiness (dev database) ==" -ForegroundColor Cyan
$dev = Get-EnvValue "DATABASE_URL"
if (-not $dev) { throw "DATABASE_URL is missing in .env" }
if ($dev -match "_test(\?|$)") { throw "DATABASE_URL points at a _test database; the readiness check must look at the dev database." }
$env:DATABASE_URL = $dev
python tools\registry_readiness.py
if ($LASTEXITCODE -ne 0) { $failed += "registry readiness (operations blocked; send me the list)" }

if ($Tests) {
    Write-Host "`n== Test suites ==" -ForegroundColor Cyan
    $test = Get-EnvValue "TEST_DATABASE_URL"
    if (-not $test -or $test -notmatch "_test(\?|$)") { throw "TEST_DATABASE_URL must be set in .env and end in _test." }
    $env:TEST_DATABASE_URL = $test
    python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { $failed += "tests" }
    python -m pytest tests_postgres -q
    if ($LASTEXITCODE -ne 0) { $failed += "tests_postgres" }
}

if ($failed.Count -eq 0) { Write-Host "`nALL CHECKS PASSED" -ForegroundColor Green; exit 0 }
Write-Host "`nNEEDS ATTENTION: $($failed -join '; ')" -ForegroundColor Yellow
exit 1
