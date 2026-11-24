<#
.SYNOPSIS
    The C# step programs and whether each is built and current: dot-sourced by scripts\bootstrap.ps1 (stage 6 builds
    them) and scripts\run-suites.ps1 (which will not run tests on programs that are missing or out of date).

.DESCRIPTION
    A program is current when its executable exists and its stamp (publish\...\.bootstrap-stamp-<project>, written by
    bootstrap stage 6 when it published it) matches a hash of the step's sources (src, schemas, global.json), the .NET
    SDK version and NUGET_SOURCES. Both scripts compute it here, so they agree on what "current" means.

    . (Join-Path $PSScriptRoot 'step-programs.ps1')
    $want = Get-StepProgramsWant -Root $root -Sdk $sdk -NugetSources $sources
    Get-StaleStepPrograms -Root $root -Want $want      # the programs that are not, with why
#>

# Project under src, its publish folder (relative to the step), the executable.
$StepPrograms = @(
    @('Fingerprinting.Cli', 'publish', 'Fingerprinting.Cli.exe'),
    @('Fingerprinting.EntryPoints.Cli', 'publish\entry-point-inventory', 'EntryPointInventory.Cli.exe'),
    @('Fingerprinting.Impact.Cli', 'publish\impact-analysis', 'ImpactAnalysis.Cli.exe'),
    @('Fingerprinting.Dependencies.Cli', 'publish\dependency-assessment', 'DependencyAssessment.Cli.exe'),
    @('Fingerprinting.Hierarchy.Cli', 'publish\dependency-hierarchy', 'DependencyHierarchy.Cli.exe'),
    @('Fingerprinting.Outbound.Cli', 'publish\outbound-invocation-inventory', 'OutboundInvocationInventory.Cli.exe'),
    @('Fingerprinting.TestCoverage.Cli', 'publish\test-coverage-assessment', 'TestCoverageAssessment.Cli.exe')
)
$StepProgramsFolder = 'steps\step-003-fingerprinting'

function TextHash([string]$text) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $bytes = $sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($text))
    return ([System.BitConverter]::ToString($bytes) -replace '-', '').ToLowerInvariant()
}

function FilesHash([string]$Root, [string[]]$Paths) {
    $lines = foreach ($p in $Paths) {
        Get-ChildItem $p -Recurse -File | Where-Object { $_.FullName -notmatch '\\(bin|obj)\\' } | Sort-Object FullName |
            ForEach-Object { "$($_.FullName.Substring($Root.Length)):$((Get-FileHash -Algorithm SHA256 $_.FullName).Hash)" }
    }
    return TextHash ($lines -join "`n")
}

function Get-StepProgramsWant([string]$Root, [string]$Sdk, [string]$NugetSources) {
    $steps = Join-Path $Root $StepProgramsFolder
    $sources = FilesHash $Root @((Join-Path $steps 'src'), (Join-Path $steps 'schemas'), (Join-Path $steps 'global.json'))
    return TextHash "$sources|$Sdk|$NugetSources"
}

function Get-StepProgramStamp([string]$Root, $Program) {
    return Join-Path (Join-Path (Join-Path $Root $StepProgramsFolder) $Program[1]) ".bootstrap-stamp-$($Program[0])"
}

function Get-BackendEnvValue([string]$Root, [string]$Name) {
    # As bootstrap reads it: the environment first, then backend\.env.
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { return $value }
    $file = Join-Path $Root 'backend\.env'
    if (Test-Path $file) {
        foreach ($line in Get-Content $file) {
            if ($line -match "^\s*$Name\s*=\s*(.*?)\s*$") { return $Matches[1].Trim('"').Trim("'") }
        }
    }
    return ''
}

function Get-StepProgramsWantHere([string]$Root) {
    # The SDK bootstrap builds with: DOTNET_ROOT's when backend\.env sets it (first on PATH, as bootstrap and the
    # backend put it), else the one on PATH; global.json in the step's folder picks the version.
    $dotnet = 'dotnet'
    $dotnetRoot = Get-BackendEnvValue $Root 'DOTNET_ROOT'
    if ($dotnetRoot -and (Test-Path (Join-Path $dotnetRoot 'dotnet.exe'))) { $dotnet = Join-Path $dotnetRoot 'dotnet.exe' }
    $sdk = ''
    Push-Location (Join-Path $Root $StepProgramsFolder)
    try { $sdk = "$(& $dotnet --version 2>$null)".Trim() } catch { } finally { Pop-Location }
    return Get-StepProgramsWant -Root $Root -Sdk $sdk -NugetSources (Get-BackendEnvValue $Root 'NUGET_SOURCES')
}

function Get-StaleStepPrograms([string]$Root, [string]$Want) {
    $steps = Join-Path $Root $StepProgramsFolder
    foreach ($p in $StepPrograms) {
        $exe = Join-Path (Join-Path $steps $p[1]) $p[2]
        $stamp = Get-StepProgramStamp $Root $p
        if (-not (Test-Path $exe)) {
            [pscustomobject]@{ Program = $p[0]; Why = "not built: $($p[1])\$($p[2]) does not exist" }
        } elseif (-not (Test-Path $stamp) -or ((Get-Content $stamp -Raw).Trim() -ne $Want)) {
            [pscustomobject]@{ Program = $p[0]; Why = 'out of date: its sources, the SDK or NUGET_SOURCES changed since it was published' }
        }
    }
}
