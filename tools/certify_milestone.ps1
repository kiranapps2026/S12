# certify_milestone.ps1 — certify a single S12–S15 milestone and update the tracker.
#
# Usage:
#   .\certify_milestone.ps1 -Milestone M12        # certify M0..M12
#   .\certify_milestone.ps1 -Milestone M12 --fast  # skip sabotage + 5x concurrency
#
# This is the per-milestone companion to certify_batch.ps1. Use it during iteration
# to verify one milestone before moving to the next. The batch script runs this
# implicitly for every milestone in the batch.
#
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('M0','M1','M2','M3','M4','M5','M6','M7','M8','M8a','M9',
                 'M10','M11','M12','M13','M14','M15','M16','M17','M18','M19','M20','M21')]
    [string]$Milestone,

    [switch]$Fast
)

$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Administrator\Documents\1SuperAgents"

Write-Host "=== Certifying milestone $Milestone ===" -ForegroundColor Cyan

# ── Certifier binary integrity ───────────────────────────────────────────────
$expectedHash = "C105C86139B2CF1FD4D17BFF1A266250BD674ABADBA7E128E64818BA473EA0CD"
$actualHash = (Get-FileHash tools\owner_certify_s12.py -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) {
    throw "FAIL: tools/owner_certify_s12.py hash mismatch ($actualHash)."
}

$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$PWD\src"
if (-not $env:TEST_DATABASE_URL) {
    throw "TEST_DATABASE_URL not set. Must point at a _test database."
}

# ── Self-test first ──────────────────────────────────────────────────────────
python tools\owner_certify_s12.py --selftest
if ($LASTEXITCODE -ne 0) { throw "FAIL: certifier self-test failed." }

# ── Certify ──────────────────────────────────────────────────────────────────
$args = @("--milestone", $Milestone)
if ($Fast) { $args += "--fast" }

Write-Host "Running: python tools/owner_certify_s12.py $($args -join ' ')" -ForegroundColor DarkGray
python tools\owner_certify_s12.py @args
if ($LASTEXITCODE -ne 0) {
    throw "FAIL: certification of $Milestone failed."
}

Write-Host "$Milestone certified: PASSED" -ForegroundColor Green

# ── Update tracker ───────────────────────────────────────────────────────────
python tools\s12_tracker.py set $Milestone green 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARN: tracker refused $Milestone (may already be green)" -ForegroundColor DarkYellow
} else {
    Write-Host "$Milestone → green in tracker" -ForegroundColor Green
}

$commitSha = git rev-parse --short HEAD
git add docs\gates\S12_PROGRESS.md docs\gates\S12_TRACKER.md docs\gates\s12_milestones.json
git commit -m "Owner checkpoint: $Milestone green at $commitSha"
git push origin s12-work

Write-Host "Committed and pushed: $commitSha" -ForegroundColor Green

# Star milestones need a review step
$starMilestones = @("M1", "M8a", "M14", "M21")
if ($starMilestones -contains $Milestone) {
    Write-Host ""
    Write-Host "Star milestone ($Milestone): run after review:" -ForegroundColor Yellow
    Write-Host "  python tools\s12_tracker.py set $Milestone reviewed" -ForegroundColor White
    Write-Host "  git add docs/gates/s12_milestones.json && git commit -m 'Owner: $Milestone reviewed'" -ForegroundColor White
}
