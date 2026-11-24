<#
.SYNOPSIS
    Runs the platform's test suites, in this repository, in one of two tiers. Exit code 0 only when every suite that
    ran passed.

      quick (the default, while working): only the suites the change can affect (-Since, or -Paths), leaving out the
            backend tests marked slow (backend\tests\tiers.py). With neither, the change is what this checkout has
            beyond its upstream branch, uncommitted and untracked files included (HEAD when it has no upstream).
      full  (-Full): every suite and every test, once, on the tip of master before a push (CLAUDE.md rule 17).

.DESCRIPTION
    The suites: backend; the seed and registration tests and the reproduce check; frontend tests and type check; the
    C# test projects and Python tests of each step program; third_party code-modernization.

    Which suites a change can affect (scripts\select_suites.py says how): frontend\ the frontend tests and type check; steps\<step>\ that
    step's tests; a script, the backend test modules that test it (a script no test is named for, the backend
    suite); one backend test module, that module alone; backend\ otherwise the backend suite; step registrations,
    the catalog, seed data or migrations the seed and registration tests and the reproduce check; documentation
    nothing; anything no rule knows, every suite. Before
    starting it prints which suites will run, and why. scripts\import-client-changes.ps1 runs it on a merge this way.

    Independent suites run at the same time, as many as the machine allows (a quarter of its logical processors, at
    least one; -MaxParallel to choose). Suites that share build output (the C# test projects) run one after another.
    Each suite's output goes to its own log; its last lines are printed when it ends, and a failing one's log is kept
    and named. The backend tests run split across processes (scripts\backend_shards.py, -Shards), each in a scratch
    schema of its own (backend\tests\__init__.py), never touching the platform's data; so does the reproduce check
    (backend\tests\reproduce_on_scratch.py). A run never hangs on its cleanup: each shard's teardown ends the
    database sessions it left open, reports them, and gives up on its schema after a time limit.

    Before running backend tests it checks that each C# step program is built and current for this checkout
    (scripts\step-programs.ps1, as bootstrap stage 6 decides). When one is not, it runs nothing, and names the
    programs and how to build them: tests on missing or stale programs would fail for that reason alone.

    Uses the repository's own environments: backend\.venv (bootstrap builds it) and frontend\node_modules.

.PARAMETER Full
    The full tier: every suite and every test. Run it once on the tip of master before a push (CLAUDE.md rule 17).

.PARAMETER Tier
    quick (default) or full: whether the backend tests marked slow run, in the suites -Since or -Paths chose.
    scripts\import-client-changes.ps1 gives full, as its merge may be pushed.

.PARAMETER Since
    A commit: only the suites the paths changed since it can affect, the uncommitted and untracked ones included.

.PARAMETER Paths
    The changed paths themselves, relative to the repository, separated by commas: only the suites they can affect.

.PARAMETER List
    Print which suites would run, and why, and run none.

.PARAMETER MaxParallel
    How many suites may run at the same time. Default: a quarter of the logical processors, at least one.

.PARAMETER Shards
    How many processes the backend tests are split across, each with its own schema. Default: 6.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\run-suites.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\run-suites.ps1 -Since HEAD~3

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\run-suites.ps1 -Full
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$Full,
    [ValidateSet('quick', 'full')][string]$Tier = 'quick',
    [string]$Since = '',
    [string[]]$Paths = @(),
    [switch]$List,
    [int]$MaxParallel = 0,
    [int]$Shards = 6
)

