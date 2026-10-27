<#
.SYNOPSIS
    Brings changes made in a client's copy of the platform back into our repository, so it holds every feature, ours
    and the client's, and every installation receives them with its next update (docs\VDI-SETUP.md, "Importing a
    client's changes"). Runs on our machine.

.DESCRIPTION
    The reverse of scripts\update-platform.ps1. It takes the platform folder in a local clone of the client's
    repository, our working repository, and a deny-list file kept outside the repository.

    Never a plain copy over our branch: our branch may hold work the client has not received yet, such as features
    built for another installation, and copying the client's folder over it would revert that work. Instead:
      1. Our working repository must have no uncommitted changes. The client's clone is fetched; its branch must
         match its remote, and the platform folder must have no uncommitted changes.
      2. The target: the client's main or master goes into our master (which must be checked out in our working
         repository); any other branch, such as release/<feature>, into our branch of the same name, created from
         the commit the client received when it does not exist. A branch name holding a deny-listed term is refused.
      3. The commit the client received is read from its PLATFORM_SOURCE.json; our repository must have it.
      4. The client's commits in the platform folder since the previous import (found through the Client-Commit
         trailer the previous import recorded) are listed. Deliveries (commits that write PLATFORM_SOURCE.json) are
         ours, not the client's, and are left out. None: there is nothing new to import.
      5. On a temporary branch from the received commit, in a scratch worktree, the client's committed folder is
         copied over it, leaving out PLATFORM_SOURCE.json, .env files, .venv, node_modules, build output and anything
         else local-only; files the client deleted are removed.
      6. Everything coming in is scanned: the added and changed lines, the file names, the branch name and the commit
         messages. Secrets (sensitive keys with values, tokens, connection strings with passwords, private keys),
         .env files, binaries over 1 MB and every deny-list term are refused, each listed with its file and line.
         Nothing is imported unless the scan finds nothing.
      7. That commit is merged into the target. Where both sides changed the same lines the client's version wins:
         the client is the source in this direction. Every file where that happened is reported.
      8. The target branch in our working repository moves to the merge (fast-forward). For master, the backend,
         frontend and C# suites run on the result (scripts\run-suites.ps1); with -Push, master is pushed only when
         they all pass, and otherwise stays unpushed, saying why. Any other branch is pushed once the scan passes.

    The commit's subject is the client's latest commit message; its body lists the client's other commits since the
    previous import; its Client-Commit trailer records the client's commit, so the next import knows where it left
    off, and update-platform.ps1 knows what has been imported.

    Our history is only ever added to: nothing is reset, rebased or force-pushed, and no tag is created.

.PARAMETER Platform
    The platform folder in a local clone of the client's repository, on the branch to import: a folder inside it, or
    its root when the repository is dedicated to the platform (then the whole repository is the platform).

.PARAMETER Repository
    Our working repository.

.PARAMETER DenyList
    A text file of terms that must never enter our repository (client names, host names, codes), one per line;
    lines starting with # are comments. It lives on the operator's machine, outside the repository.

.PARAMETER Push
    Push the target branch to origin: master only when every suite passes, any other branch once the scan passes.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\import-client-changes.ps1 -Platform C:\MPD\client-a\modernization-platform -Repository D:\work\modernization-platform -DenyList C:\MPD\deny-list.txt -Push
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Platform,
    [Parameter(Mandatory)][string]$Repository,
    [Parameter(Mandatory)][string]$DenyList,
    [switch]$Push
)

$ErrorActionPreference = 'Continue'   # git writes progress to stderr; every exit code is checked instead
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$LocalOnlyDirs = @('.git', '.venv', 'venv', 'node_modules', 'bin', 'obj', 'dist', 'publish', '__pycache__',
                   '.pytest_cache', '.vs', 'runs')
$LargeBinaryBytes = 1MB
$Trailer = 'Client-Commit'
$script:cleanup = @()

