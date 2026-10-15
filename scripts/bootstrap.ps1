<#
.SYNOPSIS
    Sets the platform up on a fresh machine, or brings it up to date (docs\VDI-SETUP.md).

.DESCRIPTION
    Eight stages. Each stops the script with a plain message if it fails, and each skips work already done, so the
    script is safe to run again at any time:

      1. Preflight: tools, package sources, RUNS_DIR     always runs (seconds)
      2. The Python virtual environment, backend\.venv   skipped when it exists
      3. Python dependencies                             skipped when requirements.txt, PIP_INDEX_URL and the
                                                         Python version are unchanged since the last install
      4. Preflight: the database                         always runs (seconds)
      5. Frontend: frontend\.env and dependencies        .env written only when missing; npm ci skipped when
                                                         package-lock.json and NPM_REGISTRY are unchanged
      6. The six C# step programs, built and published   each skipped when its sources, the SDK version and
                                                         NUGET_SOURCES are unchanged since it was published
      7. Migration into DB_SCHEMA                        alembic upgrade head; nothing to do when at head
      8. Seed: platform configuration and the catalog    a reseed changes only what changed (CLAUDE.md rule 10)

    What a stage last did is recorded in a small stamp file beside its output (backend\.venv\.bootstrap-stamp,
    frontend\node_modules\.bootstrap-stamp, steps\step-003-fingerprinting\publish\...\.bootstrap-stamp). -Force
    ignores the stamps.

    Reads backend\.env (copy backend\.env.example and fill it in first). DB_USER and DB_PASSWORD may come from the
    environment instead; they are never printed.

.PARAMETER Python
    The Python 3.11 to 3.14 to create the virtual environment with: a full path, or a command. Default: py -3, else
    python.

.PARAMETER Stage
    Run only this stage (1 to 8). Stages 3, 4, 7 and 8 need the virtual environment from stage 2.

.PARAMETER Force
    Redo the work of each stage run, even when its stamp says it is up to date. Stage 2 still keeps an existing
    virtual environment: delete backend\.venv to rebuild it.

.EXAMPLE
    .\scripts\bootstrap.ps1
.EXAMPLE
    .\scripts\bootstrap.ps1 -Python C:\Users\me\Tools\Python314\python.exe
.EXAMPLE
    .\scripts\bootstrap.ps1 -Stage 6 -Force
