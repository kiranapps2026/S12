# owner_pin.ps1 v2 — run by the OWNER (never the agent), once, before the autopilot loop.
# Pins the certifier, the spec documents, the runbook and AUTOPILOT, commits them,
# and records the pin commit OUTSIDE the repository so the agent cannot re-pin.
#
# Usage:  powershell -ExecutionPolicy Bypass -File owner_pin.ps1 [-Baseline d972516]
#   -Baseline = the commit where docs/implementation was first placed in 1SuperAgents.
param([string]$Baseline = "d972516")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "owner_common.ps1")
Set-Location $Repo

# 1. Trusted certifier -> repo (the repo copy is only a convenience for the agent)
$t = (Get-FileHash $TrustedCert -Algorithm SHA256).Hash
if ($t -ne $ExpectedCertHash) { throw "Your owner copy $TrustedCert has hash $t, expected $ExpectedCertHash. Re-download it." }
Copy-Item $TrustedCert tools\owner_certify.py -Force

# 2. AUTOPILOT v2 and the runbook must be in place
if (-not (Select-String -Path docs\gates\AUTOPILOT.md -SimpleMatch "AUTOPILOT v2" -Quiet)) {
    throw "docs\gates\AUTOPILOT.md is not v2. Copy the v2 file into docs\gates\ first."
}
if (-not (Test-Path docs\gates\S0_S11_RUNBOOK.md)) { throw "docs\gates\S0_S11_RUNBOOK.md missing." }

# 3. Owner approves the spec state that is about to be frozen
Write-Host "`nSpec changes since baseline $Baseline (working tree, line-ending changes ignored):" -ForegroundColor Cyan
git --no-pager diff --stat --ignore-cr-at-eol $Baseline -- docs/implementation
Write-Host "`nAllowed: B1-B4, ADR-13 register fix, PIPELINE_STAGES transport-normalization caution,"
Write-Host "WORKER_LIFECYCLE Re-entry Revalidation section, and files the owner added (gate, S12 plan)."
Write-Host "To inspect a file:  git diff --ignore-cr-at-eol $Baseline -- docs/implementation/<name>.md"
$ok = Read-Host "Freeze the specs exactly as they are now? (y/n)"
if ($ok -ne "y") { Write-Host "Not pinned. Ask the agent to revert the unapproved hunks, then re-run." -ForegroundColor Yellow; exit 1 }

# 4. Byte-exact files (no line-ending conversion), hashes, pins
$rules = @("tools/owner_certify.py -text", "docs/implementation/*.md -text",
           "docs/gates/S0_S11_RUNBOOK.md -text", "docs/gates/AUTOPILOT.md -text",
           "docs/gates/*.sha256 -text")
foreach ($rule in $rules) {
    if (-not (Test-Path .gitattributes) -or -not (Select-String -Path .gitattributes -SimpleMatch $rule -Quiet)) {
        Add-Content .gitattributes $rule
    }
}
$ExpectedCertHash | Out-File -Encoding ascii docs\gates\owner_certify.sha256

$pinned = @(Get-ChildItem docs\implementation\*.md | Sort-Object Name | ForEach-Object { "docs/implementation/$($_.Name)" })
$pinned += "docs/gates/S0_S11_RUNBOOK.md", "docs/gates/AUTOPILOT.md"
$pinned | ForEach-Object { "{0}  {1}" -f (Get-FileHash $_ -Algorithm SHA256).Hash, $_ } |
    Out-File -Encoding ascii docs\gates\spec_pins.sha256
Write-Host "Pinned $($pinned.Count) documents." -ForegroundColor Green

# 5. Certifier self-test with the TRUSTED copy
python $TrustedCert --selftest
if ($LASTEXITCODE -ne 0) { throw "Certifier self-test failed. Do not continue." }

# 6. Commit ONLY the pinned paths (agent work-in-progress in src/ and tests/ is left alone)
$paths = @(".gitattributes", "tools/owner_certify.py", "docs/gates/owner_certify.sha256",
           "docs/gates/spec_pins.sha256", "docs/gates/S0_S11_RUNBOOK.md", "docs/gates/AUTOPILOT.md",
           "docs/implementation")
git add -- $paths
# v1 owner scripts inside the repo are retired (owner scripts now live outside the repo)
foreach ($old in @("tools/owner_pin.ps1", "tools/owner_verify.ps1")) {
    if (git ls-files -- $old) { git rm -q -- $old; $paths += $old }
    elseif (Test-Path $old) { Remove-Item $old }
}
git commit -m "Owner: pin certifier, specs, runbook and AUTOPILOT v2" -- $paths
if ($LASTEXITCODE -ne 0) { throw "git commit failed." }
$pin = git rev-parse HEAD
$pin | Out-File -Encoding ascii $PinRecord

# 7. Baseline measurement, kept outside the repo
Clear-Caches
$stamp = Get-Date -Format "yyyyMMdd-HHmm"
python $TrustedCert --static | Tee-Object -FilePath (Join-Path $OwnerDir "baseline_static_$stamp.txt")

Write-Host ""
Write-Host "Pinned at $pin (recorded in $PinRecord)." -ForegroundColor Green
Write-Host "Now tell the agent:  continue per AUTOPILOT" -ForegroundColor Green