# Undoes the scratch work, last step first: the worktree, then the temporary branch, then the scratch folder.
function Remove-Scratch {
    for ($i = $script:cleanup.Count - 1; $i -ge 0; $i--) { & $script:cleanup[$i] }
    $script:cleanup = @()
}

function Stop-Import([string]$why) {
    Remove-Scratch
    Write-Host ''
    Write-Host "Stopped: $why" -ForegroundColor Red
    Write-Host 'Nothing was imported.'
    exit 1
}

# Runs git in a folder; returns its output lines. Call it inside @( ). Stops the import, with git's own message,
# when it fails.
function Invoke-Git([string]$folder, [string[]]$arguments, [string]$what) {
    $output = & git -C $folder @arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        Stop-Import "$what failed: git $($arguments -join ' ')`n$(($output | Out-String).Trim())"
    }
    return @($output | ForEach-Object { "$_" })
}

function Test-Commit([string]$folder, [string]$commit) {
    $type = & git -C $folder cat-file -t $commit 2>$null
    return $LASTEXITCODE -eq 0 -and "$type".Trim() -eq 'commit'
}

function Test-LocalOnly([string]$path) {
    $parts = $path -split '/'
    if ($parts.Count -eq 1 -and $parts[0] -eq 'PLATFORM_SOURCE.json') { return $true }
    for ($i = 0; $i -lt $parts.Count - 1; $i++) { if ($LocalOnlyDirs -contains $parts[$i]) { return $true } }
    return $parts[-1] -like '*.pyc'
}

function Test-EnvFile([string]$path) {
    $name = ($path -split '/')[-1]
    return $name -eq '.env' -or ($name -like '.env.*' -and $name -notin @('.env.example', '.env.sample', '.env.template'))
}

# ---- what the scan looks for
$Placeholder = '^(\$|%|<|\{|\*+$)|example|placeholder|changeme|change-me|your[-_ ]|xxx|\.\.\.|^(true|false|null|none|string|required|optional)$'
$Tokens = @(
    @('-----BEGIN [A-Z ]*PRIVATE KEY-----', 'a private key'),
    @('\bgh[pousr]_[A-Za-z0-9]{30,}', 'a GitHub token'),
    @('\bgithub_pat_[A-Za-z0-9_]{30,}', 'a GitHub token'),
    @('\bglpat-[A-Za-z0-9_-]{20,}', 'a GitLab token'),
    @('\bAKIA[0-9A-Z]{16}\b', 'an AWS access key'),
    @('\bxox[abprs]-[A-Za-z0-9-]{10,}', 'a Slack token'),
    @('\bsk-[A-Za-z0-9_-]{20,}', 'an API key'),
    @('\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}', 'a JSON web token'),
    @('(?i)\bBearer\s+[A-Za-z0-9._~+/-]{20,}=*', 'a bearer token'),
    @('(?i)\b(AccountKey|SharedAccessKey|SharedAccessSignature)=[A-Za-z0-9+/%=&:-]{20,}', 'a storage or service bus key')
)
$SensitiveKey = '(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|token|credential)s?'
$ConfigExtensions = @('.json', '.yml', '.yaml', '.config', '.ini', '.properties', '.xml', '.toml', '.env', '.conf', '.cfg', '.settings')

function Format-Value([string]$value) {
    if ($value.Length -le 2) { return '...' }
    return $value.Substring(0, 2) + '...'
}

