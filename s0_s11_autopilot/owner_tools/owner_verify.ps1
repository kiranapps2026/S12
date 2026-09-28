# owner_verify.ps1 v2 — run by the OWNER when the agent reports "AUTOPILOT COMPLETE".
# Independently re-checks everything with the owner's own certifier copy, replays the
# sabotage kit in a throw-away worktree, and tags only if every check passes.
#
# Usage:  powershell -ExecutionPolicy Bypass -File owner_verify.ps1
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "owner_common.ps1")
Set-Location $Repo
$head = git rev-parse --short HEAD
Write-Host "S0-S11 owner verification at $head" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1. protection + scope
Test-Protection
Test-Scope
Section "Working tree"
$dirty = git status --porcelain
if ($dirty) { Fail "uncommitted changes:"; $dirty | ForEach-Object { "          $_" } } else { Pass "clean" }

# ---------------------------------------------------------------- 2. certifier (trusted copy)
Section "Certifier self-test (trusted copy)"
python $TrustedCert --selftest
if ($LASTEXITCODE -ne 0) { Fail "self-test" } else { Pass "self-test" }

Section "Certifier full run (trusted copy)"
Clear-Caches
$certOut = python $TrustedCert 2>&1 | Out-String
Write-Host $certOut
if ($LASTEXITCODE -ne 0 -or $certOut -notmatch "$TotalChecks/$TotalChecks PASS") { Fail "certifier is not $TotalChecks/$TotalChecks" }
else { Pass "certifier $TotalChecks/$TotalChecks" }

# ---------------------------------------------------------------- 3. order independence
Section "Suite: serial and parallel"
Clear-Caches
python -m pytest -q -p no:cacheprovider 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Fail "serial run not green" } else { Pass "serial run green" }
Clear-Caches
python -m pytest -q -p no:cacheprovider -n 4 2>&1 | Select-Object -Last 3
if ($LASTEXITCODE -ne 0) { Fail "parallel run (-n 4) not green: tests depend on order/shared state" } else { Pass "parallel run green" }

# ---------------------------------------------------------------- 4. sabotage replay
Section "Sabotage kit replay (each patch must make its test fail)"
if ($env:PYTHONPATH -and $env:PYTHONPATH -match [regex]::Escape($Repo)) {
    Warn "PYTHONPATH points into the repo ($env:PYTHONPATH); the worktree may import unpatched code"
}
$wt = Join-Path $env:TEMP "s0s11_sabotage_wt"
git worktree remove --force $wt 2>$null | Out-Null
if (Test-Path $wt) { Remove-Item -Recurse -Force $wt }
git worktree add --detach $wt HEAD 2>$null | Out-Null
try {
    foreach ($n in 1..10) {
        $id = "SAB-{0:D2}" -f $n
        $patch = Join-Path $Repo "docs\gates\sabotage\$id.patch"
        $testf = Join-Path $Repo "docs\gates\sabotage\$id.test"
        if (-not (Test-Path $patch) -or -not (Test-Path $testf)) { Fail "$id missing"; continue }
        $node = (Get-Content $testf -Raw).Trim()
        $body = Get-Content $patch
        $targets = $body | Where-Object { $_ -match '^\+\+\+ b/(.+)$' } | ForEach-Object { $Matches[1] }
        $notSrc = $targets | Where-Object { $_ -notmatch '^src/' }
        $size = @($body | Where-Object { $_ -match '^[+-]' -and $_ -notmatch '^(\+\+\+|---) ' }).Count
        if (-not $targets -or $notSrc) { Fail "$id patch must touch src/ only (touches: $($targets -join ', '))"; continue }
        if ($size -gt 12) { Warn "$id patch is large ($size +/- lines) — read it: $patch" }

        git -C $wt apply $patch 2>$null
        if ($LASTEXITCODE -ne 0) { Fail "$id patch does not apply to HEAD"; continue }
        Push-Location $wt
        $out = python -m pytest $node -q -p no:cacheprovider 2>&1 | Out-String
        $code = $LASTEXITCODE
        Pop-Location
        git -C $wt checkout -- . 2>$null
        git -C $wt clean -fdq 2>$null

        if ($out -match 'SyntaxError|IndentationError|ImportError|ModuleNotFoundError|no tests ran|ERROR: not found') {
            Fail "$id broke the build instead of the rule ($node) — not a valid sabotage"
        } elseif ($code -eq 1 -and $out -match 'AssertionError|assert ') {
            Pass "$id  $node  fails under sabotage"
        } else {
            Fail "$id  $node  did NOT fail under sabotage (exit $code) — the test is weak"
        }
    }
} finally {
    Set-Location $Repo
    git worktree remove --force $wt 2>$null | Out-Null
}

# ---------------------------------------------------------------- 5. evidence files
Section "Evidence"
foreach ($f in @("docs\gates\S0_S11_CERTIFICATION_REPORT.md", "docs\gates\owner_certify_final.txt",
                 "docs\gates\test_manifest_baseline.txt", "docs\gates\test_manifest_final.txt",
                 "docs\gates\test_reconciliation.md", "docs\gates\autopilot_log.md")) {
    if (Test-Path $f) { Pass $f } else { Fail "$f missing" }
}
if (Test-Path docs\gates\autopilot_log.md) {
    $log = Get-Content docs\gates\autopilot_log.md -Raw
    $missing = 1..6 | Where-Object { $log -notmatch "MILESTONE M$_ REACHED" } | ForEach-Object { "M$_" }
    if ($missing) { Fail "milestones not logged: $($missing -join ', ')" } else { Pass "milestones M1-M6 logged" }
}

# ---------------------------------------------------------------- verdict
Write-Host ""
if ($script:Fails -gt 0) {
    Write-Host "NOT CERTIFIED at $head — $($script:Fails) FAIL(s). Send the FAIL lines to the agent as an AUTOPILOT STOP." -ForegroundColor Red
    exit 1
}
if ($script:Warns -gt 0) { Write-Host "$($script:Warns) warning(s): read them before tagging." -ForegroundColor Yellow }
Write-Host "S0-S11 CERTIFIED at commit $head (verified by owner)." -ForegroundColor Green
$answer = Read-Host "Create tag s0-s11-certified on $head? (y/n)"
if ($answer -eq "y") {
    git tag -a s0-s11-certified -m "S0-S11 certified by owner verification"
    Write-Host "Tagged." -ForegroundColor Green
}
