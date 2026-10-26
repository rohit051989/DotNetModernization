<#
.SYNOPSIS
    Updates the platform folder inside a client's repository to the tip of our master, and commits only that folder
    to your own branch (docs\VDI-SETUP.md Part 2).

.DESCRIPTION
    Two folders on the machine:
      - the source folder: a separate, pristine clone of our repository, on master, used only as the source of
        copies. Never the repository we work in: the script stops unless the source folder is on master, follows
        origin/master, and has no local commits or changes.
      - the platform folder: a folder inside the client's repository, which other people also work in, on their
        own branches. Our .git never goes there.

    Installations follow our master: every commit on master passes the full test suites (CLAUDE.md rule 17). Tags
    are reference points the owner creates by hand; the script neither needs nor installs one.

    It runs on the client's machine, or on ours when the client's environment cannot reach our git: then the
    client's repository is a local clone on our machine and -Push delivers master's files to the client's branch
    (docs\VDI-SETUP.md, "Delivering to a client from our machine"). Either way only files are copied: our history
    and tags never go into the client's repository, and only -Branch is pushed.

    It works the same whether it is run from the source folder or from the platform folder.

    In order, stopping with a plain message at the first problem:
      1. The client repository must be on -Branch, and the platform folder must have no uncommitted changes
         (both are named when not).
      2. The source folder must be a clone of our repository on master, following origin/master, with no local
         commits or changes. Our master is fetched.
      3. The installed commit must be known: a platform folder that already has files needs a PLATFORM_SOURCE.json
         whose commit the source folder holds, or the update is refused, changing nothing (an empty folder is a
         first install and needs none). Never backwards: origin's master must descend from the installed commit
         and from the source folder's own master. A rewritten history, or a platform installed from another
         branch, is refused, saying why, with both folders left as they were. -AllowDowngrade installs it
         anyway, after listing what will be lost. Then the source folder is brought to origin's master with
         git pull --ff-only (with -AllowDowngrade over a rewritten history, git reset --hard to it).
      4. The client branch is updated with git pull --ff-only.
      5. The source is copied into the platform folder with robocopy, leaving out .git, .venv, node_modules and
         .env files. robocopy's exit codes 0 to 7 mean success.
      6. Files we deleted or renamed are removed: only files that were in the installed commit and are not in the
         new one, worked out in the source folder, which holds both (a rename deletes the old name). A file in
         the platform folder that is in neither commit is the client's own: it is kept, and listed as "not part of
         the platform".
      7. PLATFORM_SOURCE.json is written (scripts\write-platform-source.ps1): the commit, and a tag only if one
         happens to point at it.
      8. Only the platform folder is staged and committed: git add -A -- <folder>, then git commit -- <folder>,
         with our source commit in the message. Nothing outside the folder is ever staged or committed.
      9. With -Push, only -Branch is pushed.
    Then it tells you to run bootstrap and restart the backend.

    Local files are never touched: .env, .venv, node_modules, the published step programs, and anything else not
    in our source, committed or not. RUNS_DIR and REPOS_DIR live outside the client's repository.

.PARAMETER Source
    The source folder: the pristine clone of our repository, on master.

.PARAMETER Platform
    The platform folder inside the client's repository.

.PARAMETER Branch
    Your own branch in the client's repository. The script stops if the repository is on any other.

.PARAMETER Push
    Push -Branch (and only it) to origin after committing.

.PARAMETER AllowDowngrade
    Install master even when it does not descend from the installed commit, after listing what will be lost.
    Only when you know why our history changed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File C:\MP\source\scripts\update-platform.ps1 -Source C:\MP\source -Platform C:\Client\Repo\modernization-platform -Branch rohit/modernization-platform
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Source,
    [Parameter(Mandatory)][string]$Platform,
    [Parameter(Mandatory)][string]$Branch,
    [switch]$Push,
    [switch]$AllowDowngrade
)

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