# The secrets on one line of text: each a description. $config: the line is in a configuration file, where a value
# need not be quoted.
function Find-Secrets([string]$line, [bool]$config) {
    $found = @()
    foreach ($token in $Tokens) {
        if ($line -match $token[0]) { $found += $token[1] }
    }
    if ($line -match '(?i)(server|data source|host|user id|uid|database|initial catalog|addr|address)\s*=' -and
        $line -match '(?i)\b(?:password|pwd)\s*=\s*([^;"''\s]+)' -and $Matches[1] -notmatch "(?i)$Placeholder") {
        $found += "a connection string with a password ($(Format-Value $Matches[1]))"
    }
    if ($line -match '\b[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@"'']+:([^@\s/"'']+)@' -and $Matches[1] -notmatch "(?i)$Placeholder") {
        $found += "a URL with a password ($(Format-Value $Matches[1]))"
    }
    if ($line -match "(?i)key\s*=\s*[""'][^""']*$SensitiveKey[^""']*[""']\s+value\s*=\s*[""']([^""']{4,})[""']" -and
        $Matches[1] -notmatch "(?i)$Placeholder") {
        $found += "a value for a sensitive setting ($(Format-Value $Matches[1]))"
    } elseif ($line -match "(?i)[""']?\b([A-Za-z0-9_.-]*$SensitiveKey)\b[""']?\s*[:=]\s*[""']([^""']{4,})[""']" -and
              $Matches[2] -notmatch "(?i)$Placeholder") {
        $found += "a value for $($Matches[1]) ($(Format-Value $Matches[2]))"
    } elseif ($config -and $line -match "(?i)^\s*[""']?([A-Za-z0-9_.-]*$SensitiveKey)[""']?\s*[:=]\s*([^\s""',;#]{4,})" -and
              $Matches[2] -notmatch "(?i)$Placeholder") {
        $found += "a value for $($Matches[1]) ($(Format-Value $Matches[2]))"
    }
    return $found
}

