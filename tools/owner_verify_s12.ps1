# owner_verify_s12.ps1 Mxx — run by the OWNER when the agent reports "S12 MILESTONE Mxx REACHED".
# Checks that nothing protected was touched, re-runs the S12 certifier yourself, records the checkpoint,
# and after M21 offers the s12-s15-certified tag.
param([Parameter(Mandatory = $true)][string]$Milestone)
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Administrator\Documents\1SuperAgents"

$expected = "C105C86139B2CF1FD4D17BFF1A266250BD674ABADBA7E128E64818BA473EA0CD"
$actual = (Get-FileHash tools\owner_certify_s12.py -Algorithm SHA256).Hash
if ($actual -ne $expected) { Write-Host "FAIL: S12 certifier was modified ($actual). Checkpoint void." -ForegroundColor Red; exit 1 }
$stored = (Get-Content docs\gates\owner_certify_s12.sha256 -Raw).Trim()
if ($stored -ne $expected) { Write-Host "FAIL: stored S12 certifier hash was modified. Checkpoint void." -ForegroundColor Red; exit 1 }

git fetch origin s12-work
$dirty = git status --porcelain
if ($dirty) { Write-Host "FAIL: uncommitted changes exist:" -ForegroundColor Red; $dirty; exit 1 }
git pull --ff-only origin s12-work

Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
$env:PYTHONUTF8 = "1"
python tools\owner_certify_s12.py --selftest
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: S12 certifier self-test failed." -ForegroundColor Red; exit 1 }

python tools\owner_certify_s12.py --milestone $Milestone --progress
if ($LASTEXITCODE -ne 0) { Write-Host "NOT REACHED: see FAIL rows above." -ForegroundColor Red; exit 1 }

$commit = git rev-parse --short HEAD
python tools\s12_tracker.py set $Milestone green
if ($LASTEXITCODE -ne 0) { Write-Host "Tracker refused the move (see message)." -ForegroundColor Red; exit 1 }
git add docs\gates\S12_PROGRESS.md docs\gates\S12_TRACKER.md docs\gates\s12_milestones.json
git commit -m "Owner checkpoint: $Milestone green at $commit"
git push origin s12-work
Write-Host ""
Write-Host "$Milestone REACHED at commit $commit (verified by owner)." -ForegroundColor Green
Write-Host "Star milestones (M1, M8a, M14, M21): review, then  python tools\s12_tracker.py set $Milestone reviewed" -ForegroundColor Yellow

if ($Milestone -match '^M0*21$') {
    $answer = Read-Host "Create tag s12-s15-certified on $commit? (y/n)"
    if ($answer -eq "y") { git tag s12-s15-certified; git push origin s12-s15-certified; Write-Host "Tagged." -ForegroundColor Green }
}
