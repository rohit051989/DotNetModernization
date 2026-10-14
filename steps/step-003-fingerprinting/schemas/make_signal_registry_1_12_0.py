"""Writes signal-registry-1.12.0.json from 1.11.0.

1.12.0, gaps the first Copilot pilot run (AccountsApi.Net10) exposed:
- SENSITIVE_CONFIG_KEY records the leaf: a sensitive section is walked, and each leaf under it that holds the
  secret is recorded by its full path (EnterpriseAuthentication:Token:SigningKey, not EnterpriseAuthentication:Token).
- VAULT_SECRET_REFERENCE (ConfigurationExtractor): a configuration value that is an Enterprise.Vault reference
  (vault:<name>), resolved at run time by AddEnterpriseVaultSecrets. A reference, not a secret: such a key is a vault
  reference only, never SENSITIVE_CONFIG_KEY.
- CONFIG_FILE_UNPARSEABLE (ConfigurationExtractor): a configuration file that cannot be parsed is a finding, never
  skipped silently.
- CUSTOM_FILE_LOGGER_PROVIDER (FileLoggerProviderExtractor): an ILoggerProvider that writes files.
- WINDOWS_BUILD_PIPELINE (FileIndicatorExtractor): Windows batch scripts, and pipelines that assume Windows agents.
- WINDOWS_PATH_LITERAL / UNC_PATH_LITERAL in configuration carry the configuration key in the evidence's `member`.
Run from this folder:  python make_signal_registry_1_12_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.11.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.12.0"

for signal in registry["signals"]:
    if signal["name"] == "SENSITIVE_CONFIG_KEY":
        signal["description"] += (" From 1.12.0 a sensitive section is walked: each leaf under it that holds the secret "
                                  "(named as a secret, ending in Key, or a vault reference) is recorded by its full path, "
                                  "and a leaf holding a vault reference is VAULT_SECRET_REFERENCE instead.")
        signal["value_semantics"] = ("one row per distinct matching key; value is the full configuration path of the leaf "
                                     "(Section:Sub:Key), or of the section when no leaf under it holds the secret; never the secret")
    if signal["name"] in ("WINDOWS_PATH_LITERAL", "UNC_PATH_LITERAL"):
        signal["value_semantics"] += (" From 1.12.0, in a configuration file, each evidence entry's member is the configuration "
                                      "key the value sits under (FileContent:FilePath; an XML setting's key or name, else element@attribute).")

registry["signals"] += [
    {
        "name": "VAULT_SECRET_REFERENCE",
        "category": "CONFIGURATION_INDICATOR",
        "type": "CONFIG_ELEMENT",
        "description": "A configuration value that is an Enterprise.Vault reference, vault:<name> (a connection string, a key, a "
                       "certificate), resolved at run time by AddEnterpriseVaultSecrets from the secrets directory. A reference, "
                       "not a secret: the value is read only to see its prefix.",
        "extractor": "ConfigurationExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "the full configuration path of the key holding the reference; one row per key per file.",
    },
    {
        "name": "CONFIG_FILE_UNPARSEABLE",
        "category": "CONFIGURATION_INDICATOR",
        "type": "CONFIG_ELEMENT",
        "description": "An appsettings*.json, web.config or app.config that cannot be parsed (an unescaped backslash in a JSON "
                       "string). The application fails to start with it, and nothing in it could be read.",
        "extractor": "ConfigurationExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "where parsing stopped: 'invalid JSON at line L, position P' (or XML), located at that line; never the text there.",
    },
    {
        "name": "CUSTOM_FILE_LOGGER_PROVIDER",
        "category": "SOURCE_CONSTRUCT",
        "type": "BASE_CLASS",
        "description": "A class implementing ILoggerProvider in a source file that writes to the file system (File.AppendAllText, "
                       "StreamWriter, FileStream ...): a custom logging provider that writes log files.",
        "extractor": "FileLoggerProviderExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "the class name, located at its declaration.",
    },
    {
        "name": "WINDOWS_BUILD_PIPELINE",
        "category": "DEPLOYMENT_INDICATOR",
        "type": "CONFIG_ELEMENT",
        "description": "A build or pipeline file that assumes Windows: a .bat or .cmd script; a CI workflow (GitHub Actions, Azure "
                       "Pipelines, GitLab CI) running on a Windows agent or calling a Windows workflow; a Jenkinsfile with a "
                       "Windows agent label or bat / powershell steps.",
        "extractor": "FileIndicatorExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "what was found ('Windows batch script package.bat', 'runner: windows-latest', 'Jenkins bat step'), "
                           "located at its line. Repository-level for a file outside every project directory.",
    },
]

out = HERE / "signal-registry-1.12.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
