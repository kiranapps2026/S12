# owner_verify.ps1 — run by the OWNER when the agent reports "AUTOPILOT COMPLETE".
# Verifies nothing protected was touched, re-runs the certifier yourself, and tags on success.
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Administrator\Documents\1SuperAgents"

$expected = "E5D5AB0D99D7D427B965526C3D7309BBF46127D7FE31B4416E03860C5748F4DF"
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
