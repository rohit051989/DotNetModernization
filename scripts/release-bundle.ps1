<#
.SYNOPSIS
    Writes a git bundle of a release tag, and its SHA-256, for installing on a machine with no access to this
    repository (01-ENVIRONMENT-SETUP.md section 10, "Installing from a release bundle").

.DESCRIPTION
    Writes two files into OutDir:

      <Tag>.bundle          the tag and the full history it reaches (git bundle create)
      <Tag>.bundle.sha256   its SHA-256, in the "<hash>  <file name>" form sha256sum and Get-FileHash checks use

    The bundle is checked with git bundle verify before its hash is written. Nothing is pushed or uploaded.

.PARAMETER Tag
    The release tag to bundle. Default: rbc-release-1.

.PARAMETER OutDir
    Where to write the files. Default: a release folder beside the repository (outside it, so the bundle is never
    committed).

.EXAMPLE
    .\scripts\release-bundle.ps1 -Tag rbc-release-1
#>
[CmdletBinding()]
param(
    [string]$Tag = 'rbc-release-1',
    [string]$OutDir = ''
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path (Split-Path -Parent $root) 'release' }

function Fail([string]$why) {
    Write-Host "Not written: $why" -ForegroundColor Red
    exit 1
}

$commit = (& git -C $root rev-parse --verify --quiet "refs/tags/$Tag^{commit}" 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $commit) { Fail "there is no tag $Tag in $root." }

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$bundle = Join-Path $OutDir "$Tag.bundle"
$hashFile = "$bundle.sha256"
foreach ($f in @($bundle, $hashFile)) { if (Test-Path $f) { Remove-Item -LiteralPath $f -Force } }

& git -C $root bundle create $bundle "refs/tags/$Tag" 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $bundle)) { Fail 'git bundle create failed.' }
& git -C $root bundle verify $bundle 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "git bundle verify rejected $bundle." }

$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundle).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText($hashFile, "$hash  $Tag.bundle`n", (New-Object System.Text.UTF8Encoding($false)))

Write-Host "Tag      $Tag at $commit"
Write-Host "Bundle   $bundle ($((Get-Item $bundle).Length) bytes)"
Write-Host "SHA-256  $hash"
Write-Host "Written  $hashFile"
Write-Host ''
Write-Host 'On the VDI, after copying both files:'
Write-Host "  (Get-FileHash -Algorithm SHA256 $Tag.bundle).Hash.ToLower()   # must equal the line in $Tag.bundle.sha256"
Write-Host "  git bundle list-heads $Tag.bundle                                # must name refs/tags/$Tag"
Write-Host "  git clone -c core.longpaths=true --branch $Tag $Tag.bundle C:\ModernizationPlatform\code"
