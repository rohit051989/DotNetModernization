<#
.SYNOPSIS
    Runs every test suite of the platform, in this repository: backend, frontend (tests and type check), C#, and the
    step programs' Python tests. Exit code 0 only when all pass (CLAUDE.md rule 17: every commit on master passes
    them). scripts\import-client-changes.ps1 runs it before pushing master.

.DESCRIPTION
    Uses the repository's own environments: backend\.venv (bootstrap builds it) and frontend\node_modules. The
    backend suite runs in a scratch schema of its own (backend\tests\__init__.py), never touching the platform's data.
    Each suite's last lines are printed; a failing one is named at the end. Takes about twenty minutes.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\run-suites.ps1
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$failed = @()

function Invoke-Suite([string]$name, [string]$folder, [scriptblock]$run) {
    Write-Host "== $name" -ForegroundColor Cyan
    Push-Location $folder
    try {
        $output = & $run 2>&1 | ForEach-Object { "$_" }
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $output | Select-Object -Last 6 | ForEach-Object { Write-Host "   $_" }
    if ($code -ne 0) { $script:failed += $name }
}

if (-not (Test-Path $python)) {
    Write-Host "No backend\.venv: run scripts\bootstrap.ps1 first." -ForegroundColor Red
    exit 1
}
Invoke-Suite 'backend' (Join-Path $root 'backend') { & $python -m unittest discover -s tests -t . }
Invoke-Suite 'frontend tests' (Join-Path $root 'frontend') { & npm.cmd test }
Invoke-Suite 'frontend type check' (Join-Path $root 'frontend') { & npx.cmd tsc -b }
foreach ($project in Get-ChildItem (Join-Path $root 'steps') -Recurse -Filter '*Tests.csproj' | Sort-Object FullName) {
    Invoke-Suite "C# $($project.BaseName)" $project.DirectoryName { & dotnet test $project.FullName }
}
foreach ($tests in Get-ChildItem (Join-Path $root 'steps') -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'tests\__init__.py') }) {
    Invoke-Suite "step $($tests.Name)" $tests.FullName { & $python -m unittest discover -s tests }
}
$vendored = Join-Path $root 'third_party\code-modernization'
if (Test-Path (Join-Path $vendored 'scripts\tests')) {
    Invoke-Suite 'third_party code-modernization' $vendored { & $python -m unittest discover -s scripts/tests }
}

Write-Host ''
if ($failed.Count -gt 0) {
    Write-Host "Failed: $($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host 'All suites passed.' -ForegroundColor Green
exit 0
