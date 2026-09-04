<#
Runs steps 1-5 against a REAL repo (not synthetic): VulnerableConsoleApp
from https://github.com/sandeeptulixolo/.NetCoreUpgrade, checked out at
D:\NetCoreUpgrade\.NetCoreUpgrade.

Notes going in:
  - Single .csproj repo (one application). Step 5 clustering needs 2+
    applications to compare against each other to form a NEW cluster, so
    this repo alone can only ever land as unclustered residue -- unless it
    happens to structurally match something else already in the engagement
    (client-a-ocp4), which it's registered into on purpose so the pipeline
    considers it alongside everything discovered so far.
  - Ships a .slnx solution file (the newer XML format). Step 2's solution
    scan only recognises classic .sln, so this repo will show
    solution_count: 0 -- that's expected, not a failure: step 2 discovers
    projects independently of solutions, so the .csproj is still found and
    fingerprinted as a standalone project.

Assumes: Docker Desktop + catalog Postgres up, uvicorn already running on
port 8001 in another terminal, and register_steps.py / store_job_v6.py
already applied at least once (this session's earlier steps 1-5 runs).

Output layout -- see D:\dotnet-modernization\_run-output\README.md:
  _run-output\by-repository\netcoreupgrade\full-e2e-result.json
  _run-output\by-repository\netcoreupgrade\step4-classification-result.json
  _run-output\engagement-wide\pattern-discovery\...   (shared across all repos)
#>

$ErrorActionPreference = "Stop"
$RepoRoot = "D:\dotnet-modernization"
$Py = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
$BackendUrl = "http://127.0.0.1:8001"

function Step($title) {
    Write-Host ""
    Write-Host "==> $title" -ForegroundColor Cyan
}

Step "0/5 Checking the backend is up at $BackendUrl"
try {
    $null = Invoke-WebRequest -Uri "$BackendUrl/openapi.json" -UseBasicParsing -TimeoutSec 3
    Write-Host "Backend is responding." -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "Backend is NOT responding at $BackendUrl." -ForegroundColor Red
    Write-Host "Start it first, in its own terminal, then re-run this:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  cd $RepoRoot\backend" -ForegroundColor Yellow
    Write-Host "  .venv\Scripts\Activate.ps1" -ForegroundColor Yellow
    Write-Host "  uvicorn app.main:app --reload --port 8001" -ForegroundColor Yellow
    exit 1
}

Step "1/5 Registering (or rescanning) the real repo and running steps 1-4"
Set-Location (Join-Path $RepoRoot "backend")
& $Py e2e_run\register_netcoreupgrade.py

Step "2/5 Re-running step 5 (pattern-discovery-clustering) -- engagement-wide, now includes this repo"
Set-Location (Join-Path $RepoRoot "steps\step-005-pattern-discovery")
Get-Content sample-context.json | & $Py main.py | Set-Content -Encoding utf8 step5-envelope.json
Get-Content step5-envelope.json

Step "3/5 Building the shareable result file for this repo"
Set-Location (Join-Path $RepoRoot "backend")
& $Py e2e_run\build_full_report_netcoreupgrade.py

Step "4/5 Splitting into per-repo + engagement-wide result files"
& $Py e2e_run\split_reports_netcoreupgrade.py

Step "5/5 Done"
Write-Host ""
Write-Host "Results in D:\dotnet-modernization\_run-output\by-repository\netcoreupgrade\ and _run-output\engagement-wide\pattern-discovery\ (see _run-output\README.md)." -ForegroundColor Green