#>
[CmdletBinding()]
param(
    [string]$Python = '',
    [ValidateRange(0, 8)][int]$Stage = 0,
    [switch]$Force
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$steps = Join-Path $root 'steps\step-003-fingerprinting'
$venv = Join-Path $backend '.venv'
$venvPython = Join-Path $venv 'Scripts\python.exe'

function Run([int]$n) { return ($Stage -eq 0 -or $Stage -eq $n) }
function Header([int]$n, [string]$what) {
    Write-Host ''
    Write-Host "== $n. $what" -ForegroundColor Cyan
    $script:stageStart = Get-Date
}
function Done([string]$what) {
    $seconds = [int]((Get-Date) - $script:stageStart).TotalSeconds
    Write-Host "$what ($seconds s)"
}
function Fail([int]$n, [string]$why) {
    Write-Host "Stage $n failed: $why" -ForegroundColor Red
    Write-Host "Fix the cause, then run this stage again: .\scripts\bootstrap.ps1 -Stage $n"
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
function TextHash([string]$text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text))
    return ([System.BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}
function FilesHash([string[]]$paths) {
    $lines = foreach ($p in $paths) {
        Get-ChildItem $p -Recurse -File | Where-Object { $_.FullName -notmatch '\\(bin|obj)\\' } | Sort-Object FullName |
            ForEach-Object { "$($_.FullName.Substring($root.Length)):$((Get-FileHash -Algorithm SHA256 $_.FullName).Hash)" }
    }
    return TextHash ($lines -join "`n")
}
function Stamped([string]$file, [string]$value) {
    return (-not $Force) -and (Test-Path $file) -and ((Get-Content $file -Raw).Trim() -eq $value)
}
function Stamp([string]$file, [string]$value) { Set-Content -Path $file -Value $value -Encoding ascii }
function NeedVenv([int]$n) {
    if (-not (Test-Path $venvPython)) { Fail $n 'backend\.venv does not exist yet. Run stage 2 first: .\scripts\bootstrap.ps1 -Stage 2' }
}

if (-not (Test-Path (Join-Path $backend '.env'))) {
    Write-Host 'backend\.env does not exist. Copy backend\.env.example to backend\.env and fill it in (docs\VDI-SETUP.md, section F).' -ForegroundColor Red
    exit 9
}
if (-not $Python) {
    if (Get-Command py -ErrorAction SilentlyContinue) { $Python = 'py -3' } else { $Python = 'python' }
}
if (Test-Path -LiteralPath $Python) { $pythonExe = $Python; $pythonArgs = @() }
else {
    $pythonParts = $Python -split ' '
    $pythonExe = $pythonParts[0]
    $pythonArgs = @($pythonParts | Select-Object -Skip 1)
}
$started = Get-Date

if (Run 1) {
    Header 1 'Preflight: tools, package sources, RUNS_DIR'
    & $pythonExe @pythonArgs (Join-Path $PSScriptRoot 'preflight.py') --no-database
    if ($LASTEXITCODE -ne 0) { Fail 1 'a prerequisite is missing (listed above as MISSING).' }
    Done 'all present'
}

if (Run 2) {
    Header 2 'Python virtual environment'
    if (Test-Path $venvPython) {
        Done "backend\.venv exists ($(& $venvPython -c 'import sys; print(sys.version.split()[0])')); kept. Delete it to rebuild with another Python"
    } else {
        & $pythonExe @pythonArgs -m venv $venv
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) { Fail 2 "could not create backend\.venv with '$Python'." }
        Done "created backend\.venv ($(& $venvPython -c 'import sys; print(sys.version.split()[0])'))"
    }
}

if (Run 3) {
    Header 3 'Python dependencies'
    NeedVenv 3
    $index = EnvValue 'PIP_INDEX_URL'
    $requirements = Join-Path $backend 'requirements.txt'
    $stampFile = Join-Path $venv '.bootstrap-stamp'
    $want = TextHash "$((Get-FileHash -Algorithm SHA256 $requirements).Hash)|$index|$(& $venvPython -c 'import sys; print(sys.version)')"
    if (Stamped $stampFile $want) {
        Done 'up to date: requirements.txt unchanged since the last install'
    } else {
        $pipArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '-q', '--only-binary=:all:', '-r', $requirements)
        if ($index) { $pipArgs += @('--index-url', $index); Write-Host "from $index" }
        & $venvPython @pipArgs
        if ($LASTEXITCODE -ne 0) { Fail 3 'pip could not install backend\requirements.txt from wheels (see the message above).' }
        Stamp $stampFile $want
        Done 'installed'
    }
}

if (Run 4) {
    Header 4 'Preflight: the database'
    NeedVenv 4
    & $venvPython (Join-Path $PSScriptRoot 'preflight.py') --database
    if ($LASTEXITCODE -ne 0) { Fail 4 'the database is not reachable, or this login cannot create the schema (listed above as MISSING).' }
    Done 'all present'
}

if (Run 5) {
    Header 5 'Frontend: frontend\.env and dependencies'
    $frontendEnv = Join-Path $frontend '.env'
    if (-not (Test-Path $frontendEnv)) {
        $apiHost = if (EnvValue 'API_HOST') { EnvValue 'API_HOST' } else { '127.0.0.1' }
        $apiPort = if (EnvValue 'API_PORT') { EnvValue 'API_PORT' } else { '8001' }
        Set-Content -Path $frontendEnv -Value "VITE_API_BASE_URL=http://${apiHost}:${apiPort}" -Encoding ascii
        Write-Host "wrote frontend\.env: the backend at http://${apiHost}:${apiPort}"
    } else { Write-Host 'frontend\.env exists; kept' }
    $registry = EnvValue 'NPM_REGISTRY'
    $stampFile = Join-Path $frontend 'node_modules\.bootstrap-stamp'
    $want = TextHash "$((Get-FileHash -Algorithm SHA256 (Join-Path $frontend 'package-lock.json')).Hash)|$registry"
    if (Stamped $stampFile $want) {
        Done 'up to date: package-lock.json unchanged since the last npm ci'
    } else {
        Push-Location $frontend
        try {
            $npmArgs = @('ci', '--no-audit', '--no-fund')
            if ($registry) { $npmArgs += @('--registry', $registry); Write-Host "from $registry" }
            & npm @npmArgs
            if ($LASTEXITCODE -ne 0) { Fail 5 'npm ci failed (see the message above).' }
        } finally { Pop-Location }
        Stamp $stampFile $want
        Done 'installed'
    }
}

