<#
.SYNOPSIS
    Writes PLATFORM_SOURCE.json into the platform folder: which commit of our source it was copied from.

.DESCRIPTION
    The platform folder of a client install carries no .git of ours (docs\VDI-SETUP.md Part 1). This file is how
    every preparation and verification names our release: the source commit, its tag when it has one, and the date
    the copy was made (app\experiment\instrument.py reads it). scripts\update-platform.ps1 writes it on every update;
    run this once by hand after the first copy.

    Reads the source folder with git; changes nothing there.

.PARAMETER Source
    The source folder: the clone of our repository the platform was copied from.

.PARAMETER Platform
    The platform folder. Default: the folder this script is in, one level up.

.PARAMETER Previous
    The source commit the platform folder held before this copy, when there was one (recorded, for the history).

.EXAMPLE
    .\scripts\write-platform-source.ps1 -Source C:\MP\source
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Source,
    [string]$Platform = '',
    [string]$Previous = ''
)

$ErrorActionPreference = 'Continue'   # git writes to stderr; exit codes are checked instead
# Windows PowerShell 5.1 has no $PSScriptRoot in a parameter's default value: the default is worked out here.
if (-not $Platform) { $Platform = Split-Path -Parent $PSScriptRoot }
$commit = & git -C $Source rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or -not $commit) {
    Write-Host "$Source is not a git clone of our repository: there is no commit to record." -ForegroundColor Red
    exit 1
}
$commit = "$commit".Trim()
# Its release tag: release-N, or the older <prefix>-release-N of releases 1 to 6. Any other tag is not a release.
$tag = & git -C $Source describe --tags --exact-match --match 'release-*' --match '*-release-*' HEAD 2>$null
if ($LASTEXITCODE -ne 0 -or -not $tag) { $tag = $null } else { $tag = "$tag".Trim() }
$branch = "$(& git -C $Source rev-parse --abbrev-ref HEAD)".Trim()

$record = [ordered]@{
    commit         = $commit
    tag            = $tag
    branch         = $branch
    date           = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    previousCommit = $(if ($Previous) { $Previous } else { $null })
    note           = 'Written by scripts\update-platform.ps1 (or write-platform-source.ps1): the commit of our source this folder was copied from. Do not edit.'
}
$json = ($record | ConvertTo-Json) -replace "`r`n", "`n"
[IO.File]::WriteAllText((Join-Path $Platform 'PLATFORM_SOURCE.json'), $json + "`n", (New-Object Text.UTF8Encoding($false)))
Write-Host "PLATFORM_SOURCE.json: $commit$(if ($tag) { " ($tag)" })"
