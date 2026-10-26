<#
.SYNOPSIS
    Writes a git bundle of our master, and its SHA-256, for installing on a machine with no access to this repository
    (docs\VDI-SETUP.md, "Appendix: upgrading from a bundle of master"). Made only when asked.

.DESCRIPTION
    Writes two files into OutDir:

      master-<commit>.bundle          master and the full history it reaches (git bundle create)
      master-<commit>.bundle.sha256   its SHA-256, in the "<hash>  <file name>" form sha256sum and Get-FileHash checks use

    <commit> is master's commit, shortened to 12 characters. Installations follow master, and every commit on master
    has passed the full test suites; so the bundle is made from master only when it equals origin/master, a commit
    that has been pushed, and stops otherwise. No tag is read, created or moved.

    The bundle is checked with git bundle verify before its hash is written. Nothing is pushed or uploaded.

.PARAMETER OutDir
    Where to write the files. Default: a release folder beside the repository (outside it, so the bundle is never
    committed).

.EXAMPLE
    .\scripts\master-bundle.ps1
#>
[CmdletBinding()]
param(
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path (Split-Path -Parent $root) 'release' }

function Fail([string]$why) {
    Write-Host "Not written: $why" -ForegroundColor Red
    exit 1
}

$commit = & git -C $root rev-parse --verify --quiet refs/heads/master 2>$null
if ($LASTEXITCODE -ne 0 -or -not $commit) { Fail "there is no master in $root." }
$commit = "$commit".Trim()
$pushed = & git -C $root rev-parse --verify --quiet refs/remotes/origin/master 2>$null
if ($LASTEXITCODE -ne 0 -or "$pushed".Trim() -ne $commit) {
    Fail "master ($($commit.Substring(0, 12))) is not origin/master$(if ($pushed) { " ($("$pushed".Trim().Substring(0, 12)))" }): bundle only a commit that has been pushed. Push or pull master first (git fetch origin updates origin/master)."
}

$name = "master-$($commit.Substring(0, 12)).bundle"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$bundle = Join-Path $OutDir $name
$hashFile = "$bundle.sha256"
foreach ($f in @($bundle, $hashFile)) { if (Test-Path $f) { Remove-Item -LiteralPath $f -Force } }

& git -C $root bundle create $bundle refs/heads/master 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $bundle)) { Fail 'git bundle create failed.' }
& git -C $root bundle verify $bundle 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "git bundle verify rejected $bundle." }

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundle).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText($hashFile, "$hash  $name`n", (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Master   $commit"
Write-Host "Bundle   $bundle ($((Get-Item $bundle).Length) bytes)"
Write-Host "SHA-256  $hash"
Write-Host "Written  $hashFile"
Write-Host ''
Write-Host 'On the machine, after copying both files:'
Write-Host "  (Get-FileHash -Algorithm SHA256 $name).Hash.ToLower()   # must equal the line in $name.sha256"
Write-Host "  git bundle list-heads $name                           # must name refs/heads/master"
Write-Host '  then docs\VDI-SETUP.md, "Appendix: upgrading from a bundle of master", or for a new install:'
Write-Host "  git clone -c core.longpaths=true --branch master $name C:\MP\code"
