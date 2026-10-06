"""Writes signal-registry-1.7.0.json from 1.6.0.

1.7.0 (additive):
- UNQUALIFIED_HOSTNAME_URL — a URL whose host is a single label (appsrv0341).
- WINDOWS_PATH_LITERAL, UNC_PATH_LITERAL, SENSITIVE_CONFIG_KEY,
  CONNECTION_STRING_CONFIG and WINDOWS_AUTH_CONNECTION_STRING_CONFIG are also
  read from Web Deploy SetParameters files (CustomFiles\\<Project>\\SetParamFiles\\
  <ENV>\\SetParam.xml), found by the engagement's globs.
Run from this folder:  python make_signal_registry_1_7_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.6.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.7.0"

SETPARAM = (" Also read from Web Deploy SetParameters files (SetParam*.xml, SetParameters*.xml by the engagement's globs) "
            "of the project, by the same rules.")
for signal in registry["signals"]:
    if signal["name"] in ("WINDOWS_PATH_LITERAL", "UNC_PATH_LITERAL", "SENSITIVE_CONFIG_KEY", "CONNECTION_STRING_CONFIG",
                          "WINDOWS_AUTH_CONNECTION_STRING_CONFIG"):
        description = signal["description"].rstrip()
        signal["description"] = (description if description.endswith(".") else description + ".") + SETPARAM

after = next(i for i, s in enumerate(registry["signals"]) if s["name"] == "UNC_PATH_LITERAL")
registry["signals"].insert(after + 1, {
    "name": "UNQUALIFIED_HOSTNAME_URL",
    "category": "ENDPOINT_INDICATOR",
    "type": "LITERAL",
    "description": ("A URL (http, https, net.tcp, net.pipe, ws, wss, ftp) whose host is a single label such as appsrv0341, in a C# "
                    "string literal, a configuration value or a SetParameters value. It resolves on Windows through NetBIOS or the "
                    "DNS suffix search; in an OpenShift pod only if the cluster's DNS search domains cover it. localhost, IP "
                    "addresses and placeholders are not matched; secret-named values and connection strings are never read."),
    "extractor": "PathLiteralExtractor",
    "evidence_kind": "FILE",
    "value_semantics": "the host only, lowercased — never the URL's path, query or credentials; one row per distinct host per file.",
})

out = HERE / "signal-registry-1.7.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