function Find-Terms([string]$text) {
    return @($script:terms | Where-Object { $text.IndexOf($_, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
}

$findings = New-Object System.Collections.Generic.List[string]
function Add-Finding([string]$where, [string]$what) { $findings.Add("  ${where}: $what") }

# ---- 1. Our repository, the deny-list, the client's clone
$Repository = (Resolve-Path -LiteralPath $Repository).Path.TrimEnd('\')
$Platform = (Resolve-Path -LiteralPath $Platform).Path.TrimEnd('\')
if (-not (Test-Path -LiteralPath $DenyList -PathType Leaf)) { Stop-Import "the deny-list file $DenyList does not exist." }
$DenyList = (Resolve-Path -LiteralPath $DenyList).Path

if ("$(@(Invoke-Git $Repository @('rev-parse', '--show-prefix') 'Reading our repository')[0])") {
    Stop-Import "$Repository is not the root of our working repository."
}
$ourChanges = @(Invoke-Git $Repository @('status', '--porcelain') 'Checking our repository')
if ($ourChanges.Count -gt 0) {
    Stop-Import ("our working repository has uncommitted changes; commit or stash them first:`n  " + ($ourChanges -join "`n  "))
}
if ($DenyList.StartsWith($Repository + '\', [StringComparison]::OrdinalIgnoreCase)) {
    Stop-Import "the deny-list $DenyList is inside our repository. It names what must never enter the repository, so it lives outside it, on this machine."
}
$script:terms = @(Get-Content -LiteralPath $DenyList -Encoding UTF8 | ForEach-Object { $_.Trim() } |
    Where-Object { $_ -and -not $_.StartsWith('#') } | Select-Object -Unique)
if ($script:terms.Count -eq 0) { Stop-Import "the deny-list $DenyList has no terms: it would protect nothing." }

$top = @(Invoke-Git $Platform @('rev-parse', '--show-toplevel') 'Finding the client''s repository')[0]
$folder = "$(@(Invoke-Git $Platform @('rev-parse', '--show-prefix') 'Finding the platform folder')[0])".TrimEnd('/')
# Two layouts, told apart by the path given: a folder inside the client's repository, or its root, where the whole
# repository is the platform. $scope is what every check looks at: the folder, or the whole repository.
$atRoot = -not $folder
$scope = $(if ($atRoot) { '.' } else { $folder })
$prefix = $(if ($atRoot) { '' } else { "$folder/" })
$tree = $(if ($atRoot) { 'HEAD' } else { "HEAD:$folder" })
$where = $(if ($atRoot) { 'the repository root (the whole repository is the platform)' } else { $folder })
$theirChanges = @(Invoke-Git $top @('status', '--porcelain', '--', $scope) 'Checking the platform folder')
if ($theirChanges.Count -gt 0) {
    Stop-Import ("the platform folder in the client's clone has uncommitted changes; only committed work is imported:`n  " +
        ($theirChanges -join "`n  "))
}
Invoke-Git $top @('fetch', '--quiet', 'origin') 'Fetching the client''s clone' | Out-Null
$branch = @(Invoke-Git $top @('rev-parse', '--abbrev-ref', 'HEAD') 'Reading the client''s branch')[0]
if ($branch -eq 'HEAD') { Stop-Import "the client's clone is on a commit of its own, not a branch. Check out the branch to import." }
$upstream = & git -C $top rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>$null
if ($LASTEXITCODE -ne 0 -or -not $upstream) { Stop-Import "the client's branch '$branch' follows nothing on its remote, so it cannot be confirmed." }
$clientHead = @(Invoke-Git $top @('rev-parse', 'HEAD') 'Reading the client''s commit')[0]
$remoteHead = @(Invoke-Git $top @('rev-parse', '@{u}') 'Reading the client''s remote branch')[0]
if ($clientHead -ne $remoteHead) {
    $counts = @(Invoke-Git $top @('rev-list', '--left-right', '--count', 'HEAD...@{u}') 'Comparing with the remote')[0] -split '\s+'
    Stop-Import "the client's branch '$branch' does not match $upstream ($($counts[0]) commit(s) only here, $($counts[1]) only on the remote). Pull or push it first: the import takes what the client's remote holds."
}
Write-Host "Client's clone $top, branch $branch at $($clientHead.Substring(0, 12)), platform at $where"

# ---- 2. Where it goes
$target = $(if ($branch -in @('main', 'master')) { 'master' } else { $branch })
foreach ($term in Find-Terms $branch) { Add-Finding "branch name '$branch'" "deny-listed term '$term'" }
if ($findings.Count -gt 0) {
    Stop-Import ("the branch name holds a deny-listed term, and would enter our repository as a branch:`n" + ($findings -join "`n"))
}
$ourBranch = @(Invoke-Git $Repository @('rev-parse', '--abbrev-ref', 'HEAD') 'Reading our branch')[0]
if ($target -eq 'master' -and $ourBranch -ne 'master') {
    Stop-Import "the client's '$branch' goes into our master, and our working repository is on '$ourBranch'. Check out master first: the suites run on the merged master there. git -C `"$Repository`" switch master"
}
$hasOrigin = @(& git -C $Repository remote) -contains 'origin'
if ($hasOrigin) { Invoke-Git $Repository @('fetch', '--quiet', 'origin') 'Fetching our repository' | Out-Null }
$localTip = & git -C $Repository rev-parse --verify --quiet "refs/heads/$target" 2>$null
$localTip = $(if ($LASTEXITCODE -eq 0 -and $localTip) { "$localTip".Trim() } else { $null })
$remoteTip = $null
if ($hasOrigin) {
    $remoteTip = & git -C $Repository rev-parse --verify --quiet "refs/remotes/origin/$target" 2>$null
    $remoteTip = $(if ($LASTEXITCODE -eq 0 -and $remoteTip) { "$remoteTip".Trim() } else { $null })
}
if ($localTip -and $remoteTip -and $localTip -ne $remoteTip) {
    Stop-Import "our '$target' ($($localTip.Substring(0, 12))) differs from origin/$target ($($remoteTip.Substring(0, 12))). Pull or push it first, so the import builds on what everyone has."
}
$targetTip = $(if ($localTip) { $localTip } else { $remoteTip })
Write-Host "Target: our $target$(if (-not $targetTip) { ' (new: created from the commit the client received)' })"

# ---- 3. The commit the client received
$recordPath = Join-Path $Platform 'PLATFORM_SOURCE.json'
if (-not (Test-Path $recordPath)) {
    Stop-Import "the platform folder has no PLATFORM_SOURCE.json, so the commit the client received is not known, and the client's changes cannot be told from ours."
}
try { $base = "$((Get-Content $recordPath -Raw | ConvertFrom-Json).commit)".Trim() } catch { $base = '' }
if (-not $base -or -not (Test-Commit $Repository $base)) {
    Stop-Import "the client received commit $(if ($base) { $base } else { '(none recorded)' }) (PLATFORM_SOURCE.json), which our repository does not have. Fetch the branch it came from, or ask who delivered it."
}
Write-Host "The client received our commit $($base.Substring(0, 12))"

# ---- 4. The client's commits since the previous import
$imported = @(& git -C $Repository log --all "--format=%(trailers:key=$Trailer,valueonly,separator=%x2C)" 2>$null |
    ForEach-Object { "$_" -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique)
$previous = $null
$previousDepth = -1
foreach ($commit in $imported) {
    if (-not (Test-Commit $top $commit)) { continue }
    & git -C $top merge-base --is-ancestor $commit HEAD
    if ($LASTEXITCODE -ne 0) { continue }
    $depth = [int]@(Invoke-Git $top @('rev-list', '--count', $commit) 'Counting')[0]
    if ($depth -gt $previousDepth) { $previous = $commit; $previousDepth = $depth }
}
# Only since the latest delivery as well: what came before it was imported, or knowingly delivered over. At the root
# this also leaves out the repository's own history from before the platform arrived.
$lastDelivery = "$(@(Invoke-Git $top @('log', '-1', '--format=%H', 'HEAD', '--', "${prefix}PLATFORM_SOURCE.json") 'Finding the latest delivery')[0])".Trim()
$stops = @(@($previous, $lastDelivery) | Where-Object { $_ })
$range = @('HEAD') + $(if ($stops.Count -gt 0) { @('--not') + $stops } else { @() })
$incoming = @()
foreach ($commit in @(Invoke-Git $top (@('log', '--no-merges', '--format=%H') + $range + @('--', $scope)) 'Listing the client''s commits')) {
    $delivery = @(Invoke-Git $top @('diff-tree', '--no-commit-id', '--name-only', '-r', $commit, '--', "${prefix}PLATFORM_SOURCE.json") 'Reading a commit')
    if ($delivery.Count -eq 0) { $incoming += $commit }
}
if ($incoming.Count -eq 0) {
    Write-Host ''
    Write-Host ("Nothing new to import: the client's branch '$branch' has no commits in the platform folder " +
        $(if ($previous) { "since the previous import (client commit $($previous.Substring(0, 12)))." } else { 'other than our deliveries.' })) -ForegroundColor Green
    exit 0
}
$messages = @()
foreach ($commit in $incoming) {
    $text = (@(Invoke-Git $top @('show', '-s', '--format=%B', $commit) 'Reading a commit message') -join "`n").Trim()
    $messages += [pscustomobject]@{ Commit = $commit; Subject = ($text -split "`n")[0]; Text = $text }
    $number = 0
    foreach ($line in $text -split "`n") {
        $number++
        foreach ($term in Find-Terms $line) { Add-Finding "commit $($commit.Substring(0, 12)) message, line $number" "deny-listed term '$term'" }
        foreach ($secret in Find-Secrets $line $false) { Add-Finding "commit $($commit.Substring(0, 12)) message, line $number" $secret }
    }
}
Write-Host "Client commits since the $(if ($previous) { "previous import ($($previous.Substring(0, 12)))" } else { 'platform arrived' }): $($incoming.Count)"

# What the client's folder is compared with: the commit it received, or, when an import since then already took part
# of its changes, that import's own commit of the client's folder (it sits on the received commit). Then only what
# changed since that import comes in, and a file the client changed again is not a conflict with itself.
$parent = $base
if ($previous) {
    $previousReceived = @(& git -C $Repository log --all --no-merges --format=%H --fixed-strings --grep "${Trailer}: $previous" 2>$null |
        ForEach-Object { "$_".Trim() } | Where-Object { $_ }) | Select-Object -First 1
    if ($previousReceived) {
        & git -C $Repository merge-base --is-ancestor $base $previousReceived
        if ($LASTEXITCODE -eq 0) { $parent = $previousReceived }
    }
}

# ---- 5. The client's folder over the received commit, on a temporary branch
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('mp-import-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$worktree = Join-Path $scratch 'wt'
$extract = Join-Path $scratch 'client'
$temporary = "platform-import/received-$($clientHead.Substring(0, 12))-$([guid]::NewGuid().ToString('N').Substring(0, 6))"
New-Item -ItemType Directory -Force $extract | Out-Null
$script:cleanup += { Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue }
$script:cleanup += { & git -C $Repository branch -q -D $temporary 2>$null | Out-Null }
$script:cleanup += { & git -C $Repository worktree remove --force $worktree 2>$null | Out-Null; & git -C $Repository worktree prune 2>$null | Out-Null }
Invoke-Git $Repository @('-c', 'core.longpaths=true', 'worktree', 'add', '-q', '-b', $temporary, $worktree, $parent) 'Making a scratch worktree' | Out-Null

# The client's committed folder, exactly: nothing untracked on its disk comes along.
$tar = Join-Path $scratch 'client.tar'
Invoke-Git $top @('archive', '--format=tar', '-o', $tar, $tree) 'Exporting the client''s folder' | Out-Null
$tarExe = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path $tarExe)) { $tarExe = 'tar' }
& $tarExe -xf $tar -C $extract
if ($LASTEXITCODE -ne 0) { Stop-Import "unpacking the client's folder failed (tar exit code $LASTEXITCODE)." }

$theirFiles = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($path in @(Invoke-Git $top @('-c', 'core.quotepath=false', 'ls-tree', '-r', '--name-only', $tree) 'Listing the client''s files')) {
    if (Test-EnvFile $path) { Add-Finding $path 'a .env file, committed in the platform folder: never imported'; continue }
    if (-not (Test-LocalOnly $path)) { [void]$theirFiles.Add($path) }
}
& robocopy $extract $worktree /E /XD @LocalOnlyDirs /XF PLATFORM_SOURCE.json .env *.pyc /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { Stop-Import "copying the client's folder failed (robocopy exit code $LASTEXITCODE)." }
foreach ($path in @(Invoke-Git $worktree @('-c', 'core.quotepath=false', 'ls-files') 'Listing our files')) {
    if (-not $theirFiles.Contains($path) -and -not (Test-LocalOnly $path)) {
        Invoke-Git $worktree @('rm', '-q', '--', $path) "Removing $path" | Out-Null
    }
}
# A .env file never comes in, whatever the scan finds.
Get-ChildItem -LiteralPath $worktree -Recurse -Force -File -ErrorAction SilentlyContinue |
    Where-Object { (Test-EnvFile $_.Name) -and $_.FullName -notlike "$worktree\.git*" } | Remove-Item -Force
Invoke-Git $worktree @('add', '-A') 'Staging the client''s folder' | Out-Null
$status = @(Invoke-Git $worktree @('-c', 'core.quotepath=false', 'diff', '--cached', '--name-status', '--no-renames', $parent) 'Listing the client''s changes')
if ($status.Count -eq 0 -and $findings.Count -eq 0) {
    Remove-Scratch
    Write-Host ''
    Write-Host "Nothing new to import: the client's folder holds exactly what our repository already received from it ($($parent.Substring(0, 12)))." -ForegroundColor Green
    exit 0
}

# ---- 6. Scan everything coming in
$added = @(); $changed = @(); $deleted = @()
foreach ($entry in $status) {
    $kind, $path = $entry -split "`t", 2
    switch ($kind[0]) { 'A' { $added += $path } 'M' { $changed += $path } 'D' { $deleted += $path } default { $changed += $path } }
    foreach ($term in Find-Terms $path) { Add-Finding $path "deny-listed term '$term' in the file name" }
}
foreach ($entry in @(Invoke-Git $worktree @('-c', 'core.quotepath=false', 'diff', '--cached', '--numstat', '--no-renames', $parent) 'Measuring the client''s changes')) {
    $addedLines, $removedLines, $path = $entry -split "`t", 3
    if ($addedLines -eq '-') {
        $file = Join-Path $worktree ($path.Replace('/', '\'))
        if ((Test-Path -LiteralPath $file) -and (Get-Item -LiteralPath $file).Length -gt $LargeBinaryBytes) {
            Add-Finding $path "a binary file of $([math]::Round((Get-Item -LiteralPath $file).Length / 1MB, 1)) MB (over $($LargeBinaryBytes / 1MB) MB)"
        }
    }
}
$file = $null; $lineNumber = 0
foreach ($line in @(Invoke-Git $worktree @('-c', 'core.quotepath=false', 'diff', '--cached', '-U0', '--no-color', '--no-ext-diff', '--no-renames', $parent) 'Reading the client''s changes')) {
    if ($line.StartsWith('+++ ')) { $file = $(if ($line -eq '+++ /dev/null') { $null } else { $line.Substring(6) }); continue }
    if ($line -match '^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@') { $lineNumber = [int]$Matches[1]; continue }
    if (-not $file -or -not $line.StartsWith('+')) { continue }
    $text = $line.Substring(1)
    $config = $ConfigExtensions -contains [IO.Path]::GetExtension($file).ToLowerInvariant()
    foreach ($term in Find-Terms $text) { Add-Finding "${file}:$lineNumber" "deny-listed term '$term'" }
    foreach ($secret in Find-Secrets $text $config) { Add-Finding "${file}:$lineNumber" $secret }
    $lineNumber++
}
if ($findings.Count -gt 0) {
    Stop-Import ("the scan found what must not enter our repository ($($findings.Count)):`n" + ($findings -join "`n") +
        "`nHave the client remove it on their branch (and rewrite the commit message if it is in one), then import again.")
}
Write-Host "Scanned: $($added.Count) added, $($changed.Count) changed, $($deleted.Count) deleted; nothing refused"

# ---- 7. The commit, then the merge into the target
$subject = $messages[0].Subject
$others = @($messages | Select-Object -Skip 1 | ForEach-Object { "- $($_.Subject)" })
$body = @("Imported from the client's branch '$branch' (client commit $($clientHead.Substring(0, 12))), on our commit $($base.Substring(0, 12)), which the client had received.")
if ($others.Count -gt 0) { $body += @('', "The client's other commits since the $(if ($previous) { 'previous import' } else { 'platform arrived' }):") + $others }
function Write-Message([string[]]$extra) {
    $text = (@($subject, '') + $body + $extra + @('', "${Trailer}: $clientHead")) -join "`n"
    $path = Join-Path $scratch 'message.txt'
    [IO.File]::WriteAllText($path, $text + "`n", (New-Object Text.UTF8Encoding($false)))
    return $path
}
Invoke-Git $worktree @('commit', '-q', '--no-verify', '-F', (Write-Message @())) 'Committing what the client changed' | Out-Null
$received = @(Invoke-Git $worktree @('rev-parse', 'HEAD') 'Reading the commit')[0]

$start = $(if ($targetTip) { $targetTip } else { $base })
Invoke-Git $worktree @('checkout', '-q', '--detach', $start) "Checking out our $target" | Out-Null
# A trial merge finds where both sides changed the same lines; the merge itself then takes the client's version there.
& git -C $worktree -c core.longpaths=true merge --no-commit --no-ff -X no-renames $received 2>&1 | Out-Null
$clientWon = @(& git -C $worktree -c core.quotepath=false diff --name-only --diff-filter=U 2>$null | ForEach-Object { "$_" })
& git -C $worktree merge --abort 2>&1 | Out-Null
& git -C $worktree -c core.longpaths=true merge --no-commit --no-ff -X theirs -X no-renames $received 2>&1 | Out-Null
foreach ($path in @(& git -C $worktree -c core.quotepath=false diff --name-only --diff-filter=U 2>$null | ForEach-Object { "$_" })) {
    # Left by -X theirs: one side deleted the file, the other changed it. The client's side wins here too.
    & git -C $worktree cat-file -e "${received}:$path" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Invoke-Git $worktree @('checkout', '--theirs', '--', $path) "Taking the client's $path" | Out-Null
        Invoke-Git $worktree @('add', '--', $path) "Staging $path" | Out-Null
    } else {
        Invoke-Git $worktree @('rm', '-q', '--', $path) "Removing $path, as the client did" | Out-Null
    }
    if ($clientWon -notcontains $path) { $clientWon += $path }
}
& git -C $worktree diff --cached --quiet HEAD
if ($LASTEXITCODE -eq 0) {
    & git -C $worktree merge --abort 2>&1 | Out-Null
    Remove-Scratch
    Write-Host ''
    Write-Host "Nothing new to import: our $target already holds every change on the client's branch." -ForegroundColor Green
    exit 0
}
$won = $(if ($clientWon.Count -gt 0) { @('', "Where both sides changed the same lines, the client's version was kept:") + @($clientWon | ForEach-Object { "- $_" }) } else { @() })
Invoke-Git $worktree @('commit', '-q', '--no-verify', '-F', (Write-Message $won)) "Merging into our $target" | Out-Null
$merged = @(Invoke-Git $worktree @('rev-parse', 'HEAD') 'Reading the merge')[0]

# ---- 8. Our branch moves to the merge
if ($ourBranch -eq $target) {
    Invoke-Git $Repository @('merge', '-q', '--ff-only', $merged) "Moving our $target to the merge" | Out-Null
} else {
    Invoke-Git $Repository @('branch', '-f', $target, $merged) "Moving our $target to the merge" | Out-Null
}
Remove-Scratch

Write-Host ''
Write-Host "Imported into our $target as $($merged.Substring(0, 12)): $subject" -ForegroundColor Green
foreach ($group in @(@('Added', $added), @('Changed', $changed), @('Deleted', $deleted))) {
    if ($group[1].Count -gt 0) { Write-Host "$($group[0]) ($($group[1].Count)):`n  $($group[1] -join "`n  ")" }
}
if ($clientWon.Count -gt 0) {
    Write-Host "The client's version won where both sides changed the same lines ($($clientWon.Count)):`n  $($clientWon -join "`n  ")" -ForegroundColor Yellow
}

$passed = $true
if ($target -eq 'master') {
    Write-Host ''
    Write-Host 'Running every suite on the merged master (scripts\run-suites.ps1)...'
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repository 'scripts\run-suites.ps1')
    $passed = $LASTEXITCODE -eq 0
    Write-Host $(if ($passed) { 'The suites passed on the merged master.' } else { 'The suites FAILED on the merged master.' })
}
if (-not $Push) {
    Write-Host "Not pushed (no -Push)$(if (-not $passed) { '; the suites failed, so master must be fixed before it is pushed' })."
    exit $(if ($passed) { 0 } else { 1 })
}
if (-not $passed) {
    Write-Host "Not pushed: master stays deployable, and the suites failed on the merge. It is on our local master only; fix it there (a commit on top), run the suites, then push." -ForegroundColor Red
    exit 1
}
if (-not $hasOrigin) { Write-Host 'Not pushed: our repository has no origin.' -ForegroundColor Red; exit 1 }
Invoke-Git $Repository @('push', '-q', 'origin', "refs/heads/$target`:refs/heads/$target") "Pushing our $target" | Out-Null
Write-Host "Pushed our $target to origin."
exit 0
