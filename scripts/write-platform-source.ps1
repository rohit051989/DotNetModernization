<#
.SYNOPSIS
    Writes PLATFORM_SOURCE.json into the platform folder: which commit of our source it was copied from.

.DESCRIPTION
    The platform folder of a client install carries no .git of ours (docs\VDI-SETUP.md Part 1). This file is how
    every preparation and verification names what is installed: the source commit (installations follow our master),
    a tag only if one happens to point at that commit, and the date the copy was made (app\experiment\instrument.py
    reads it), and every file the commit delivers (`files`), which preflight checks are tracked and on disk.
    scripts\update-platform.ps1 runs it on every delivery, the first included.

    Ours alone, like every path scripts\our-side-only.txt lists: it runs only from the source folder it reads (the
    pristine clone of our repository), never from a client's copy of the platform, and is never delivered.

    Reads the source folder with git; changes nothing there.

.PARAMETER Source
    The source folder: the clone of our repository the platform was copied from.

.PARAMETER Platform
    The platform folder, where PLATFORM_SOURCE.json is written.

.PARAMETER Previous
    The source commit the platform folder held before this copy, when there was one (recorded, for the history).

.PARAMETER Release
    Ignored. Older copies of scripts\update-platform.ps1, which installed release tags, pass it; installations now
    follow master, and the tag recorded is whichever tag points at the commit, if any.

.EXAMPLE
    C:\MP\source\scripts\write-platform-source.ps1 -Source C:\MP\source -Platform C:\MP\client\modernization-platform
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Platform,
    [string]$Previous = '',
    [string]$Release = ''
)

$ErrorActionPreference = 'Continue'   # git writes to stderr; exit codes are checked instead
# Only from the source folder it reads, compared as git sees the two folders.
$here = "$(& git -C $PSScriptRoot rev-parse --show-toplevel 2>$null)".Trim()
$sourceRoot = "$(& git -C $Source rev-parse --show-toplevel 2>$null)".Trim()
if (-not $here -or $here -ne $sourceRoot) {
    Write-Host ("This copy of write-platform-source.ps1 is not the source folder's: our delivery tooling runs only from our " +
        "side (docs\VDI-SETUP.md, `"Our delivery tooling stays on our side`"). Run $Source\scripts\write-platform-source.ps1.") -ForegroundColor Red
    exit 1
}
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
# When the commit was made: how a copy without our .git tells whether it is newer or older than the database's version
# (app\platform_version.py).
$committedAt = "$(& git -C $Source show -s --format=%cI HEAD)".Trim()
if (-not $committedAt) { $committedAt = $null }
# Every file this commit delivers: all of it but the paths ours alone (scripts\our-side-only.txt). Preflight checks
# on an installation, which has no history of ours, that each is tracked in the client's repository and on disk.
$ourSideOnly = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($line in @(& git -C $Source show 'HEAD:scripts/our-side-only.txt' 2>$null)) {
    $path = "$line".Trim().Replace('\', '/')
    if ($path -and -not $path.StartsWith('#')) { [void]$ourSideOnly.Add($path) }
}
$files = @(& git -C $Source -c core.quotepath=false ls-tree -r --name-only HEAD | ForEach-Object { "$_" } |
    Where-Object { -not $ourSideOnly.Contains($_) } | Sort-Object -CaseSensitive)

$record = [ordered]@{
    commit         = $commit
    tag            = $tag
    branch         = $branch
    date           = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
    committedAt    = $committedAt
    previousCommit = $(if ($Previous) { $Previous } else { $null })
    note           = 'Written by scripts\update-platform.ps1 (or write-platform-source.ps1): the commit of our source this folder was copied from. Do not edit.'
    files          = $files
}
$json = ($record | ConvertTo-Json) -replace "`r`n", "`n"
[IO.File]::WriteAllText((Join-Path $Platform 'PLATFORM_SOURCE.json'), $json + "`n", (New-Object Text.UTF8Encoding($false)))
Write-Host "PLATFORM_SOURCE.json: $commit$(if ($tag) { " ($tag)" })"
