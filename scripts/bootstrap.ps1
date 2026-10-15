<#
.SYNOPSIS
    Sets the platform up on a fresh machine (01-ENVIRONMENT-SETUP.md section 10).

.DESCRIPTION
    Each stage stops the script with a plain message if it fails:

      1. Preflight: tools, package sources, RUNS_DIR (scripts\preflight.py --no-database)
      2. The Python virtual environment, backend\.venv
      3. Python dependencies, from PIP_INDEX_URL when set
      4. Preflight: the database (connection, the right to create the schema)
      5. Frontend dependencies, from NPM_REGISTRY when set
      6. The C# step programs, built and published, restoring from NUGET_SOURCES when set
      7. Migration: every table in DB_SCHEMA
      8. Seed: platform configuration, and the catalog from the committed export

    Reads backend\.env (copy backend\.env.example and fill it in first). DB_USER and DB_PASSWORD may come from the
    environment instead; they are never printed. Safe to run again: each stage brings the machine up to date.

.PARAMETER Python
    The Python 3.11+ to create the virtual environment with. Default: py -3, else python.

.EXAMPLE
    .\scripts\bootstrap.ps1
#>
[CmdletBinding()]
param([string]$Python = '')

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$steps = Join-Path $root 'steps\step-003-fingerprinting'
$venvPython = Join-Path $backend '.venv\Scripts\python.exe'

function Stage([int]$n, [string]$what) { Write-Host ""; Write-Host "== $n. $what" -ForegroundColor Cyan }
function Fail([int]$n, [string]$why) {
    Write-Host "Stage $n failed: $why" -ForegroundColor Red
    Write-Host 'Nothing after this stage was done. Fix the cause and run .\scripts\bootstrap.ps1 again.'
    exit $n
}
function EnvValue([string]$name) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ($value) { return $value }
    $file = Join-Path $backend '.env'
    if (Test-Path $file) {
        foreach ($line in Get-Content $file) {
            if ($line -match "^\s*$name\s*=\s*(.*?)\s*$") { return $Matches[1].Trim('"').Trim("'") }
        }
    }
    return ''
}

if (-not (Test-Path (Join-Path $backend '.env'))) {
    Fail 0 "backend\.env does not exist. Copy backend\.env.example to backend\.env and fill it in (DB_HOST, DB_PORT, DB_NAME, DB_SCHEMA, RUNS_DIR; DB_USER and DB_PASSWORD there or in the environment)."
}
if (-not $Python) {
    if (Get-Command py -ErrorAction SilentlyContinue) { $Python = 'py -3' } else { $Python = 'python' }
}
$pythonParts = $Python -split ' '
$pythonExe = $pythonParts[0]
$pythonArgs = @($pythonParts | Select-Object -Skip 1)

Stage 1 'Preflight: tools, package sources, RUNS_DIR'
& $pythonExe @pythonArgs (Join-Path $PSScriptRoot 'preflight.py') --no-database
if ($LASTEXITCODE -ne 0) { Fail 1 'a prerequisite is missing (listed above as MISSING).' }

Stage 2 'Python virtual environment'
if (-not (Test-Path $venvPython)) {
    & $pythonExe @pythonArgs -m venv (Join-Path $backend '.venv')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) { Fail 2 "could not create backend\.venv with '$Python'." }
    Write-Host 'created backend\.venv'
} else { Write-Host 'backend\.venv exists' }

Stage 3 'Python dependencies'
$pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '-r', (Join-Path $backend 'requirements.txt'))
$index = EnvValue 'PIP_INDEX_URL'
if ($index) { $pipArgs += @('--index-url', $index); Write-Host "from $index" }
& $venvPython @pipArgs
if ($LASTEXITCODE -ne 0) { Fail 3 'pip could not install backend\requirements.txt (see the message above).' }
Write-Host 'installed'

Stage 4 'Preflight: the database'
& $venvPython (Join-Path $PSScriptRoot 'preflight.py') --database
if ($LASTEXITCODE -ne 0) { Fail 4 'the database is not reachable, or this login cannot create the schema (listed above as MISSING).' }

Stage 5 'Frontend dependencies'
Push-Location $frontend
try {
    $npmArgs = @('ci', '--no-audit', '--no-fund')
    $registry = EnvValue 'NPM_REGISTRY'
    if ($registry) { $npmArgs += @('--registry', $registry); Write-Host "from $registry" }
    & npm @npmArgs
    if ($LASTEXITCODE -ne 0) { Fail 5 'npm ci failed (see the message above).' }
} finally { Pop-Location }

Stage 6 'C# step programs: build and publish'
$sourceArgs = @()
foreach ($source in ((EnvValue 'NUGET_SOURCES') -split ',' | Where-Object { $_.Trim() })) { $sourceArgs += @('--source', $source.Trim()) }
if ($sourceArgs.Count -gt 0) { Write-Host "restoring from $((EnvValue 'NUGET_SOURCES'))" }
$programs = @(
    @('Fingerprinting.Cli', 'publish'),
    @('Fingerprinting.EntryPoints.Cli', 'publish\entry-point-inventory'),
    @('Fingerprinting.Impact.Cli', 'publish\impact-analysis'),
    @('Fingerprinting.Dependencies.Cli', 'publish\dependency-assessment'),
    @('Fingerprinting.Outbound.Cli', 'publish\outbound-invocation-inventory'),
    @('Fingerprinting.TestCoverage.Cli', 'publish\test-coverage-assessment')
)
Push-Location $steps
try {
    foreach ($p in $programs) {
        Write-Host "  $($p[0]) -> $($p[1])"
        & dotnet publish (Join-Path 'src' $p[0]) -c Release -o $p[1] -nologo -v quiet @sourceArgs | Out-Null
        if ($LASTEXITCODE -ne 0) { Fail 6 "dotnet publish of $($p[0]) failed. Run it by hand to see why: dotnet publish src\$($p[0]) -c Release -o $($p[1])" }
    }
} finally { Pop-Location }

Stage 7 'Migration'
Push-Location $backend
try {
    & $venvPython -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Fail 7 'alembic upgrade head failed (see the message above).' }

    Stage 8 'Seed: platform configuration and the catalog'
    & $venvPython -m app.seed
    if ($LASTEXITCODE -ne 0) { Fail 8 'python -m app.seed failed (see the message above).' }
} finally { Pop-Location }

Write-Host ''
Write-Host 'Bootstrap complete.' -ForegroundColor Green
Write-Host 'Start the backend from its own terminal:'
Write-Host "  cd $backend; .venv\Scripts\Activate.ps1; uvicorn app.main:app --reload --port $(if (EnvValue 'API_PORT') { EnvValue 'API_PORT' } else { '8001' })"
Write-Host 'and the frontend from another:'
Write-Host "  cd $frontend; npm run dev"
