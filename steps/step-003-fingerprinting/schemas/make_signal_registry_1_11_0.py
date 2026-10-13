"""Writes signal-registry-1.11.0.json from 1.10.0.

1.11.0 (additive, plus one value change), gaps AccountsApi exposed:
- TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET, anticipated since 1.4.0, now emitted by dependency-assessment 1.4.0:
  target-framework-retarget becomes ready.
- PACKAGE_PROVIDED_BY_FRAMEWORK (dependency-assessment 1.4.0): a package the target's shared framework provides is a
  removal, not an upgrade (Microsoft.AspNetCore.Server.Kestrel 2.x).
- USE_IIS_INVOCATION (ApiUsageExtractor) and ASPNETCORE_HOSTING_MODEL (IisHostingExtractor): an ASP.NET Core
  application hosted in IIS through the ASP.NET Core Module.
- CONTAINER_RUNS_AS_ROOT, CONTAINER_PRIVILEGED_PORT, CONTAINER_FIXED_USER_WRITABLE_PATH (FileIndicatorExtractor):
  an existing Dockerfile or manifest that OpenShift's restricted security policy refuses or breaks. Presence is not
  readiness.
- SENSITIVE_CONFIG_KEY's value is the key's full configuration path (Section:Sub:Key), and a key whose last word only
  describes a secret (ClientCredentialType, TokenEndpoint, SecretsDir) is no longer one.
Run from this folder:  python make_signal_registry_1_11_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.10.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.11.0"

for signal in registry["signals"]:
    if signal["name"] == "SENSITIVE_CONFIG_KEY":
        signal["description"] = (
            "A configuration key whose own name matches the sensitive-key pattern (password|pwd|secret|token|apikey|"
            "api_key|connectionstring|accountkey|sharedaccesskey|credential) and whose last word does not merely describe "
            "a secret (Type, Name, Path, Dir, Url, Endpoint, Provider, Header ... : ClientCredentialType, TokenEndpoint "
            "and SecretsDir are settings) — presence only, value never read (Part G). Also read from Web Deploy "
            "SetParameters files (SetParam*.xml, SetParameters*.xml by the engagement's globs) of the project.")
        signal["value_semantics"] = (
            "one row per distinct matching key; value is the key's full configuration path (Section:Sub:Key for JSON, "
            "the appSettings key or attribute name for XML, the parameter name for SetParameters), never the secret")

PACKAGE = {"category": "PACKAGE_DEPENDENCY", "type": "PACKAGE", "extractor": "DependencyAssessment", "evidence_kind": "FILE"}
CONTAINER = {"category": "DEPLOYMENT_INDICATOR", "type": "CONFIG_ELEMENT", "extractor": "FileIndicatorExtractor", "evidence_kind": "FILE"}
registry["signals"] += [
    {
        "name": "TARGET_FRAMEWORK_BELOW_ENGAGEMENT_TARGET",
        "category": "PROJECT_METADATA",
        "type": "CONFIG_ELEMENT",
        "description": "A .NET Core or .NET 5+ project (.NETCoreApp) whose target framework is below the engagement's target "
                       "framework (engagements.target_framework). Emitted by lifecycle step 6 (dependency-assessment), which "
                       "is given the engagement's target.",
        "extractor": "DependencyAssessment",
        "evidence_kind": "FILE",
        "value_semantics": "'{from} -> {to}', located at the line declaring the target framework: the project file, else the "
                           "nearest Directory.Build.props above it that declares one.",
    },
    {
        "name": "PACKAGE_PROVIDED_BY_FRAMEWORK",
        **PACKAGE,
        "description": "A direct package the target framework's shared framework already provides, at a version it carries "
                       "(the SDK's PackageOverrides.txt, schemas/shared-frameworks-1.0.0.json): Microsoft.NETCore.App's for "
                       "every project, Microsoft.AspNetCore.App's for a Web or Razor SDK project or one with a "
                       "FrameworkReference to it. A removal, not an upgrade: dependency-assessment outcome framework_provided.",
        "value_semantics": "'{id} {from}: provided by {shared framework} {target}'. One row per project per package, located at "
                           "the PackageReference line.",
    },
    {
        "name": "USE_IIS_INVOCATION",
        "category": "HOSTING_INDICATOR",
        "type": "API_INVOCATION",
        "description": "A UseIIS() or UseIISIntegration() call: the application is hosted behind IIS through the ASP.NET Core "
                       "Module.",
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "the method called (UseIIS or UseIISIntegration); one row per distinct method per file. Syntax-only: "
                           "confidence 0.9 for a type-qualified member, 0.8 for a bare method name.",
    },
    {
        "name": "ASPNETCORE_HOSTING_MODEL",
        "category": "HOSTING_INDICATOR",
        "type": "CONFIG_ELEMENT",
        "description": "How an ASP.NET Core application is hosted in IIS through the ASP.NET Core Module: the project file's "
                       "<AspNetCoreHostingModel>, a web.config's <aspNetCore hostingModel>, or the module handler "
                       "(modules=\"AspNetCoreModule[V2]\") with no model stated.",
        "extractor": "IisHostingExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "inprocess, outofprocess or unspecified; located at the declaring line.",
    },
    {
        "name": "CONTAINER_RUNS_AS_ROOT",
        **CONTAINER,
        "description": "An existing Dockerfile whose final stage never switches to a non-root user or switches to root, or a "
                       "manifest setting runAsUser: 0, runAsNonRoot: false, privileged: true or allowPrivilegeEscalation: "
                       "true. OpenShift's restricted security context constraint refuses it.",
        "value_semantics": "the instruction or manifest line as written ('no USER instruction: the image runs as root' when "
                           "absent), located at its line. Repository-level for a file outside every project directory.",
    },
    {
        "name": "CONTAINER_PRIVILEGED_PORT",
        **CONTAINER,
        "description": "An existing Dockerfile or manifest binding a port below 1024: EXPOSE, a listening URL or port variable "
                       "(ASPNETCORE_URLS, ASPNETCORE_HTTP_PORTS, HTTP_PORTS) in the final stage, or a containerPort. A "
                       "non-root process cannot bind it.",
        "value_semantics": "the instruction or manifest line as written, located at its line.",
    },
    {
        "name": "CONTAINER_FIXED_USER_WRITABLE_PATH",
        **CONTAINER,
        "description": "Writable paths that assume a fixed user: a chown in the final stage to an owner whose group is not 0, or "
                       "an owner-only chmod (700, 600), with no later chmod giving group 0 the owner's rights (g=u); or a "
                       "manifest's fixed runAsUser or fsGroup. OpenShift runs the image with an arbitrary UID in group 0.",
        "value_semantics": "the instruction or manifest line as written, located at its line.",
    },
]

out = HERE / "signal-registry-1.11.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
