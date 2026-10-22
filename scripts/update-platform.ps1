<#
.SYNOPSIS
    Updates the platform folder inside a client's repository from our source folder, and commits only that folder
    to your own branch (docs\VDI-SETUP.md Part 2).

.DESCRIPTION
    Two folders on the machine:
      - the source folder: a clone of our repository, used only as the source of copies. Never run anything in it.
      - the platform folder: a folder inside the client's repository, which other people also work in, on their
        own branches. Our .git never goes there.

    In order, stopping with a plain message at the first problem:
      1. The client repository must be on -Branch, and the platform folder must have no uncommitted changes
         (both are named when not).
      2. The source folder fetches our release tags and checks out a release: the newest by default, or the one
         -Release names. A release is installed, never the tip of master. The old commit is the one the platform
         folder holds (its PLATFORM_SOURCE.json), else the source folder's commit before the checkout.
      3. The client branch is updated with git pull --ff-only.
      4. The source is copied into the platform folder with robocopy, leaving out .git, .venv, node_modules and
         .env files. robocopy's exit codes 0 to 7 mean success.
      5. Files deleted upstream are removed from the platform folder, including the old names of renamed files:
         git diff --name-only --no-renames --diff-filter=D <old> <new>, in the source folder.
      6. PLATFORM_SOURCE.json is written (scripts\write-platform-source.ps1), naming the release installed.
      7. Only the platform folder is staged and committed: git add -A -- <folder>, then git commit -- <folder>,
         with our source commit in the message. Nothing outside the folder is ever staged or committed.
      8. With -Push, only -Branch is pushed.
    Then it tells you to run bootstrap and restart the backend.

    Local files are never touched: .env, .venv, node_modules, the published step programs, and anything else not
    in our source. RUNS_DIR and REPOS_DIR live outside the client's repository.

.PARAMETER Source
    The source folder: the clone of our repository.

.PARAMETER Platform
    The platform folder inside the client's repository.

.PARAMETER Branch
    Your own branch in the client's repository. The script stops if the repository is on any other.

.PARAMETER Release
    The release to install, by its tag: release-N (release-7 onward), or the older <prefix>-release-N of releases 1
    to 6. Default: the newest release, by its number.

.PARAMETER Push
    Push -Branch (and only it) to origin after committing.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File C:\Client\Repo\modernization-platform\scripts\update-platform.ps1 -Source C:\MP\source -Platform C:\Client\Repo\modernization-platform -Branch rohit/modernization-platform
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Platform,
    [Parameter(Mandatory)][string]$Branch,
    [string]$Release = '',
    [switch]$Push
)

# A release tag: release-N, or the older <prefix>-release-N of releases 1 to 6.
$ReleaseTag = '^(?:[a-z0-9]+-)?release-(\d+)$'

$ErrorActionPreference = 'Continue'   # git writes progress to stderr; every exit code is checked instead

function Stop-Update([string]$why) {
    Write-Host ''
    Write-Host "Stopped: $why" -ForegroundColor Red
    Write-Host 'Nothing was committed.'
    exit 1
}

# Runs git in a folder; returns its output lines. Call it inside @( ): PowerShell unrolls a one-line result to
# a string, whose [0] would be its first character. Stops the update, with git's own message, when it fails.
# Not named Git: PowerShell names are case-insensitive, and a function named Git would shadow git.exe.
function Invoke-Git([string]$folder, [string[]]$arguments, [string]$what) {
    $output = & git -C $folder @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        Stop-Update "$what failed: git $($arguments -join ' ')`n$(($output | Out-String).Trim())"
    }
    return @($output | ForEach-Object { "$_" })
}

