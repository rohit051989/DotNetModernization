"""Writes signal-registry-1.14.0.json from 1.13.0.

1.14.0 (additive), Serilog sinks beyond appsettings File sinks:
- SERILOG_FILE_SINK_USAGE (ApiUsageExtractor): a Serilog File or RollingFile sink configured in code
  (.WriteTo.File(...), .WriteTo.RollingFile(...), or inside a wrapper: .WriteTo.Async(a => a.File(...))).
  The code-configured counterpart of SERILOG_FILE_SINK_CONFIG.
- SERILOG_CONSOLE_SINK_USAGE (ApiUsageExtractor): a Serilog Console sink configured in code (.WriteTo.Console()).
- SERILOG_CONSOLE_SINK_CONFIG (ConfigurationExtractor): a Serilog sink named Console under the Serilog section of
  appsettings*.json.
The Console signals say whether logs already reach standard output beside a File sink.
Run from this folder:  python make_signal_registry_1_14_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.13.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.14.0"

registry["signals"] += [
    {
        "name": "SERILOG_FILE_SINK_USAGE",
        "category": "CONFIGURATION_INDICATOR",
        "type": "API_INVOCATION",
        "description": "A Serilog File or RollingFile sink configured in code: .WriteTo.File(...), .WriteTo.RollingFile(...) "
                       "(or AuditTo), or the same sink inside a wrapper whose lambda receives the sink configuration "
                       "(.WriteTo.Async(a => a.File(...)), .WriteTo.Conditional(..., wt => wt.File(...))). Only in a file "
                       "that uses Serilog. The code-configured counterpart of SERILOG_FILE_SINK_CONFIG.",
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "the sink's path when written as a string literal (the first argument, or path:), else null; "
                           "one row per distinct path per file, a line span per use. Syntax-only: confidence 0.9.",
    },
    {
        "name": "SERILOG_CONSOLE_SINK_USAGE",
        "category": "CONFIGURATION_INDICATOR",
        "type": "API_INVOCATION",
        "description": "A Serilog Console sink configured in code: .WriteTo.Console(...) (or AuditTo), or inside a wrapper "
                       "(.WriteTo.Async(a => a.Console())). Only in a file that uses Serilog. Logs already reach standard "
                       "output.",
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "always 'Console'; one row per file, a line span per use. Syntax-only: confidence 0.9.",
    },
    {
        "name": "SERILOG_CONSOLE_SINK_CONFIG",
        "category": "CONFIGURATION_INDICATOR",
        "type": "CONFIG_ELEMENT",
        "description": "A Serilog sink named Console under the Serilog section of appsettings*.json, including one nested in "
                       "an Async sink's configure. The Console counterpart of SERILOG_FILE_SINK_CONFIG.",
        "extractor": "ConfigurationExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "always 'Console'; one row per file, a line per sink.",
    },
]

out = HERE / "signal-registry-1.14.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
