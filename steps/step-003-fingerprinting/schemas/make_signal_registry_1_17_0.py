"""Writes signal-registry-1.17.0.json from 1.16.0.

1.17.0, what a review of a prepared conversion found in class libraries on .NET Framework (framework-only APIs not
detected), additive except one narrowed description:
- LINQ to SQL: SYSTEM_DATA_LINQ_NAMESPACE, SYSTEM_DATA_LINQ_ASSEMBLY (FrameworkReferenceExtractor), DATACONTEXT_BASE_CLASS
  (InheritanceExtractor) and DBML_FILE (FileIndicatorExtractor).
- Windows Identity Foundation: SYSTEM_IDENTITYMODEL_SERVICES_NAMESPACE, SYSTEM_IDENTITYMODEL_SERVICES_ASSEMBLY
  (FrameworkReferenceExtractor) and WIF_API_USAGE (ApiUsageExtractor).
- Windows Workflow Foundation: SYSTEM_ACTIVITIES_NAMESPACE, SYSTEM_ACTIVITIES_ASSEMBLY (FrameworkReferenceExtractor) and
  WORKFLOW_XAML_FILE (FileIndicatorExtractor).
- CURRENT_USER_IDENTITY_CHECK (ApiUsageExtractor): the signed-in Windows user's identity or group checks, which a token's
  claims can replace, told apart from directory queries for other users and groups (DIRECTORY_SERVICES_USAGE).
- UNQUALIFIED_HOSTNAME_URL (no new name): not reported for a C# string literal that is an identifier written as a URI (a
  claim type, an XML namespace) rather than an endpoint.
None of these has an implementation on the target framework, nor a package that provides one.
Run from this folder:  python make_signal_registry_1_17_0.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
registry = json.loads((HERE / "signal-registry-1.16.0.json").read_text(encoding="utf-8"))
registry["registry_version"] = "1.17.0"


def namespace(name: str, prefix: str, what: str) -> dict:
    return {
        "name": name,
        "category": "FRAMEWORK_REFERENCE",
        "type": "NAMESPACE",
        "description": f"A 'using {prefix}' (or sub-namespace) directive: {what}",
        "extractor": "FrameworkReferenceExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "occurrence count per file; value is the exact namespace written",
    }


def assembly(name: str, simple: str, what: str) -> dict:
    return {
        "name": name,
        "category": "FRAMEWORK_REFERENCE",
        "type": "ASSEMBLY",
        "description": f"A raw <Reference Include=\"{simple}\"> in a non-SDK project file: {what}",
        "extractor": "FrameworkReferenceExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "occurrence count per project file; value is the assembly simple name",
    }


LINQ = "LINQ to SQL, which has no implementation on the target framework"
WIF = "Windows Identity Foundation, which has no implementation on the target framework"
WF = "Windows Workflow Foundation, which has no implementation on the target framework"

registry["signals"] += [
    namespace("SYSTEM_DATA_LINQ_NAMESPACE", "System.Data.Linq", LINQ),
    assembly("SYSTEM_DATA_LINQ_ASSEMBLY", "System.Data.Linq", LINQ),
    {
        "name": "DATACONTEXT_BASE_CLASS",
        "category": "SOURCE_CONSTRUCT",
        "type": "BASE_CLASS",
        "description": "A type deriving DataContext (LINQ to SQL's context, System.Data.Linq)",
        "extractor": "InheritanceExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "count of matching types per file",
    },
    {
        "name": "DBML_FILE",
        "category": "FILE_INDICATOR",
        "type": "FILE_PRESENCE",
        "description": "Presence of a .dbml LINQ to SQL mapping file",
        "extractor": "FileIndicatorExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "count of matching files",
    },
    namespace("SYSTEM_IDENTITYMODEL_SERVICES_NAMESPACE", "System.IdentityModel.Services", WIF),
    assembly("SYSTEM_IDENTITYMODEL_SERVICES_ASSEMBLY", "System.IdentityModel.Services", WIF),
    {
        "name": "WIF_API_USAGE",
        "category": "SOURCE_CONSTRUCT",
        "type": "API_INVOCATION",
        "description": "Windows Identity Foundation used in code: a member of FederatedAuthentication; "
                       "SessionAuthenticationModule, WSFederationAuthenticationModule or FederationConfiguration used as "
                       "a type (in a file importing System.IdentityModel.Services, or written fully qualified); or a type "
                       "deriving ClaimsAuthenticationManager or ClaimsAuthorizationManager. None has an implementation on "
                       "the target framework.",
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "System.IdentityModel.Services.FederatedAuthentication.<member>, "
                           "System.IdentityModel.Services.<type>, or System.Security.Claims.<manager type>; one row per "
                           "distinct value per file, a line span per use. Syntax-only: confidence 0.9 for a "
                           "type-qualified member or a fully qualified type, 0.8 for a type name matched by the file's "
                           "imports.",
    },
    namespace("SYSTEM_ACTIVITIES_NAMESPACE", "System.Activities", WF),
    assembly("SYSTEM_ACTIVITIES_ASSEMBLY", "System.Activities", WF),
    {
        "name": "WORKFLOW_XAML_FILE",
        "category": "FILE_INDICATOR",
        "type": "FILE_PRESENCE",
        "description": "A Windows Workflow Foundation workflow: a .xaml file whose first 64 KB hold the activities XAML "
                       "namespace (http://schemas.microsoft.com/netfx/2009/xaml/activities), or a .xamlx workflow "
                       "service. A .xaml file is also XAML_FILE.",
        "extractor": "FileIndicatorExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "count of matching files",
    },
    {
        "name": "CURRENT_USER_IDENTITY_CHECK",
        "category": "SOURCE_CONSTRUCT",
        "type": "API_INVOCATION",
        "description": "The signed-in Windows user's identity or group checks, which a token's claims can replace: "
                       "WindowsIdentity.GetCurrent, a new WindowsPrincipal, UserPrincipal.Current, Thread.CurrentPrincipal, "
                       "or any IsInRole call. A directory query for another user or group is DIRECTORY_SERVICES_USAGE, "
                       "which a token cannot replace.",
        "extractor": "ApiUsageExtractor",
        "evidence_kind": "FILE",
        "value_semantics": "System.Security.Principal.WindowsIdentity.GetCurrent, "
                           "System.Security.Principal.WindowsPrincipal, "
                           "System.DirectoryServices.AccountManagement.UserPrincipal.Current, "
                           "System.Threading.Thread.CurrentPrincipal or System.Security.Principal.IPrincipal.IsInRole; one "
                           "row per distinct value per file, a line span per use, with the enclosing type and member. "
                           "Syntax-only: confidence 0.9 for a type-qualified member, 0.8 for IsInRole on any receiver.",
    },
]

for signal in registry["signals"]:
    if signal["name"] == "UNQUALIFIED_HOSTNAME_URL":
        signal["description"] += (" A C# string literal that is an identifier written as a URI is not matched (1.17.0): "
                                  "a URL with a claims path segment; an argument of new Claim, FindFirst, FindAll, "
                                  "FindFirstValue, HasClaim, new ClaimsIdentity or XNamespace.Get, or a value given to an "
                                  "XNamespace; the value of a constant, field, property or variable named like ClaimType, "
                                  "Claim, Namespace or Xmlns, or one declared in a type named like ClaimTypes or Claims; "
                                  "an attribute argument named Namespace, or an XmlnsDefinition argument.")

out = HERE / "signal-registry-1.17.0.json"
out.write_text(json.dumps(registry, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
print(f"wrote {out.name}: {len(registry['signals'])} signals")
