<#
Runs step 5 (pattern-discovery-clustering) on its own, standalone -- no
job engine, no re-registration, just the step's real CLI contract against
whatever real fingerprint/classification data is already in Postgres.
This is the piece to narrate live: it's pure arithmetic (weighted-Jaccard
similarity + union-find clustering) reading straight from the database.

Assumes Docker Desktop and the catalog Postgres container are already up
(docker compose -f docker\docker-compose.yml up -d) -- this step talks to
Postgres directly, it does NOT need the backend/uvicorn running at all.
#>

$ErrorActionPreference = "Stop"
$RepoRoot = "D:\dotnet-modernization"
$Py = Join-Path $RepoRoot "backend\.venv\Scripts\python.exe"
$Step5Dir = Join-Path $RepoRoot "steps\step-005-pattern-discovery"

function Section($title) {
    Write-Host ""
    Write-Host "==> $title" -ForegroundColor Cyan
}

Section "Input: sample-context.json"
Get-Content (Join-Path $Step5Dir "sample-context.json")

Section "Running main.py (reads Postgres, scores, clusters, writes back)"
Set-Location $Step5Dir
$envelope = Get-Content sample-context.json | & $Py main.py
$envelope | Set-Content -Encoding utf8 step5-envelope.json

Section "StepResult envelope (what the engine would see on stdout)"
$envelope | ConvertFrom-Json | ConvertTo-Json -Depth 10

Section "Full clustering artifact (pattern-discovery-clusters.json)"
$artifactPath = ($envelope | ConvertFrom-Json).outputs[0].uri -replace '^file:///', ''
Get-Content $artifactPath | ConvertFrom-Json | ConvertTo-Json -Depth 10

Write-Host ""
Write-Host "Done." -ForegroundColor Green
