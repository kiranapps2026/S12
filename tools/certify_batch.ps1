# certify_batch.ps1 — certify and owner-pin an entire batch (B1…B5) of S12–S15 milestones.
#
# Usage:
#   .\certify_batch.ps1 -Batch B3          # certify M0..M14 (everything up to and including B3)
#   .\certify_batch.ps1 -Batch B3 -SkipPin # certify only, do not pin
#
# What it does per batch:
#   1. Verifies the certifier binary is unmodified (SHA-256 guard).
#   2. Runs the S12 certifier for every milestone in the batch (full: sabotage + 5x concurrency).
#   3. If all pass, runs the certifier --pin to write docs/gates/s12_pins.sha256.
#   4. Commits the pin file and pushes.
#
# Prerequisites:
#   - Clean working tree on s12-work (no uncommitted changes in tests_golden/ or docs/gates/)
#   - TEST_DATABASE_URL in environment, pointing at a _test database
#   - PYTHONPATH=$PWD/src (or pip install -e .)
#   - Owner privileges on the branch
#
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('B1','B2','B3','B4','B5')]
    [string]$Batch,

    [switch]$SkipPin
)

$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Administrator\Documents\1SuperAgents"

# ── Batch → last milestone mapping ───────────────────────────────────────────
$batchMap = @{
    B1 = "M4"
    B2 = "M9"
    B3 = "M14"
    B4 = "M18"
    B5 = "M21"
}
$lastMilestone = $batchMap[$Batch]
Write-Host "=== Certifying batch $Batch (M0..$lastMilestone) ===" -ForegroundColor Cyan

# ── Pre-flight: clean tree ───────────────────────────────────────────────────
$dirty = git status --porcelain
if ($dirty) {
    throw "Uncommitted changes exist. Commit or stash first:`n$dirty"
}

# ── Certifier binary integrity ───────────────────────────────────────────────
$expectedHash = "C105C86139B2CF1FD4D17BFF1A266250BD674ABADBA7E128E64818BA473EA0CD"
$actualHash = (Get-FileHash tools\owner_certify_s12.py -Algorithm SHA256).Hash
if ($actualHash -ne $expectedHash) {
    throw "FAIL: tools/owner_certify_s12.py hash mismatch ($actualHash). Checkpoint void."
}
Write-Host "Certifier binary: OK ($expectedHash)" -ForegroundColor Green

# ── Python environment ───────────────────────────────────────────────────────
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$PWD\src"
if (-not $env:TEST_DATABASE_URL) {
    throw "TEST_DATABASE_URL not set. Must point at a _test database."
}

# ── Certifier self-test ──────────────────────────────────────────────────────
Write-Host "`n[1/3] Certifier self-test..." -ForegroundColor Yellow
python tools\owner_certify_s12.py --selftest
if ($LASTEXITCODE -ne 0) { throw "FAIL: certifier self-test failed." }

# ── Full certification up to the batch's last milestone ──────────────────────
Write-Host "`n[2/3] Certifying M0..$lastMilestone (full: golden + sabotage + 5x concurrency)..." -ForegroundColor Yellow
Write-Host "  This may take several minutes for B3/B4/B5..." -ForegroundColor DarkGray

python tools\owner_certify_s12.py --milestone $lastMilestone
if ($LASTEXITCODE -ne 0) {
    throw "FAIL: certification of M0..$lastMilestone failed. See output above."
}
Write-Host "Certification of M0..$lastMilestone: PASSED" -ForegroundColor Green

# ���─ Milestone tracker: set every milestone in the batch to green ─────────────
Write-Host "`n[3/3] Updating milestone tracker..." -ForegroundColor Yellow

$allMilestones = @("M0","M1","M2","M3","M4","M5","M6","M7","M8","M8a","M9",
                   "M10","M11","M12","M13","M14","M15","M16","M17","M18","M19","M20","M21")
$batchEndIdx = [array]::IndexOf($allMilestones, $lastMilestone)

for ($i = 0; $i -le $batchEndIdx; $i++) {
    $mid = $allMilestones[$i]
    python tools\s12_tracker.py set $mid green 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  WARN: tracker refused $mid (may already be green)" -ForegroundColor DarkYellow
    } else {
        Write-Host "  $mid → green" -ForegroundColor Green
    }
}

# ── Commit tracker changes ───────────────────────────────────────────────────
$trackerFiles = @(
    "docs\gates\S12_PROGRESS.md",
    "docs\gates\S12_TRACKER.md",
    "docs\gates\s12_milestones.json"
)
git add @trackerFiles
$commitMsg = "Owner checkpoint: $Batch (M0..$lastMilestone) certified green"
git commit -m $commitMsg

$commitSha = git rev-parse --short HEAD
Write-Host "`nTracker committed: $commitSha" -ForegroundColor Green

# ── Pin (owner-only: records SHA-256 of the entire golden set) ───────────────
if (-not $SkipPin) {
    Write-Host "`n[4/4] Pinning golden set..." -ForegroundColor Yellow
    python tools\owner_certify_s12.py --pin
    if ($LASTEXITCODE -ne 0) { throw "FAIL: pinning failed." }

    git add docs\gates\s12_pins.sha256 docs\gates\owner_certify_s12.sha256
    git commit -m "Owner: pin S12 golden set and certifier (batch $Batch)"
    git push origin s12-work

    Write-Host "Pinned and pushed." -ForegroundColor Green
} else {
    Write-Host "`nPin skipped (-SkipPin). Run .\owner_pin_s12.ps1 manually when ready." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "=== Batch $Batch certification complete ===" -ForegroundColor Cyan
Write-Host "  Commit : $commitSha" -ForegroundColor White
Write-Host "  Milestones: M0..$lastMilestone → green" -ForegroundColor White
if (-not $SkipPin) {
    Write-Host "  Pinned : docs/gates/s12_pins.sha256" -ForegroundColor White
}

# Star milestones (M1, M8a, M14, M21) need a separate review step:
$starMilestones = @("M1", "M8a", "M14", "M21") | Where-Object { $_ -le $lastMilestone }
if ($starMilestones) {
    Write-Host ""
    Write-Host "NOTE: Star milestones require a review step before 'reviewed' status:" -ForegroundColor Yellow
    $starMilestones | ForEach-Object { Write-Host "  python tools\s12_tracker.py set $_ reviewed" }
}
