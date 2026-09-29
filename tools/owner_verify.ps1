# owner_verify.ps1 — run by the OWNER when the agent reports "AUTOPILOT COMPLETE".
# Verifies nothing protected was touched, re-runs the certifier yourself, and tags on success.
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Administrator\Documents\1SuperAgents"

$expected = "6B9D1C301DC1D4461923610F652806DAB0015FB2D4B63CBF113772F94A734043"
$actual = (Get-FileHash tools\owner_certify.py -Algorithm SHA256).Hash
if ($actual -ne $expected) { Write-Host "FAIL: certifier was modified ($actual). Certification void." -ForegroundColor Red; exit 1 }
$stored = (Get-Content docs\gates\owner_certify.sha256 -Raw).Trim()
if ($stored -ne $expected) { Write-Host "FAIL: stored certifier hash was modified. Certification void." -ForegroundColor Red; exit 1 }

$dirty = git status --porcelain
if ($dirty) { Write-Host "FAIL: uncommitted changes exist:" -ForegroundColor Red; $dirty; exit 1 }

Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

python tools\owner_certify.py --selftest
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: certifier self-test failed." -ForegroundColor Red; exit 1 }

python tools\owner_certify.py
if ($LASTEXITCODE -ne 0) { Write-Host "NOT CERTIFIED: see FAIL rows above." -ForegroundColor Red; exit 1 }

$commit = git rev-parse --short HEAD
Write-Host ""
Write-Host "S0-S11 CERTIFIED at commit $commit (verified by owner)." -ForegroundColor Green
$answer = Read-Host "Create tag s0-s11-certified on $commit? (y/n)"
if ($answer -eq "y") { git tag s0-s11-certified; Write-Host "Tagged." -ForegroundColor Green }