function Test-Commit([string]$folder, [string]$commit) {
    $type = & git -C $folder cat-file -t $commit 2>$null
    return $LASTEXITCODE -eq 0 -and "$type".Trim() -eq 'commit'
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

# ---- 2. The source folder: a pristine clone of ours, on master, following origin/master
$sourcePrefix = "$(@(Invoke-Git $Source @('rev-parse', '--show-prefix') 'Reading the source folder')[0])"
if ($sourcePrefix) { Stop-Update "$Source is not the root of a clone of our repository." }
$sourceTop = @(Invoke-Git $Source @('rev-parse', '--show-toplevel') 'Reading the source folder')[0]
if ($sourceTop -eq $top) { Stop-Update "the source folder is the client's repository. The source is a separate clone of our repository." }
$sourceChanged = @(Invoke-Git $Source @('status', '--porcelain') 'Checking the source folder')
if ($sourceChanged.Count -gt 0) {
    Stop-Update ("the source folder has changes, and nothing is ever edited there:`n  " + ($sourceChanged -join "`n  ") +
        "`nDiscard them (git -C `"$Source`" checkout -- . ; git -C `"$Source`" clean -fd) and run the update again.")
}
$sourceBranch = @(Invoke-Git $Source @('rev-parse', '--abbrev-ref', 'HEAD') 'Reading the source branch')[0]
if ($sourceBranch -ne 'master') {
    $where = $(if ($sourceBranch -eq 'HEAD') { "a commit of its own ($((@(Invoke-Git $Source @('describe', '--tags', '--always') 'Reading the source commit'))[0]))" } else { "branch '$sourceBranch'" })
    Stop-Update ("the source folder is on $where, not master. Installations follow master. An update made with an older " +
        "script leaves the source folder at a release tag; put it back on master and run the update again:`n" +
        "  git -C `"$Source`" switch master")
}
$upstream = & git -C $Source rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
if ($LASTEXITCODE -ne 0 -or "$upstream".Trim() -ne 'origin/master') {
    Stop-Update "the source folder's master follows $(if ($upstream) { "'$upstream'" } else { 'nothing' }), not origin/master: it looks like a working repository. Use a separate, pristine clone of our repository (docs\VDI-SETUP.md, `"The source folder and the platform folder`")."
}
$ahead = @(Invoke-Git $Source @('rev-list', '--count', '@{u}..HEAD') 'Comparing the source with origin')[0]
if ([int]$ahead -gt 0) {
    Stop-Update "the source folder's master has $ahead commit(s) not on origin: it is a working repository. Use a separate, pristine clone of our repository (docs\VDI-SETUP.md, `"The source folder and the platform folder`")."
}
$sourceBefore = @(Invoke-Git $Source @('rev-parse', 'HEAD') 'Reading the source commit')[0]
$installed = $null
$record = Join-Path $Platform 'PLATFORM_SOURCE.json'
if (Test-Path $record) {
    try { $installed = "$((Get-Content $record -Raw | ConvertFrom-Json).commit)".Trim() } catch { $installed = $null }
}
# An empty platform folder is a first install. Anything else is an installed platform, whose commit must be known:
# deletions are worked out from it, and without it a client's own file cannot be told from one we deleted.
$firstInstall = -not (Get-ChildItem -LiteralPath $Platform -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne '.env' } | Select-Object -First 1)
# Fetch first and check, then pull: a refused update leaves the source folder as it found it. --refmap= keeps
# origin/master where it was (master goes only to FETCH_HEAD) until the update is accepted. The owner's tags come
# along as they are on origin, to name the commit when one points at it.
Invoke-Git $Source @('fetch', '--quiet', '--refmap=', 'origin', 'master', '+refs/tags/*:refs/tags/*') 'Fetching our master' | Out-Null
$new = @(Invoke-Git $Source @('rev-parse', 'FETCH_HEAD') 'Reading origin''s master')[0]
$tag = & git -C $Source describe --tags --exact-match $new 2>$null
$tag = $(if ($LASTEXITCODE -eq 0 -and $tag) { "$tag".Trim() } else { $null })

# ---- 3. The installed commit, and never backwards
if (-not $firstInstall) {
    if (-not $installed) {
        Stop-Update ("the platform folder has files but no PLATFORM_SOURCE.json naming the commit of ours it holds. Without " +
            "it, a file we deleted cannot be told from the client's own, so nothing was changed. Ask us which of our " +
            "commits the folder was copied from, then record it: check that commit out in the source folder " +
            "(git -C `"$Source`" checkout <commit>), run scripts\write-platform-source.ps1 -Source `"$Source`" from the " +
            "platform folder, commit PLATFORM_SOURCE.json to your branch, put the source folder back on master " +
            "(git -C `"$Source`" switch master) and run the update again.")
    }
    if (-not (Test-Commit $Source $installed)) {
        Stop-Update ("the platform folder holds commit $installed (PLATFORM_SOURCE.json), which the source folder does not " +
            "contain: our history was rewritten, or the platform was installed from another repository. Without it, a " +
            "file we deleted cannot be told from the client's own, so nothing was changed. Ask us why; once the source " +
            "folder holds that commit (git -C `"$Source`" fetch origin, or the commit's branch), run the update again.")
    }
}
$old = $(if ($installed -and -not $firstInstall) { $installed } else { $null })
Write-Host "Source $Source`: master $(if ($old) { $old.Substring(0, 12) } else { 'nothing installed' }) -> $($new.Substring(0, 12))$(if ($tag) { " ($tag)" })"

