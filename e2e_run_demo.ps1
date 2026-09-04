<#
End-to-end demo: steps 1-5 of the modernization pipeline against the
synthetic legacy-grpc-suite sample repo. Safe to re-run -- registration
steps upsert, and repo registration falls back to rescan automatically.

Steps 1-4 run for real (step 3's Fingerprinting.Cli.exe included, since
it's built and registered now). Step 5 reads whatever real fingerprint
data steps 1-4 produced -- no synthetic stand-in data involved any more.

Assumes: Docker Desktop running, the catalog Postgres container up
(docker compose -f docker\docker-compose.yml up -d), and uvicorn already
running on port 8001 in another terminal (uvicorn app.main:app --reload
--port 8001, run from backend\ with the venv active). Checked below
before anything else runs.

Run this from anywhere -- it cd's explicitly at each step and calls the
venv's python.exe directly by path, so it doesn't depend on Activate.ps1
having been run in this shell first.
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
    Write-Host ""
    Write-Host "(Also confirm Docker Desktop and the catalog DB container are up:" -ForegroundColor Yellow
    Write-Host "  docker compose -f docker\docker-compose.yml up -d )" -ForegroundColor Yellow
    exit 1
}

Step "1/5 Registering steps 1-5 with the engine"
Set-Location (Join-Path $RepoRoot "backend")
& $Py e2e_run\register_steps.py

Step "2/5 Activating the job definition"
& $Py e2e_run\store_job_v6.py

Step "3/5 Registering (or rescanning) the sample repo and running the job"
& $Py e2e_run\register_repo_and_run.py

Step "4/5 Running step 5 (pattern-discovery-clustering) standalone"
Set-Location (Join-Path $RepoRoot "steps\step-005-pattern-discovery")
Get-Content sample-context.json | & $Py main.py | Set-Content -Encoding utf8 step5-envelope.json
Get-Content step5-envelope.json

Step "5/5 Building the shareable result files"
Set-Location (Join-Path $RepoRoot "backend")
& $Py e2e_run\build_full_report.py
& $Py e2e_run\split_reports.py

Write-Host ""
Write-Host "Done. Results in D:\dotnet-modernization\_run-output\by-repository\legacy-grpc-suite\ and _run-output\engagement-wide\pattern-discovery\ (see _run-output\README.md)." -ForegroundColor Green
