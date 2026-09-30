# sync_s12_workspace.ps1 - create or update a SEPARATE working folder for a second Claude Code session on the same
# machine (the S12 test author), then prove it is ready: same commit as GitHub, own virtual environment, database
# reachable, S12 tooling self-tests green.
#
# First time (run from the master folder, which already has the script):
#   powershell -ExecutionPolicy Bypass -File C:\Users\Administrator\Documents\1SuperAgents\tools\sync_s12_workspace.ps1
# Every later time (fetch + pull everything, reinstall if needed, re-check):
#   powershell -ExecutionPolicy Bypass -File C:\Users\Administrator\Documents\1SuperAgents-tests\tools\sync_s12_workspace.ps1
#
#   -Folder <path>      the second clone (default: 1SuperAgents-tests next to the master folder)
#   -Master <path>      the master clone, source of the git identity and TEST_DATABASE_URL (default: 1SuperAgents)
#   -Branch <name>      default s12-work
#   -TestDatabase <db>  use this database name instead of the master's (must end in _test; must already exist)
#   -RunGolden          also run every golden file (red until its milestone is built: that is expected)
#
# Never prints secrets. Never pushes, never merges, never resets: a folder with local changes or local commits
# that are not on GitHub is reported and left alone.

param(
    [string]$Folder = "C:\Users\Administrator\Documents\1SuperAgents-tests",
    [string]$Master = "C:\Users\Administrator\Documents\1SuperAgents",
    [string]$Branch = "s12-work",
    [string]$TestDatabase = "",
    [switch]$RunGolden
)

$ErrorActionPreference = "Continue"   # native git/python errors are checked through $LASTEXITCODE (PowerShell 5.1 safe)
$env:PYTHONUTF8 = "1"
function Step($text) { Write-Host "`n== $text ==" -ForegroundColor Cyan }
function Fail($text) { Write-Host "FAIL: $text" -ForegroundColor Red; exit 1 }
$problems = @()

if ((Resolve-Path -LiteralPath $Master -ErrorAction SilentlyContinue).Path -eq (Resolve-Path -LiteralPath $Folder -ErrorAction SilentlyContinue).Path) {
    Fail "-Folder must be a different folder from the master ($Master): two sessions must never share one working tree."
}

# --- 1. clone or update ---------------------------------------------------------------------------------------
Step "Repository"
$url = (git -C $Master remote get-url origin).Trim()
if (-not (Test-Path (Join-Path $Folder ".git"))) {
    if ((Test-Path $Folder) -and (Get-ChildItem $Folder -Force | Select-Object -First 1)) {
        Fail "$Folder exists, is not empty and is not a git clone. Move it away or pass another -Folder."
    }
    git clone --branch $Branch $url $Folder
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed" }
}
Set-Location $Folder
if ((git remote get-url origin).Trim() -ne $url) { Fail "$Folder is a clone of another repository." }

$dirty = git status --porcelain
if ($dirty) {
    Write-Host "Uncommitted changes in $Folder (nothing was pulled):" -ForegroundColor Yellow; $dirty
    Fail "commit and push them from the session that made them, or discard them, then run again."
}
git fetch origin $Branch --tags
if ($LASTEXITCODE -ne 0) { Fail "git fetch failed (network?)" }
git rev-parse --verify --quiet "refs/heads/$Branch" | Out-Null
if ($LASTEXITCODE -eq 0) { git switch $Branch } else { git switch -c $Branch --track "origin/$Branch" }
if ($LASTEXITCODE -ne 0) { Fail "cannot switch to $Branch" }
$ahead = [int](git rev-list --count "origin/$Branch..HEAD")
if ($ahead -gt 0) { Fail "$ahead local commit(s) not on GitHub. Push them (git push origin $Branch) and run again." }
git pull --ff-only origin $Branch
if ($LASTEXITCODE -ne 0) { Fail "fast-forward pull failed" }
Write-Host "folder : $Folder"
Write-Host "branch : $Branch at $(git rev-parse --short HEAD) (origin: $(git rev-parse --short origin/$Branch))"
Write-Host "tag    : s0-s11-certified at $(git rev-parse --short --verify --quiet s0-s11-certified)"