# Both the installed commit and the source folder's own master must be in master's history: a commit that is not
# was installed from another branch, or our history was rewritten.
$why = @()
$lost = @()
if ($old -and $old -ne $new) {
    & git -C $Source merge-base --is-ancestor $old $new
    if ($LASTEXITCODE -ne 0) {
        $why += "master ($($new.Substring(0, 12))) does not descend from the installed commit $($old.Substring(0, 12)): our history was rewritten, or the platform was installed from another branch."
        $lost += @(Invoke-Git $Source @('log', '--oneline', '--no-decorate', "$new..$old") 'Listing the installed commits master lacks')
    }
}
& git -C $Source merge-base --is-ancestor $sourceBefore $new
$sourceForward = $LASTEXITCODE -eq 0
if (-not $sourceForward) {
    $why += "origin's master ($($new.Substring(0, 12))) does not descend from the source folder's master ($($sourceBefore.Substring(0, 12))): our master's history was rewritten."
    foreach ($line in @(Invoke-Git $Source @('log', '--oneline', '--no-decorate', "$new..$sourceBefore") 'Listing the commits master lost')) {
        if ($lost -notcontains $line) { $lost += $line }
    }
}
if ($why.Count -gt 0) {
    if (-not $AllowDowngrade) {
        Stop-Update (($why -join "`n") + "`nCommits that would be lost ($($lost.Count)):`n  " + ($lost -join "`n  ") +
            "`nThe source folder and the platform folder are unchanged. Ask why our master changed; to install it anyway, losing those, run again with -AllowDowngrade.")
    }
    Write-Host ('Going backwards (-AllowDowngrade): ' + ($why -join "`n  ")) -ForegroundColor Yellow
    Write-Host "These will be lost from the platform folder ($($lost.Count)):`n  $($lost -join "`n  ")" -ForegroundColor Yellow
}
if ($sourceForward) {
    Invoke-Git $Source @('pull', '--ff-only', '--quiet', 'origin', 'master') 'Bringing the source folder to origin/master (git pull --ff-only)' | Out-Null
} else {
    # Only with -AllowDowngrade. The source folder holds nothing of its own (checked above), so nothing of ours is lost here.
    Invoke-Git $Source @('fetch', '--quiet', 'origin') 'Fetching origin''s rewritten master' | Out-Null
    Invoke-Git $Source @('reset', '--hard', '--quiet', $new) 'Moving the source folder to origin''s rewritten master' | Out-Null
}
if (@(Invoke-Git $Source @('rev-parse', 'HEAD') 'Reading the source commit')[0] -ne $new) {
    Stop-Update "the source folder did not reach origin's master $new."
}

# ---- 4. The client branch
Invoke-Git $top @('pull', '--ff-only') "Updating $Branch (git pull --ff-only)" | Out-Null

# ---- 5. Copy
& robocopy $Source $Platform /E /XD .git .venv node_modules /XF .env /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
$copied = $LASTEXITCODE
if ($copied -ge 8) { Stop-Update "robocopy failed (exit code $copied): the platform folder may be partly copied. Fix the cause and run the update again." }
Write-Host "Copied (robocopy exit code $copied)"

# ---- 6. Files we deleted or renamed: in the installed commit, not in the new one
# Worked out in the source folder, which holds both commits, whichever folder this script runs from. With
# --no-renames a rename is the deletion of the old name and the addition of the new. Nothing else is ever removed.
$removed = 0
if ($old -and $old -ne $new) {
    foreach ($path in @(Invoke-Git $Source @('-c', 'core.quotepath=false', 'diff', '--name-only', '--no-renames', '--diff-filter=D', $old, $new) 'Listing the files we deleted or renamed')) {
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
}
Write-Host "Removed $removed file(s) we deleted or renamed"

# The client's own files: committed in the platform folder, in neither the installed commit nor the new one. Kept.
$platformFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($commit in @($old, $new) | Where-Object { $_ }) {
    foreach ($path in @(Invoke-Git $Source @('-c', 'core.quotepath=false', 'ls-tree', '-r', '--name-only', $commit) 'Listing our files')) {
        [void]$platformFiles.Add($path)
    }
}
$theirs = @()
foreach ($tracked in @(Invoke-Git $top @('-c', 'core.quotepath=false', 'ls-files', '--', $folder) 'Listing the platform folder''s files')) {
    $path = $tracked.Substring($folder.Length + 1)
    if ($path -ne 'PLATFORM_SOURCE.json' -and -not $platformFiles.Contains($path)) { $theirs += $path }
}
if ($theirs.Count -gt 0) {
    Write-Host "Kept, not part of the platform ($($theirs.Count)):`n  $($theirs -join "`n  ")"
}

