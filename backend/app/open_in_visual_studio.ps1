<#
.SYNOPSIS
    Opens a file at a line in a running instance of one Visual Studio installation, through that installation's own
    versioned automation object (DTE). Run by app\editors.py; prints one line of JSON:
    {"state": "at_line" | "not_running" | "failed", "reason": ...}.

.DESCRIPTION
    A running Visual Studio registers its automation object in the running object table of the session it runs in,
    under its versioned name and process id: !VisualStudio.DTE.17.0:<pid> for 2022, !VisualStudio.DTE.18.0:<pid> for
    2026. This looks only at entries with -ProgId's name, and accepts an instance only when its program (DTE.FullName)
    is -Devenv: another installation of the same version, or another product built on the Visual Studio shell (SQL
    Server Management Studio), is never used. No version-independent registration is read. It opens the file, moves
    the caret to the line and brings the window forward. Nothing on the machine changes. With -WaitSeconds, it waits
    that long for an instance just started to register.
#>
param(
    [Parameter(Mandatory)][string]$ProgId,
    [Parameter(Mandatory)][string]$Devenv,
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][int]$Line,
    [int]$WaitSeconds = 0
)

function Answer([string]$state, [string]$reason = '') {
    [pscustomobject]@{ state = $state; reason = $reason } | ConvertTo-Json -Compress
    exit 0
}

try {
    Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

public static class ModernizationPlatformRot {
    [DllImport("ole32.dll")] static extern int GetRunningObjectTable(int reserved, out IRunningObjectTable table);
    [DllImport("ole32.dll")] static extern int CreateBindCtx(int reserved, out IBindCtx context);

    // The objects registered under names that start with the prefix, such as "!VisualStudio.DTE.18.0:".
    public static object[] Find(string prefix) {
        var found = new List<object>();
        IRunningObjectTable table;
        IBindCtx context;
        IEnumMoniker monikers;
        if (GetRunningObjectTable(0, out table) != 0 || CreateBindCtx(0, out context) != 0) return found.ToArray();
        table.EnumRunning(out monikers);
        var one = new IMoniker[1];
        while (monikers.Next(1, one, IntPtr.Zero) == 0) {
            string name;
            try { one[0].GetDisplayName(context, null, out name); } catch { continue; }
            if (!name.StartsWith(prefix, StringComparison.OrdinalIgnoreCase)) continue;
            object entry;
            if (table.GetObject(one[0], out entry) == 0) found.Add(entry);
        }
        return found.ToArray();
    }
}
'@
} catch {
    if (-not ('ModernizationPlatformRot' -as [type])) { Answer 'failed' "the running object table could not be read: $($_.Exception.Message)" }
}

$wanted = [System.IO.Path]::GetFullPath($Devenv)
function Find-Instance {
    foreach ($candidate in [ModernizationPlatformRot]::Find("!$ProgId`:")) {
        # A busy instance rejects the call for a moment: ask again before passing it over, or a second one is started.
        for ($attempt = 0; $attempt -lt 5; $attempt++) {
            try {
                if ([System.IO.Path]::GetFullPath($candidate.FullName) -ieq $wanted) { return $candidate }
                break                 # another installation's program: not ours
            } catch { Start-Sleep -Milliseconds 1000 }
        }
    }
    return $null
}

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$dte = $null
do {
    $dte = Find-Instance
    if ($dte) { break }
    if ((Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
} while ((Get-Date) -lt $deadline)
if (-not $dte) { Answer 'not_running' "no running $Devenv in this session ($ProgId)" }

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
