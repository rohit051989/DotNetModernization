<#
.SYNOPSIS
    Writes PLATFORM_SOURCE.json into the platform folder: which commit of our source it was copied from.

.DESCRIPTION
    The platform folder of a client install carries no .git of ours (docs\VDI-SETUP.md Part 1). This file is how
    every preparation and verification names what is installed: the source commit (installations follow our master),
    a tag only if one happens to point at that commit, and the date the copy was made (app\experiment\instrument.py reads it). scripts\update-platform.ps1 writes it on every update;
    run this once by hand after the first copy.

    Reads the source folder with git; changes nothing there.

.PARAMETER Source
    The source folder: the clone of our repository the platform was copied from.

.PARAMETER Platform
    The platform folder. Default: the folder this script is in, one level up.

.PARAMETER Previous
    The source commit the platform folder held before this copy, when there was one (recorded, for the history).

.PARAMETER Release
    Ignored. Older copies of scripts\update-platform.ps1, which installed release tags, pass it; installations now
    follow master, and the tag recorded is whichever tag points at the commit, if any.

.EXAMPLE
    .\scripts\write-platform-source.ps1 -Source C:\MP\source
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Source,
    [string]$Platform = '',
    [string]$Previous = '',
    [string]$Release = ''
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
# A tag, only if one happens to point at this commit: the owner tags milestones by hand; installations follow master.
$tag = & git -C $Source describe --tags --exact-match HEAD 2>$null
if ($LASTEXITCODE -ne 0 -or -not $tag) { $tag = $null } else { $tag = "$tag".Trim() }
$branch = "$(& git -C $Source rev-parse --abbrev-ref HEAD)".Trim()
if ($branch -eq 'HEAD') { $branch = $null }   # a commit checked out on its own: no branch

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
