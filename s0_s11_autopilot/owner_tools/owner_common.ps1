# owner_common.ps1 — shared settings for the owner scripts. Dot-sourced, never run directly.
# These scripts live OUTSIDE the repository so the coding agent cannot change them.
$Repo       = "C:\Users\Administrator\Documents\1SuperAgents"
$OwnerDir   = $PSScriptRoot                                   # e.g. C:\Users\Administrator\Documents\1SuperAgents_owner
$TrustedCert = Join-Path $OwnerDir "owner_certify.py"         # the owner's own copy of the certifier
$PinRecord  = Join-Path $OwnerDir "pin_record.txt"            # one line per owner pin commit (first = original pin)
$ExpectedCertHash = "356359B9EFC847B56B7D222C2F92EC3DF53DC0F76B63EDB68D18F2E7F9FF9546"   # certifier with R-Z tests
# (previous certifier, before R-Z: F8E4C933B09884B3106B48710FACE7F6B07AEA24E31F5CAE6258CE88BA1550F2)
$TotalChecks = 19

# Files the agent must never change after the pin commit.
$Protected = @(
    "tools/owner_certify.py",
    "docs/gates/owner_certify.sha256",
    "docs/gates/spec_pins.sha256",
    "docs/gates/S0_S11_RUNBOOK.md",
    "docs/gates/AUTOPILOT.md",
    "docs/implementation",
    ".gitattributes"
)

# Paths the agent may change (AUTOPILOT Part A rule 2). Anything else is flagged for review.
$AllowedPattern = '^(src/|tests/|docs/gates/(autopilot_log\.md|test_manifest_baseline\.txt|test_manifest_final\.txt|test_reconciliation\.md|owner_certify_final\.txt|S0_S11_CERTIFICATION_REPORT\.md|sabotage/.+)$)'

# pytest hooks / options that can hide failures.
$CheatHooks = 'pytest_runtest_makereport|pytest_collection_modifyitems|pytest_runtest_logreport|hookwrapper|force_result|report\.outcome|pytest_report_teststatus'
$CheatOpts  = '--testmon|--lf\b|--last-failed|--deselect|(^|\s)-k\s'   # hide tests -> FAIL
$ReviewOpts = '-p\s*no:|--ignore|(^|\s)-x\b|--maxfail'                  # suspicious -> WARN

$script:Fails = 0
$script:Warns = 0
function Pass($msg) { Write-Host "  PASS  $msg" -ForegroundColor Green }
function Fail($msg) { Write-Host "  FAIL  $msg" -ForegroundColor Red; $script:Fails++ }
function Warn($msg) { Write-Host "  WARN  $msg" -ForegroundColor Yellow; $script:Warns++ }
function Section($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }

function Get-PinLines {
    if (-not (Test-Path $PinRecord)) { return @() }
    return @(Get-Content $PinRecord | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}
function Get-PinCommit      { $l = Get-PinLines; if ($l.Count) { return $l[-1] } else { return $null } }  # latest pin: protection
function Get-FirstPinCommit { $l = Get-PinLines; if ($l.Count) { return $l[0] }  else { return $null } }  # original pin: scope

# Shared protection checks used by checkpoint and verify.
function Test-Protection {
    Section "Protection"
    if (-not (Test-Path $TrustedCert)) { Fail "trusted certifier missing at $TrustedCert"; return }
    $t = (Get-FileHash $TrustedCert -Algorithm SHA256).Hash
    if ($t -ne $ExpectedCertHash) { Fail "trusted certifier copy has wrong hash $t" } else { Pass "trusted certifier hash" }

    $r = (Get-FileHash (Join-Path $Repo "tools\owner_certify.py") -Algorithm SHA256).Hash
    if ($r -ne $ExpectedCertHash) { Fail "repo certifier modified ($r)" } else { Pass "repo certifier hash" }

    $pin = Get-PinCommit
    if (-not $pin) { Fail "no pin record — run owner_pin.ps1 first"; return }
    git merge-base --is-ancestor $pin HEAD 2>$null
    if ($LASTEXITCODE -ne 0) { Fail "pin commit $pin is not an ancestor of HEAD (history rewritten?)"; return }
    Pass "latest pin commit $pin is in history ($((Get-PinLines).Count) pin(s) recorded)"

    $changed = git diff --name-only $pin HEAD -- $Protected
    $dirty   = git status --porcelain -- $Protected
    if ($changed -or $dirty) { Fail "protected files changed since pin:"; (@($changed) + @($dirty)) | ForEach-Object { "          $_" } }
    else { Pass "protected files unchanged since pin (specs, runbook, AUTOPILOT, hashes, .gitattributes)" }

    $tags = git tag --contains $pin 2>$null | Where-Object { $_ -ne "s0-s11-certified" }
    if ($tags) { Warn "tags created after the pin (agent must not tag): $($tags -join ', ')" }
}

function Test-Scope {
    Section "Change scope since pin"
    $pin = Get-FirstPinCommit
    if (-not $pin) { return }
    # Protected paths are covered by Test-Protection (owner re-pins legitimately change them).
    $protRx = '^(' + (($Protected | ForEach-Object { [regex]::Escape($_) }) -join '|') + ')'
    $files = git diff --name-only $pin HEAD | Where-Object { $_ -notmatch $protRx -and $_ -notmatch '^tools/owner_(pin|verify)\.ps1$' }
    $outside = $files | Where-Object { $_ -notmatch $AllowedPattern }
    if ($outside) { Warn "files outside the allowed scope — review each:"; $outside | ForEach-Object { "          $_" } }
    else { Pass "$(@($files).Count) changed files, all inside src/, tests/, allowed docs/gates files" }

    # conftest / pytest config tricks
    $conf = Get-ChildItem -Recurse -Filter conftest.py -File | Where-Object { $_.FullName -notmatch '\\(\.venv|venv|\.git)\\' }
    $hits = $conf | Select-String -Pattern $CheatHooks
    if ($hits) { Fail "result/selection-altering pytest hooks in conftest:"; $hits | ForEach-Object { "          $($_.Path):$($_.LineNumber)  $($_.Line.Trim())" } }
    else { Pass "no result-altering hooks in conftest.py files" }

    foreach ($cfg in @("pyproject.toml", "pytest.ini", "setup.cfg", "tox.ini")) {
        if (Test-Path $cfg) {
            $bad = Select-String -Path $cfg -Pattern 'addopts' -Context 0,3 | Where-Object { ($_.Line + ($_.Context.PostContext -join ' ')) -match $CheatOpts }
            if ($bad) { Fail "$cfg addopts hides tests: $($bad.Line.Trim())" }
            $sus = Select-String -Path $cfg -Pattern 'addopts' -Context 0,3 | Where-Object { ($_.Line + ($_.Context.PostContext -join ' ')) -match $ReviewOpts }
            if ($sus) { Warn "$cfg addopts has options to review: $($sus.Line.Trim())" }
        }
    }
    if ($env:PYTEST_ADDOPTS) { Warn "PYTEST_ADDOPTS is set in this shell ($env:PYTEST_ADDOPTS) — clearing it for this run"; $env:PYTEST_ADDOPTS = "" }
}

function Clear-Caches {
    Get-ChildItem -Recurse -Directory -Filter __pycache__ -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    if (Test-Path .pytest_cache) { Remove-Item -Recurse -Force .pytest_cache -ErrorAction SilentlyContinue }
}

