"""Writes signal-registry-1.16.0.json from 1.15.0.

1.16.0 (additive), what a conversion review found on Linux and in an SSIS job:
- EVENT_LOG_USAGE (ApiUsageExtractor): the Windows Event Log (System.Diagnostics.EventLog: WriteEntry, SourceExists,
  CreateEventSource and the like, or an EventLog instance). It throws PlatformNotSupportedException on Linux.
- BACKSLASH_PATH_BUILDING (PathLiteralExtractor): a path built by joining parts with a backslash literal (dir + "\\" +
  name, string.Concat(dir, @"\", name), $"{dir}\\{name}"). On Linux a backslash is part of the file name.
- SSIS_PACKAGE_EXECUTION (ApiUsageExtractor): a call that loads or runs an SSIS package through the SSIS runtime
  (Application.LoadPackage, LoadFromSqlServer, LoadFromDtsServer, Package.Execute), in a file that imports
  Microsoft.SqlServer.Dts.Runtime: the code a reimplementation of the package changes.
Run from this folder:  python make_signal_registry_1_16_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.15.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.16.0"

registry["signals"] += [
    {
        "name": "EVENT_LOG_USAGE",
        "category": "SOURCE_CONSTRUCT",
        "type": "API_INVOCATION",
        "description": "The Windows Event Log used in code: a System.Diagnostics.EventLog member (WriteEntry, WriteEvent, "
                       "SourceExists, CreateEventSource, DeleteEventSource, Exists, Delete, GetEventLogs, "
                       "LogNameFromSourceName) or a new EventLog instance. Windows-only: it throws "
                       "PlatformNotSupportedException on Linux.",
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "the fully qualified member (System.Diagnostics.EventLog.WriteEntry), or "
                           "System.Diagnostics.EventLog for an instance; one row per distinct value per file, a line "
                           "span per use. Syntax-only: confidence 0.9.",
    },
    {
        "name": "BACKSLASH_PATH_BUILDING",
        "category": "HOSTING_INDICATOR",
        "type": "LITERAL",
        "description": "A path built by joining parts with a backslash: a string literal that a backslash starts or ends "
                       "(\"\\\\\", @\"\\\", \"\\\\logs\\\\\"), used as an operand of +, an argument of string.Concat, or "
                       "interpolated-string text beside an interpolation. On Linux a backslash is an ordinary character "
                       "of a file name. A drive-letter or UNC path is its own signal; text passed to a Regex is not read.",
        "extractor": "PathLiteralExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "the literal's text (\\, \\logs\\); one row per distinct text per file, a line per use.",
    },
    {
        "name": "SSIS_PACKAGE_EXECUTION",
        "category": "EXECUTION_INDICATOR",
        "type": "API_INVOCATION",
        "description": "Code that loads or runs an SSIS package through the SSIS runtime: Application.LoadPackage, "
                       "LoadFromSqlServer, LoadFromSqlServer2, LoadFromDtsServer, or Execute, in a file that imports "
                       "Microsoft.SqlServer.Dts.Runtime (or on a receiver written with that namespace). The place a "
                       "reimplementation of the package changes.",
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "Microsoft.SqlServer.Dts.Runtime.Application.<method> for a load, "
                           "Microsoft.SqlServer.Dts.Runtime.Package.Execute for a run; one row per distinct value per "
                           "file, a line span per use, with the enclosing type and member. Syntax-only: confidence 0.8.",
    },
]

out = HERE / "signal-registry-1.16.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