# ---- 7. Which of our commits this is
# The copy just placed in the platform folder, whichever folder this script was started from.
# Kept as it is when the commit has not changed: a run with nothing new commits nothing.
if ($installed -ne $new) {
    & (Join-Path $Platform 'scripts\write-platform-source.ps1') -Source $Source -Platform $Platform -Previous "$old"
    if ($LASTEXITCODE -and $LASTEXITCODE -ne 0) { Stop-Update 'writing PLATFORM_SOURCE.json failed.' }
}

# ---- 8. Commit only the platform folder
Invoke-Git $top @('add', '-A', '--', $folder) 'Staging the platform folder' | Out-Null
$staged = @(Invoke-Git $top @('diff', '--cached', '--name-only', '--', $folder) 'Listing the staged files')
if ($staged.Count -eq 0) {
    Write-Host 'Nothing changed in the platform folder: no commit.'
} else {
    $title = "Modernization platform: update to $($new.Substring(0, 12))$(if ($tag) { " ($tag)" })"
    $message = "$title`n`nSource commit: $new`nPrevious source commit: $(if ($old) { $old } else { 'none (first install)' })$(if ($tag) { "`nTag: $tag" })`nFiles: $($staged.Count) changed in $folder"
    Invoke-Git $top @('commit', '-q', '-m', $message, '--', $folder) 'Committing the platform folder' | Out-Null
    $commit = @(Invoke-Git $top @('rev-parse', '--short', 'HEAD') 'Reading the commit')[0]
    Write-Host "Committed $commit on $Branch`: $($staged.Count) file(s) in $folder"
}

# ---- 9. Push, only your branch
if ($Push) {
    Invoke-Git $top @('push', 'origin', "refs/heads/$Branch`:refs/heads/$Branch") "Pushing $Branch" | Out-Null
    Write-Host "Pushed $Branch"
}

Write-Host ''
Write-Host 'Update complete. Now run bootstrap, then restart the backend:' -ForegroundColor Green
Write-Host "  cd `"$Platform`"; powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1"
Write-Host '  then stop the backend (Ctrl+C in its window) and start it again (docs\VDI-SETUP.md Part 1, "Starting").'
