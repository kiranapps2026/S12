# adopt_master_folder.ps1 - make C:\Users\Administrator\Documents\1SuperAgents the master working folder, identical to the
# GitHub branch s0-s11-repair. Nothing is deleted: the old folder is renamed to 1SuperAgents.old-<time> (keep it until you are
# sure, then delete it yourself). Your .env (secrets) is carried over. Then it installs, certifies and compares the hashes.
#
#   powershell -ExecutionPolicy Bypass -File C:\Users\Administrator\Documents\S12-repair\tools\adopt_master_folder.ps1
#   -HashesOnly   only compare the certifier hash with owner_verify.ps1 and docs\gates\owner_certify.sha256 (run after any
#                 certifier edit; if they differ, owner_verify.ps1 will say "certifier was modified")
# Close every terminal, editor and Python process that uses the old 1SuperAgents folder first (a rename fails while files are open).

param(
    [string]$Target = "C:\Users\Administrator\Documents\1SuperAgents",
    [string]$Source = "C:\Users\Administrator\Documents\S12-repair",
    [string]$Url = "https://github.com/kiranapps2026/S12.git",
    [string]$Branch = "s0-s11-repair",
    [switch]$HashesOnly
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"

function Show-Hashes([string]$Root) {
    $actual = (Get-FileHash (Join-Path $Root "tools\owner_certify.py") -Algorithm SHA256).Hash
    $stored = (Get-Content (Join-Path $Root "docs\gates\owner_certify.sha256") -Raw).Trim()
    $line = Select-String -Path (Join-Path $Root "tools\owner_verify.ps1") -Pattern '^\$expected\s*=\s*"([0-9A-Fa-f]+)"' | Select-Object -First 1
    $expected = if ($line) { $line.Matches[0].Groups[1].Value } else { "(not found)" }
    Write-Host "certifier file      : $actual"
    Write-Host "owner_verify.ps1    : $expected"
    Write-Host "docs\gates\*.sha256 : $stored"
    if (($actual -eq $expected) -and ($actual -eq $stored)) {
        Write-Host "HASHES AGREE" -ForegroundColor Green
        return $true
    }
    Write-Host "HASHES DIFFER: put the certifier file's hash into the other two (owner integrity edit) or restore the certifier." -ForegroundColor Red
    return $false
}

if ($HashesOnly) {
    $root = if (Test-Path (Join-Path $Target "tools\owner_certify.py")) { $Target } else { $Source }
    if (Show-Hashes $root) { exit 0 } else { exit 1 }
}

if ((Get-Location).Path -like "$Target*") { throw "Run this from another folder (for example: cd C:\Users\Administrator\Documents), not from inside $Target." }
foreach ($tool in "git", "python") { if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { throw "$tool is not on the PATH." } }

# 1. keep the secrets: the master folder's .env if it has one, else the one from the working copy
$envText = $null
foreach ($candidate in (Join-Path $Target ".env"), (Join-Path $Source ".env")) {
    if (-not $envText -and (Test-Path $candidate)) { $envText = Get-Content $candidate -Raw; Write-Host ".env taken from $candidate" }
}
if (-not $envText) { Write-Host "WARNING: no .env found in either folder; you will have to create one." -ForegroundColor Yellow }

# 2. move the old folder aside (never delete)
if (Test-Path $Target) {
    $backup = "$Target.old-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Rename-Item -Path $Target -NewName (Split-Path $backup -Leaf)
    Write-Host "old folder kept as $backup"
}

# 3. a fresh clone of the branch = exactly what is on GitHub
git clone --branch $Branch $Url $Target
Set-Location $Target
Write-Host "commit: $(git rev-parse --short HEAD) on $(git branch --show-current)"

# 4. secrets back in place (git-ignored, never committed)
if ($envText) { Set-Content -Path (Join-Path $Target ".env") -Value $envText -NoNewline -Encoding utf8 }

# 5. own virtual environment and an editable install that points at THIS folder
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
& .\.venv\Scripts\python.exe -m pip install --quiet -e ".[dev]"
[Environment]::SetEnvironmentVariable("PYTHONUTF8", "1", "User")     # the tests read source files as UTF-8; new windows pick it up
$imported = & .\.venv\Scripts\python.exe -c "import engine; print(engine.__file__)"
Write-Host "engine is imported from: $imported"
if ($imported -notlike "$Target*") { throw "the code is imported from somewhere else than $Target" }

# 6. certify and compare the hashes
& .\.venv\Scripts\python.exe tools\owner_certify.py
$certified = ($LASTEXITCODE -eq 0)
$agree = Show-Hashes $Target
$dirty = git status --porcelain

Write-Host ""
if ($certified -and $agree -and -not $dirty) {
    Write-Host "MASTER FOLDER READY: $Target at $(git rev-parse --short HEAD), certifier 19/19, hashes agree, tree clean." -ForegroundColor Green
    Write-Host "Next: powershell -ExecutionPolicy Bypass -File .\tools\sync_and_check.ps1 -Tests   then   .\tools\owner_verify.ps1"
    exit 0
}
if ($dirty) { Write-Host "Working tree is not clean:"; $dirty }
Write-Host "NOT READY: see the lines above." -ForegroundColor Yellow
exit 1