$ErrorActionPreference = 'Continue'
# From powershell -File, "-Paths a,b" arrives as one string: split it.
$Paths = @($Paths | ForEach-Object { "$_" -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host "No backend\.venv: run scripts\bootstrap.ps1 first." -ForegroundColor Red
    exit 1
}
if ($Full) {
    if ($Since -or $Paths.Count -gt 0) { Write-Host '-Full runs every suite: give it without -Since or -Paths.' -ForegroundColor Red; exit 1 }
    $Tier = 'full'
} elseif (-not $Since -and $Paths.Count -eq 0) {
    # The quick tier's change, when none is given: what this checkout has beyond its upstream branch.
    $upstream = (& git -C $root rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>$null)
    $Since = $(if ($LASTEXITCODE -eq 0 -and $upstream) { "$upstream".Trim() } else { 'HEAD' })
}
Write-Host "Tier: $Tier$(if ($Tier -eq 'quick') { ' (the backend tests marked slow are left out; -Full runs everything)' })."

# ---- Which suites
$scratch = Join-Path ([IO.Path]::GetTempPath()) ('mp-suites-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6))
New-Item -ItemType Directory -Force $scratch | Out-Null
$selector = @((Join-Path $root 'scripts\select_suites.py'), '--root', $root)
if ($Since) {
    & git -C $root rev-parse --verify --quiet "$Since^{commit}" 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "-Since $Since is not a commit of this repository." -ForegroundColor Red; exit 1 }
    # --relative: paths from the platform's own folder, also when it is a folder of a client's repository.
    $changed = @(& git -C $root -c core.quotepath=false diff --relative --name-only --no-renames $Since) +
               @(& git -C $root -c core.quotepath=false ls-files --others --exclude-standard)
    $why = "changed since $Since"
} elseif ($Paths.Count -gt 0) {
    $changed = $Paths
    $why = 'the paths given'
}
if ($Since -or $Paths.Count -gt 0) {
    $pathsFile = Join-Path $scratch 'paths.txt'
    [IO.File]::WriteAllLines($pathsFile, [string[]]@($changed | ForEach-Object { "$_" } | Select-Object -Unique), (New-Object Text.UTF8Encoding($false)))
    $selector += @('--paths-file', $pathsFile)
    Write-Host "$(@($changed).Count) path(s) $why."
} else {
    $selector += '--all'
}
$selection = (& $python @selector | Out-String) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $selection) { Write-Host 'Choosing the suites failed (scripts\select_suites.py).' -ForegroundColor Red; exit 1 }
$chosen = @($selection.suites)
if ($chosen.Count -eq 0) {
    Write-Host "No suite to run: $($selection.none)." -ForegroundColor Green
    Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}
Write-Host "Suites to run ($($chosen.Count)):"
foreach ($s in $chosen) { Write-Host "  $($s.name): $($s.why)" }
if ($List) {
    Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
    exit 0
}

# ---- The C# step programs the backend tests run: built and current for this checkout, or nothing runs
if (@($chosen | Where-Object { $_.name -in @('backend', 'backend tests') }).Count -gt 0) {
    . (Join-Path $PSScriptRoot 'step-programs.ps1')
    $stale = @(Get-StaleStepPrograms -Root $root -Want (Get-StepProgramsWantHere -Root $root))
    if ($stale.Count -gt 0) {
        Write-Host ''
        Write-Host "The backend tests need the C# step programs built and current for this checkout; $($stale.Count) are not:" -ForegroundColor Red
        foreach ($s in $stale) { Write-Host "  $($s.Program): $($s.Why)" }
        Write-Host 'Build them, then run the suites again: .\scripts\bootstrap.ps1 -Stage 6' -ForegroundColor Red
        Write-Host 'No suite was run: tests on missing or stale step programs would fail for that reason alone.'
        Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
        exit 1
    }
}
$env:PLATFORM_TESTS_TIER = $Tier

# ---- How to run each: a command, its folder, and its lane (suites in one lane run one after another)
$shardsScript = Join-Path $root 'scripts\backend_shards.py'
function Get-Command-For([string]$name, [string[]]$modules) {
    $backend = Join-Path $root 'backend'
    $frontend = Join-Path $root 'frontend'
    switch -Regex ($name) {
        '^backend$' { return @{ Exe = $python; Args = @($shardsScript, '--shards', "$Shards", '--tier', $Tier); Dir = $backend; Lane = 'backend' } }
        '^backend tests$' { return @{ Exe = $python; Args = @($shardsScript, '--shards', "$Shards", '--tier', $Tier, '--modules') + $modules; Dir = $backend; Lane = 'backend tests' } }
        '^seed and registrations$' {
            $modules = @(& $python -c "import sys; sys.path.insert(0, r'$root\scripts'); import select_suites; print(' '.join(select_suites.SEED_TESTS))") -split ' '
            return @{ Exe = $python; Args = @($shardsScript, '--shards', "$Shards", '--tier', $Tier, '--modules') + $modules; Dir = $backend; Lane = 'seed' }
        }
        '^reproduce$' { return @{ Exe = $python; Args = @('-m', 'tests.reproduce_on_scratch'); Dir = $backend; Lane = 'seed' } }
        '^frontend tests$' { return @{ Exe = 'npm.cmd'; Args = @('test'); Dir = $frontend; Lane = 'frontend tests' } }
        '^frontend type check$' { return @{ Exe = 'npx.cmd'; Args = @('tsc', '-b'); Dir = $frontend; Lane = 'frontend type check' } }
        '^C# (.+)$' {
            $project = Get-ChildItem (Join-Path $root 'steps') -Recurse -Filter "$($Matches[1]).csproj" |
                Where-Object { $_.FullName -notmatch '\\(bin|obj)\\' } | Select-Object -First 1
            return @{ Exe = 'dotnet'; Args = @('test', $project.FullName); Dir = $project.DirectoryName; Lane = 'C#' }
        }
        '^step (.+)$' { return @{ Exe = $python; Args = @('-m', 'unittest', 'discover', '-s', 'tests'); Dir = (Join-Path $root "steps\$($Matches[1])"); Lane = $name } }
        '^third_party code-modernization$' { return @{ Exe = $python; Args = @('-m', 'unittest', 'discover', '-s', 'scripts/tests'); Dir = (Join-Path $root 'third_party\code-modernization'); Lane = $name } }
    }
    return $null
}

