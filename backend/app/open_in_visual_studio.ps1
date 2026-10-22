<#
.SYNOPSIS
    Opens a file at a line in the Visual Studio that is running, through Visual Studio's automation object (DTE).
    Run by app\editors.py; prints one line of JSON: {"state": "at_line" | "not_running" | "failed", "reason": ...}.

.DESCRIPTION
    A running Visual Studio registers its automation object (for example VisualStudio.DTE.17.0) for the session it
    runs in. This finds it, opens the file, moves the caret to the line and brings the window forward. Nothing on the
    machine changes. With -WaitSeconds, it waits that long for an instance just started to register.
#>
param(
    [Parameter(Mandatory)][string]$ProgId,
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][int]$Line,
    [int]$WaitSeconds = 0
)

function Answer([string]$state, [string]$reason = '') {
    [pscustomobject]@{ state = $state; reason = $reason } | ConvertTo-Json -Compress
    exit 0
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$dte = $null
do {
    try { $dte = [System.Runtime.InteropServices.Marshal]::GetActiveObject($ProgId) } catch { $dte = $null }
    if ($dte) { break }
    if ((Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
} while ((Get-Date) -lt $deadline)
if (-not $dte) { Answer 'not_running' "no $ProgId in this session" }

# Visual Studio rejects calls while it is busy (loading, a dialog open): try for a while before giving up.
$last = ''
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $null = $dte.ItemOperations.OpenFile($Path)
        $dte.ActiveDocument.Selection.GotoLine($Line, $true)
        $dte.MainWindow.Activate()
        Answer 'at_line'
    } catch {
        $last = $_.Exception.Message
        Start-Sleep -Milliseconds 1500
    }
}
Answer 'failed' $last
