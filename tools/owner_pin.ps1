# owner_pin.ps1 — run by the OWNER after AUTOPILOT Step 0 reports "STEP 0 DONE".
# Pins the certifier and the spec documents, then commits.
$ErrorActionPreference = "Stop"
Set-Location "C:\Users\Administrator\Documents\1SuperAgents"

$expected = "E5D5AB0D99D7D427B965526C3D7309BBF46127D7FE31B4416E03860C5748F4DF"
$actual = (Get-FileHash tools\owner_certify.py -Algorithm SHA256).Hash
if ($actual -ne $expected) {
    throw "tools\owner_certify.py is not the owner version (hash $actual). Copy the downloaded file into tools\ first."
}
$actual | Out-File -Encoding ascii docs\gates\owner_certify.sha256

foreach ($rule in @("tools/owner_certify.py -text", "docs/implementation/*.md -text")) {
    if (-not (Test-Path .gitattributes) -or -not (Select-String -Path .gitattributes -SimpleMatch $rule -Quiet)) {
        Add-Content .gitattributes $rule
    }
}

$golden = @("tests/stages/test_s6_task_profile.py",
            "tests/stages/test_s7_path_routing.py",
            "tests/stages/test_s9_plan_creation.py",
            "tests/stages/test_s10_confirmation.py",
            "tests/stages/test_s11_plan_validation.py",
            "tests/stages/test_s7_to_s11.py")
foreach ($g in $golden) {
    if (-not (Test-Path $g)) { throw "Golden test file missing: $g" }
    $rule = "$g -text"
    if (-not (Select-String -Path .gitattributes -SimpleMatch $rule -Quiet)) { Add-Content .gitattributes $rule }
}
$pins = @()
$pins += Get-ChildItem docs\implementation\*.md | Sort-Object Name | ForEach-Object {
    "{0}  docs/implementation/{1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash, $_.Name
}
$pins += $golden | ForEach-Object { "{0}  {1}" -f (Get-FileHash $_ -Algorithm SHA256).Hash, $_ }
$pins | Out-File -Encoding ascii docs\gates\spec_pins.sha256

python tools\owner_certify.py --selftest
if ($LASTEXITCODE -ne 0) { throw "Certifier self-test failed. Do not continue." }

git add .gitattributes tools\owner_certify.py docs\gates tests\stages\test_s6_task_profile.py tests\stages\test_s7_path_routing.py tests\stages\test_s9_plan_creation.py tests\stages\test_s10_confirmation.py tests\stages\test_s11_plan_validation.py tests\stages\test_s7_to_s11.py tools\owner_pin.ps1 tools\owner_verify.ps1
git commit -m "Owner: pin certifier, spec documents and golden tests"
Write-Host ""
Write-Host "Pinned. Now tell the agent:  continue per AUTOPILOT" -ForegroundColor Green
