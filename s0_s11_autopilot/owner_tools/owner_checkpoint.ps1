# owner_checkpoint.ps1 — READ-ONLY progress audit. Run any time, e.g. when the log shows
# "MILESTONE M2 REACHED". Changes nothing in the repository; safe while the agent works.
#
# Usage:  powershell -ExecutionPolicy Bypass -File owner_checkpoint.ps1 [-Full]
#   default : protection + scope + static checks (seconds)
#   -Full   : also runs the pytest-based checks (OWN-12..15) with the trusted certifier
param([switch]$Full)
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "owner_common.ps1")
Set-Location $Repo

Write-Host "S0-S11 checkpoint  $(Get-Date -Format 'yyyy-MM-dd HH:mm')   HEAD $(git rev-parse --short HEAD)" -ForegroundColor Cyan

Test-Protection
Test-Scope

Section "Agent progress (docs/gates/autopilot_log.md)"
$log = "docs\gates\autopilot_log.md"
if (Test-Path $log) {
    $lines = Get-Content $log
    $ms = $lines | Where-Object { $_ -match '^MILESTONE' }
    if ($ms) { $ms | ForEach-Object { "  $_" } } else { "  no milestone reached yet" }
    "  last 8 iterations:"
    $lines | Where-Object { $_ -notmatch '^MILESTONE' } | Select-Object -Last 8 | ForEach-Object { "    $_" }
    # PASS count must never go down between consecutive iterations
    $counts = $lines | ForEach-Object { if ($_ -match '\|\s*(\d+)/19\s*\|') { [int]$Matches[1] } }
    for ($i = 1; $i -lt @($counts).Count; $i++) {
        if ($counts[$i] -lt $counts[$i - 1]) { Warn "PASS count dropped $($counts[$i-1]) -> $($counts[$i]) at log entry $($i+1)" }
    }
} else { Warn "no autopilot_log.md yet" }

$stops = git log --oneline -30 | Select-String -Pattern 'revert|Revert'
if ($stops) { "  recent reverts:"; $stops | ForEach-Object { "    $_" } }

Section "Certifier (trusted copy, run on the repo)"
Clear-Caches
if ($Full) { python $TrustedCert } else { python $TrustedCert --static }

Write-Host ""
if ($script:Fails) { Write-Host "CHECKPOINT: $($script:Fails) protection/scope FAIL(s) — stop the agent and send the fail lines back." -ForegroundColor Red }
elseif ($script:Warns) { Write-Host "CHECKPOINT: no protection failures, $($script:Warns) warning(s) to review." -ForegroundColor Yellow }
else { Write-Host "CHECKPOINT: protection and scope clean. Let the agent continue." -ForegroundColor Green }