# git identity for commits made in this folder (copied from the master clone once)
foreach ($key in @("user.name", "user.email")) {
    if (-not (git config --local $key)) {
        $value = git -C $Master config $key
        if ($value) { git config --local $key $value } else { $problems += "git $key is not set (git config $key ...)" }
    }
}

# --- 2. own virtual environment --------------------------------------------------------------------------------
Step "Python environment"
if (-not (Test-Path ".\.venv\Scripts\python.exe")) { python -m venv .venv; if ($LASTEXITCODE -ne 0) { Fail "python -m venv failed" } }
$py = (Resolve-Path ".\.venv\Scripts\python.exe").Path
$where = & $py -c "import adapters, os; print(os.path.abspath(adapters.__file__))" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $where -or -not $where.StartsWith((Resolve-Path $Folder).Path)) {
    # missing, or an editable install that points at another folder: install this folder's code
    & $py -m pip install --quiet --upgrade pip
    & $py -m pip install --quiet -e ".[dev]"
    if ($LASTEXITCODE -ne 0) { Fail "pip install -e .[dev] failed" }
    $where = & $py -c "import adapters, os; print(os.path.abspath(adapters.__file__))"
}
Write-Host "python : $(& $py --version) ($py)"
Write-Host "code   : imported from $where"

# --- 3. .env with only the test database -----------------------------------------------------------------------
Step "Test database"
function Get-EnvValue($file, $name) {
    if (-not (Test-Path $file)) { return $null }
    $text = Get-Content $file -Raw -Encoding UTF8
    if ($text -match "(?m)^\s*(?:export\s+)?$name\s*=\s*(\S+)") { return $Matches[1].Trim('"').Trim("'") }
    return $null
}
$test = Get-EnvValue ".env" "TEST_DATABASE_URL"
if (-not $test) {
    $test = Get-EnvValue (Join-Path $Master ".env") "TEST_DATABASE_URL"
    if (-not $test) { Fail "TEST_DATABASE_URL is not in $Master\.env; add it there (a database whose name ends in _test)." }
    if ($TestDatabase) { $test = $test -replace '/[^/?]+(\?|$)', "/$TestDatabase`$1" }
    # only the test database: this folder never needs the dev database or the model key
    "TEST_DATABASE_URL=$test" | Out-File -Encoding utf8 ".env"
    Write-Host "wrote .env with TEST_DATABASE_URL only (value not shown)"
}
if ($test -notmatch "_test(\?|$)") { Fail "TEST_DATABASE_URL must name a database ending in _test." }
$env:TEST_DATABASE_URL = $test
& $py -c "import asyncio, os, asyncpg; from adapters.postgres.database import normalize_url; c = asyncio.run(asyncpg.connect(normalize_url(os.environ['TEST_DATABASE_URL']))); print('server : PostgreSQL', c.get_server_version().major); asyncio.run(c.close())"
if ($LASTEXITCODE -ne 0) { Fail "cannot connect to the test database (does it exist? is PostgreSQL running?)." }

# --- 4. checks -------------------------------------------------------------------------------------------------
Step "S12 tooling"
& $py tools\owner_certify_s12.py --selftest
if ($LASTEXITCODE -ne 0) { $problems += "owner_certify_s12.py --selftest" }
& $py tools\s12_tracker.py check
if ($LASTEXITCODE -ne 0) { $problems += "s12_tracker.py check" }
& $py tools\doc_consistency.py
if ($LASTEXITCODE -ne 0) { $problems += "doc_consistency.py (see CONFLICT lines)" }

if ($RunGolden) {
    Step "Golden files (red until each milestone is built)"
    Get-ChildItem tests_golden\s12\M*.py | Sort-Object Name | ForEach-Object {
        $line = & $py -m pytest $_.FullName -q -p no:cacheprovider -o addopts= 2>&1 | Select-Object -Last 1
        Write-Host ("{0,-40} {1}" -f $_.Name, $line)
    }
}

Step "Result"
if ($problems) {
    Write-Host "NOT READY:" -ForegroundColor Red; $problems | ForEach-Object { Write-Host "  - $_" }; exit 1
}
Write-Host "READY: $Folder is at $(git rev-parse --short HEAD), same as GitHub." -ForegroundColor Green
Write-Host "Open this folder in the second Claude Code account and paste the prompt from docs\gates\S12_TEST_AUTHOR_BRIEF.md."
