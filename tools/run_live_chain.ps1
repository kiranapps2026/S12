# run_live_chain.ps1 - run the live multi-step chain test against real DeepSeek + local PostgreSQL.
# Usage (from the repo root):   powershell -ExecutionPolicy Bypass -File .\tools\run_live_chain.ps1 -Pull
#   -Repo <folder>  the clone (default: the folder above this script)
#   -Pull           git fetch/checkout/pull the s0-s11-repair branch first
# Secrets are read from .env by the test itself; this script never prints them.

param(
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [switch]$Pull
)

$ErrorActionPreference = "Stop"
Set-Location $Repo

if ($Pull) {
    git fetch origin s0-s11-repair
    git checkout s0-s11-repair
    git pull origin s0-s11-repair
}

if (-not (Test-Path "tests_postgres\test_live_chain.py")) {
    throw "tests_postgres\test_live_chain.py not found in $Repo. Run with -Pull, or: git checkout s0-s11-repair; git pull origin s0-s11-repair"
}

if (Test-Path ".\.venv\Scripts\Activate.ps1") { . .\.venv\Scripts\Activate.ps1 }

if (-not (Test-Path ".env")) { throw ".env not found in $Repo. Copy .env.example to .env and fill it in." }
$envText = Get-Content ".env" -Raw
foreach ($name in "DEEPSEEK_API_KEY", "TEST_DATABASE_URL") {
    if ($envText -notmatch "(?m)^\s*$name\s*=\s*\S+") { throw "$name is missing or empty in .env" }
}
if ($envText -notmatch "(?m)^\s*TEST_DATABASE_URL\s*=.*_test\s*$") {
    throw "TEST_DATABASE_URL must point at a database whose name ends in _test (the test rebuilds its schema)."
}

if (Get-Command pg_isready -ErrorAction SilentlyContinue) {
    pg_isready
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL is not answering. Start the service, then run this again." }
}

python -c "import pytest, asyncpg, httpx, cryptography" 2>$null
if ($LASTEXITCODE -ne 0) { pip install -e ".[dev]" }

python -m pytest tests_postgres/test_live_chain.py -s
$code = $LASTEXITCODE

if ($code -eq 0) { Write-Host "`nLIVE CHAIN TEST: all passed" -ForegroundColor Green }
else { Write-Host "`nLIVE CHAIN TEST: failures (exit $code). Send me the whole output, especially the 'LLM in=' / 'out=' lines." -ForegroundColor Yellow }
exit $code
