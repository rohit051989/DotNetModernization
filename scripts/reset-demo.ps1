<#
.SYNOPSIS
    Resets client and repository data to a clean slate, keeping the catalog.

.DESCRIPTION
    Clears every engagement and everything scoped to one, every repository
    and everything derived from it (steps 2 to 6), all workflow history, the
    validation queue and backend\runs. Then creates the demo engagements
    TestClientA and TestClientB (Linux / OpenShift Container Platform 4,
    lift-and-shift) and verifies the result.

    Keeps: catalog_items and item_resolutions, the signal registry and
    extractors, step registrations and job definitions, global step
    policies, catalog_revisions, and the legacy patterns and
    target_state_options.

    Refuses to run while a workflow job is in flight or another database
    session holds an open transaction (uvicorn mid-request, for instance).
    Warns if uvicorn is listening. Stopping uvicorn first is the safe default.

    Takes a full pg_dump first, by default, to a folder OUTSIDE the
    repository (%LOCALAPPDATA%\ModernizationPlatform\backups). A backup
    directory inside the repository is refused: a database dump holds
    client data and must never be committed.

    The seed creates no engagements, so `python -m app.seed` afterwards
    does not bring the old ones back. This is the only reset path: the
    seed has no --reset.

.PARAMETER Yes
    Skip the confirmation prompt.

.PARAMETER Force
    Proceed even when another session holds an open transaction.

.PARAMETER VerifyOnly
    Change nothing; print and check the current state.

.PARAMETER BackupDir
    Where the pre-reset pg_dump goes. Must be outside the repository.

.PARAMETER NoBackup
    Skip the pre-reset backup.

.EXAMPLE
    .\scripts\reset-demo.ps1

.EXAMPLE
    .\scripts\reset-demo.ps1 -Yes
#>
[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$Force,
    [switch]$VerifyOnly,
    [string]$BackupDir = (Join-Path $env:LOCALAPPDATA 'ModernizationPlatform\backups'),
    [switch]$NoBackup
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
# Resolve a relative -BackupDir against where the script was run from,
# before anything changes directory.
$BackupDir = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($BackupDir)
$backend = Join-Path $repoRoot 'backend'
$python = Join-Path $backend '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "Python virtual environment not found at $python. See docs\01-ENVIRONMENT-SETUP.md."
}

if ($VerifyOnly) {
    Push-Location $backend
    try { & $python -m app.seed.reset_demo --verify-only; exit $LASTEXITCODE } finally { Pop-Location }
}

# The database check in reset_demo is the real guard; this is an early,
# friendlier warning.
$uvicorn = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8000, 8001 }
if ($uvicorn) {
    Write-Warning "Something is listening on port $(($uvicorn.LocalPort | Sort-Object -Unique) -join ', ') (uvicorn?). The reset refuses if it holds an open transaction; restart it afterwards either way."
}

if (-not $Yes) {
    Write-Host 'This deletes every engagement, repository, scan result and workflow execution, and empties backend\runs.' -ForegroundColor Yellow
    Write-Host 'The catalog, signal registry, step registrations and job definitions are kept.' -ForegroundColor Yellow
    $answer = Read-Host "Type RESET to continue"
    if ($answer -cne 'RESET') {
        Write-Host 'Cancelled.'
        exit 1
    }
}

$forceArgument = @()
if ($Force) { $forceArgument = @('--force') }

Push-Location $backend
try {
    # Refuse before taking a backup, not after.
    & $python -m app.seed.reset_demo --preflight-only @forceArgument
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Reset refused: nothing was changed.' -ForegroundColor Red
        exit $LASTEXITCODE
    }

    if (-not $NoBackup) {
        $target = $BackupDir
        $root = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
        if ($target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase) -or $target -eq $root.TrimEnd('\')) {
            throw "Backup directory $target is inside the repository. A dump holds client data and must never be committed; choose a folder outside $root."
        }
        New-Item -ItemType Directory -Force -Path $target | Out-Null

        # Container, user and database from docker\docker-compose.yml's catalog-db service.
        $container = 'modernization-catalog-db'
        $file = "pre-reset-$(Get-Date -Format 'yyyyMMdd-HHmmss').dump"
        docker exec $container pg_dump -U catalog -d modernization_catalog -Fc -f "/tmp/$file"
        if ($LASTEXITCODE -ne 0) { throw "pg_dump failed in container $container; nothing was reset. Use -NoBackup to skip the backup." }
        docker cp "${container}:/tmp/$file" (Join-Path $target $file) | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Copying the dump out of $container failed; nothing was reset." }
        docker exec $container rm -f "/tmp/$file" | Out-Null
        Write-Host "Backup: $(Join-Path $target $file)"
        Write-Host "  To restore: docker cp <file> ${container}:/tmp/r.dump; docker exec $container pg_restore -U catalog -d modernization_catalog --clean /tmp/r.dump"
    }

    & $python -m app.seed.reset_demo --yes @forceArgument
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($code -eq 0) {
    Write-Host 'Reset complete.' -ForegroundColor Green
}
elseif ($code -eq 3) {
    Write-Host 'Reset refused: nothing was changed.' -ForegroundColor Red
}
else {
    Write-Host "Reset finished with exit code $code; see the checks above." -ForegroundColor Red
}
exit $code
