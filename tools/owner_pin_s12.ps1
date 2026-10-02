# owner_pin_s12.ps1 — run by the OWNER to pin the S12–S15 golden set, the S12 certifier and the S12 autopilot.
# Run it once after reviewing a golden batch (B1…B5), and again after any ruling that changes a pinned file.
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Administrator\Documents\1SuperAgents"

$expected = "C105C86139B2CF1FD4D17BFF1A266250BD674ABADBA7E128E64818BA473EA0CD"
$actual = (Get-FileHash tools\owner_certify_s12.py -Algorithm SHA256).Hash
if ($actual -ne $expected) {
    throw "tools\owner_certify_s12.py is not the owner version (hash $actual). Restore it before pinning."
}
$actual | Out-File -Encoding ascii docs\gates\owner_certify_s12.sha256

$dirty = git status --porcelain -- tests_golden tools docs\gates\S12_AUTOPILOT.md
if ($dirty) { throw "Uncommitted changes in pinned areas; review and commit them first:`n$dirty" }

$env:PYTHONUTF8 = "1"
python tools\owner_certify_s12.py --selftest
if ($LASTEXITCODE -ne 0) { throw "S12 certifier self-test failed. Do not pin." }
python tools\owner_certify_s12.py --pin
if ($LASTEXITCODE -ne 0) { throw "Pinning failed." }

git add docs\gates\s12_pins.sha256 docs\gates\owner_certify_s12.sha256
git commit -m "Owner: pin S12 golden set, S12 certifier and S12 autopilot"
git push origin s12-work
Write-Host ""
Write-Host "Pinned. Now tell the agent:  continue per S12 AUTOPILOT" -ForegroundColor Green