if (Run 6) {
    Header 6 'C# step programs: build and publish'
    $sourceArgs = @()
    foreach ($source in ((EnvValue 'NUGET_SOURCES') -split ',' | Where-Object { $_.Trim() })) { $sourceArgs += @('--source', $source.Trim()) }
    if ($sourceArgs.Count -gt 0) { Write-Host "restoring from $((EnvValue 'NUGET_SOURCES'))" }
    Push-Location $steps
    try {
        $sdk = (& dotnet --version 2>$null)
        if ($LASTEXITCODE -ne 0 -or -not $sdk) { Fail 6 'dotnet was not found, or no SDK fits global.json (run preflight).' }
        Write-Host "SDK $sdk"
        $sources = FilesHash @((Join-Path $steps 'src'), (Join-Path $steps 'schemas'), (Join-Path $steps 'global.json'))
        $want = TextHash "$sources|$sdk|$(EnvValue 'NUGET_SOURCES')"
        $programs = @(
            @('Fingerprinting.Cli', 'publish', 'Fingerprinting.Cli.exe'),
            @('Fingerprinting.EntryPoints.Cli', 'publish\entry-point-inventory', 'EntryPointInventory.Cli.exe'),
            @('Fingerprinting.Impact.Cli', 'publish\impact-analysis', 'ImpactAnalysis.Cli.exe'),
            @('Fingerprinting.Dependencies.Cli', 'publish\dependency-assessment', 'DependencyAssessment.Cli.exe'),
            @('Fingerprinting.Outbound.Cli', 'publish\outbound-invocation-inventory', 'OutboundInvocationInventory.Cli.exe'),
            @('Fingerprinting.TestCoverage.Cli', 'publish\test-coverage-assessment', 'TestCoverageAssessment.Cli.exe')
        )
        $published = 0
        foreach ($p in $programs) {
            $stampFile = Join-Path $p[1] ".bootstrap-stamp-$($p[0])"
            $exe = Join-Path $p[1] $p[2]
            if ((Test-Path $exe) -and (Stamped $stampFile $want)) { Write-Host "  $($p[0]): up to date"; continue }
            Write-Host "  $($p[0]) -> $($p[1])"
            & dotnet publish (Join-Path 'src' $p[0]) -c Release -o $p[1] -nologo -v quiet @sourceArgs | Out-Null
            if ($LASTEXITCODE -ne 0) { Fail 6 "dotnet publish of $($p[0]) failed. Run it by hand to see why: cd steps\step-003-fingerprinting; dotnet publish src\$($p[0]) -c Release -o $($p[1])" }
            if (-not (Test-Path $exe)) { Fail 6 "dotnet publish of $($p[0]) did not produce $exe." }
            Stamp $stampFile $want
            $published++
        }
    } finally { Pop-Location }
    Done "$published published, $($programs.Count - $published) up to date"
}

if (Run 7) {
    Header 7 'Migration'
    NeedVenv 7
    Push-Location $backend
    try {
        & $venvPython -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { Fail 7 'alembic upgrade head failed (see the message above).' }
    } finally { Pop-Location }
    Done 'at head'
}

if (Run 8) {
    Header 8 'Seed: platform configuration and the catalog'
    NeedVenv 8
    Push-Location $backend
    try {
        & $venvPython -m app.seed
        if ($LASTEXITCODE -ne 0) { Fail 8 'python -m app.seed failed (see the message above).' }
    } finally { Pop-Location }
    Done 'seeded'
}

Write-Host ''
if ($Stage -ne 0) {
    Write-Host "Stage $Stage complete ($([int]((Get-Date) - $started).TotalSeconds) s)." -ForegroundColor Green
    exit 0
}
Write-Host "Bootstrap complete ($([int]((Get-Date) - $started).TotalSeconds) s)." -ForegroundColor Green
Write-Host 'Start the backend from its own terminal:'
Write-Host "  cd $backend; .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port $(if (EnvValue 'API_PORT') { EnvValue 'API_PORT' } else { '8001' })"
Write-Host 'and the frontend from another:'
Write-Host "  cd $frontend; npm run dev -- --port 5174 --strictPort"