function Format-Arguments([string[]]$arguments) {
    return ($arguments | ForEach-Object { if ($_ -match '[\s"]') { '"' + ($_ -replace '"', '\"') + '"' } else { $_ } }) -join ' '
}

$queue = New-Object System.Collections.ArrayList
$n = 0
foreach ($s in $chosen) {
    $command = Get-Command-For $s.name @($s.modules)
    if (-not $command) { Write-Host "Unknown suite '$($s.name)'." -ForegroundColor Red; exit 1 }
    $n++
    [void]$queue.Add([pscustomobject]@{ Name = $s.name; Command = $command; Log = (Join-Path $scratch ('{0:D2}' -f $n)) })
}

$cores = [Environment]::ProcessorCount
$limit = $(if ($MaxParallel -gt 0) { $MaxParallel } else { [Math]::Max(1, [Math]::Floor($cores / 4)) })
Write-Host "Up to $limit at a time ($cores logical processors$(if ($MaxParallel -le 0) { '; -MaxParallel to change' }))."
Write-Host ''

# ---- Run: start whatever may start, wait for one to end, report it, again
$running = @()
$busyLanes = @{}
$failed = @()
$started = Get-Date
while ($queue.Count -gt 0 -or $running.Count -gt 0) {
    foreach ($next in @($queue)) {
        if ($running.Count -ge $limit) { break }
        if ($busyLanes.ContainsKey($next.Command.Lane)) { continue }
        # A lane runs its suites in the order chosen: only its first waiting suite may start.
        $first = @($queue | Where-Object { $_.Command.Lane -eq $next.Command.Lane })[0]
        if ($first -ne $next) { continue }
        $c = $next.Command
        $process = Start-Process -FilePath $c.Exe -ArgumentList (Format-Arguments $c.Args) -WorkingDirectory $c.Dir -NoNewWindow -PassThru `
            -RedirectStandardOutput "$($next.Log).out.txt" -RedirectStandardError "$($next.Log).err.txt"
        [void]$process.Handle          # held, so the exit code can be read once it ends
        Write-Host "   started: $($next.Name)"
        $running += [pscustomobject]@{ Suite = $next; Process = $process; Since = Get-Date }
        $busyLanes[$c.Lane] = $true
        $queue.Remove($next)
    }
    Start-Sleep -Milliseconds 500
    foreach ($r in @($running | Where-Object { $_.Process.HasExited })) {
        $r.Process.WaitForExit()
        $code = $r.Process.ExitCode
        $minutes = [Math]::Round(((Get-Date) - $r.Since).TotalMinutes, 1)
        $ok = $code -eq 0
        Write-Host "== $($r.Suite.Name): $(if ($ok) { 'passed' } else { "FAILED (exit $code)" }), $minutes min" -ForegroundColor $(if ($ok) { 'Cyan' } else { 'Red' })
        $lines = @(Get-Content "$($r.Suite.Log).out.txt", "$($r.Suite.Log).err.txt" -ErrorAction SilentlyContinue | Where-Object { "$_".Trim() })
        $lines | Select-Object -Last 6 | ForEach-Object { Write-Host "   $_" }
        if (-not $ok) {
            $failed += $r.Suite.Name
            Write-Host "   full output: $($r.Suite.Log).out.txt and .err.txt"
        }
        $busyLanes.Remove($r.Suite.Command.Lane)
        $running = @($running | Where-Object { $_ -ne $r })
    }
}

Write-Host ''
$total = [Math]::Round(((Get-Date) - $started).TotalMinutes, 1)
if ($failed.Count -gt 0) {
    Write-Host "Failed: $($failed -join ', ') ($total min; logs kept in $scratch)" -ForegroundColor Red
    exit 1
}
Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "All suites passed ($($chosen.Count), $total min)." -ForegroundColor Green
exit 0