$Source = (Resolve-Path -LiteralPath $Source).Path.TrimEnd('\')
$Platform = (Resolve-Path -LiteralPath $Platform).Path.TrimEnd('\')

# ---- 1. The client repository: the right branch, and a clean platform folder
# Where the platform folder sits in its repository comes from git itself (--show-prefix), never from comparing paths:
# a path can be written more than one way on Windows (C:\Users\ROHIT~1.KHA is C:\Users\rohit.khanna).
$top = @(Invoke-Git $Platform @('rev-parse', '--show-toplevel') 'Finding the client repository')[0]
$folder = "$(@(Invoke-Git $Platform @('rev-parse', '--show-prefix') 'Finding the platform folder')[0])".TrimEnd('/')
if (-not $folder) {
    Stop-Update "$Platform is the root of a git repository, not a folder inside the client's repository. This script updates a platform folder inside a client's repository (docs\VDI-SETUP.md Part 1)."
}
$current = @(Invoke-Git $top @('rev-parse', '--abbrev-ref', 'HEAD') 'Reading the client branch')[0]
if ($current -ne $Branch) {
    Stop-Update "the client repository $top is on branch '$current', not '$Branch'. Switch to your own branch first: git -C `"$top`" switch $Branch"
}
$changed = @(Invoke-Git $top @('status', '--porcelain', '--', $folder) 'Checking the platform folder')
if ($changed.Count -gt 0) {
    Stop-Update ("the platform folder has uncommitted changes:`n  " + ($changed -join "`n  ") +
        "`nCommit or discard them (only in $folder) and run the update again.")
}
Write-Host "Client repository $top, branch $Branch, platform folder $folder"

# ---- 2. The source folder
$sourcePrefix = "$(@(Invoke-Git $Source @('rev-parse', '--show-prefix') 'Reading the source folder')[0])"
if ($sourcePrefix) { Stop-Update "$Source is not the root of a clone of our repository." }
$sourceChanged = @(Invoke-Git $Source @('status', '--porcelain') 'Checking the source folder')
if ($sourceChanged.Count -gt 0) {
    Stop-Update ("the source folder has changes, and nothing is ever run or edited there:`n  " + ($sourceChanged -join "`n  ") +
        "`nDiscard them (git -C `"$Source`" checkout -- . ; git -C `"$Source`" clean -fd) and run the update again.")
}
$sourceBefore = @(Invoke-Git $Source @('rev-parse', 'HEAD') 'Reading the source commit')[0]
$installed = $null
$record = Join-Path $Platform 'PLATFORM_SOURCE.json'
if (Test-Path $record) { $installed = (Get-Content $record -Raw | ConvertFrom-Json).commit }
# The client installs releases, never the tip of master: fetch the tags, choose the release, check it out.
Invoke-Git $Source @('fetch', '--quiet', '--tags', '--force', 'origin') 'Fetching our releases' | Out-Null
$releases = @(Invoke-Git $Source @('tag', '--list') 'Listing our releases') | Where-Object { $_ -match $ReleaseTag }
if ($Release) {
    if ($Release -notmatch $ReleaseTag) { Stop-Update "$Release is not a release: releases are tagged release-N, such as release-7." }
    if ($releases -notcontains $Release) { Stop-Update "there is no release $Release in the source folder. Releases there: $(($releases | Sort-Object) -join ', ')" }
} else {
    $Release = $releases | Sort-Object { [int]([regex]::Match($_, $ReleaseTag).Groups[1].Value) } | Select-Object -Last 1
    if (-not $Release) { Stop-Update "the source folder has no release (a tag release-N). Ask for one; the platform is never installed from master." }
}
Invoke-Git $Source @('-c', 'advice.detachedHead=false', 'checkout', '--quiet', "refs/tags/$Release") "Checking out $Release in the source folder" | Out-Null
$new = @(Invoke-Git $Source @('rev-parse', 'HEAD') 'Reading the source commit')[0]
$old = $(if ($installed) { $installed } else { $sourceBefore })
& git -C $Source cat-file -e "$old^{commit}" 2>$null
if ($LASTEXITCODE -ne 0) { Stop-Update "the platform folder's recorded source commit $old is not in the source folder's history." }
Write-Host "Source $Source`: $Release, $($old.Substring(0, 12)) -> $($new.Substring(0, 12))$(if (-not $installed) { ' (no PLATFORM_SOURCE.json: the old commit is the source folder''s before the checkout)' })"

# ---- 3. The client branch
Invoke-Git $top @('pull', '--ff-only') "Updating $Branch (git pull --ff-only)" | Out-Null

# ---- 4. Copy
& robocopy $Source $Platform /E /XD .git .venv node_modules /XF .env /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
$copied = $LASTEXITCODE
if ($copied -ge 8) { Stop-Update "robocopy failed (exit code $copied): the platform folder may be partly copied. Fix the cause and run the update again." }
Write-Host "Copied (robocopy exit code $copied)"

# ---- 5. Files deleted upstream, renamed files' old names included
$removed = 0
foreach ($path in @(Invoke-Git $Source @('diff', '--name-only', '--no-renames', '--diff-filter=D', $old, $new) 'Listing deleted files')) {
    if (-not $path) { continue }
    $target = Join-Path $Platform ($path.Replace('/', '\'))
    if (Test-Path -LiteralPath $target -PathType Leaf) {
        Remove-Item -LiteralPath $target -Force
        $removed++
        $parent = Split-Path -Parent $target
        while ($parent.Length -gt $Platform.Length -and -not (Get-ChildItem -LiteralPath $parent -Force)) {
            Remove-Item -LiteralPath $parent -Force
            $parent = Split-Path -Parent $parent
        }
    }
}
Write-Host "Removed $removed file(s) deleted or renamed upstream"

# ---- 6. Which of our commits this is
# The copy just placed in the platform folder: nothing is ever run from the source folder.
& (Join-Path $Platform 'scripts\write-platform-source.ps1') -Source $Source -Platform $Platform -Previous $old -Release $Release
if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { Stop-Update 'writing PLATFORM_SOURCE.json failed.' }

# ---- 7. Commit only the platform folder
Invoke-Git $top @('add', '-A', '--', $folder) 'Staging the platform folder' | Out-Null
$staged = @(Invoke-Git $top @('diff', '--cached', '--name-only', '--', $folder) 'Listing the staged files')
if ($staged.Count -eq 0) {
    Write-Host 'Nothing changed in the platform folder: no commit.'
} else {
    $title = "Modernization platform: update to $Release ($($new.Substring(0, 12)))"
    $message = "$title`n`nRelease: $Release`nSource commit: $new`nPrevious source commit: $old`nFiles: $($staged.Count) changed in $folder"
    Invoke-Git $top @('commit', '-q', '-m', $message, '--', $folder) 'Committing the platform folder' | Out-Null
    $commit = @(Invoke-Git $top @('rev-parse', '--short', 'HEAD') 'Reading the commit')[0]
    Write-Host "Committed $commit on $Branch`: $($staged.Count) file(s) in $folder"
}

# ---- 8. Push, only your branch
if ($Push) {
    Invoke-Git $top @('push', 'origin', "refs/heads/$Branch`:refs/heads/$Branch") "Pushing $Branch" | Out-Null
    Write-Host "Pushed $Branch"
}

Write-Host ''
Write-Host 'Update complete. Now run bootstrap, then restart the backend:' -ForegroundColor Green
Write-Host "  cd `"$Platform`"; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1"
Write-Host '  then stop the backend (Ctrl+C in its window) and start it again (docs\VDI-SETUP.md Part 1, "Starting").'
