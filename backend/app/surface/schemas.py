"""The repository Surface section — 29-STEPS-004-005-INVENTORIES.md Part D.
Inbound: step 4's entry points. Outbound: step 5's invocations."""

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

EntryPointKind = Literal[
    "http_controller_action",
    "http_minimal_api",
    "wcf_operation",
    "asmx_web_method",
    "grpc_service_method",
    "signalr_hub_method",
    "message_consumer",
    "hosted_service",
    "scheduled_job",
    "console_main",
    "webforms_page",
    "razor_page",
    "windows_service",
    "http_handler",
    "global_asax",
    "owin_startup",
    "blazor_component",
    "azure_function",
    "desktop_app",
]
AuthDeclared = Literal["declared", "none_declared", "not_assessed"]
Origin = Literal["application", "framework"]
EntryClass = Literal["request", "lifecycle"]
ProjectScanStatus = Literal["SCANNED", "SKIPPED", "FAILED"]


class EntryPointOut(BaseModel):
    id: str = Field(description="Derived, stable across rescans: sha256 over repository, project, kind, handler, route and verb, truncated.")
    kind: EntryPointKind
    origin: Origin = Field(
        description="'application' (code in the repository) or 'framework' (a registered framework or package type — "
        "kept for the move to middleware, but it migrates through its package's own path, not by rewriting)."
    )
    origin_reconciled_from: Origin | None = Field(
        None,
        description="Set when step 11 corrected the origin estate-wide (31-STEP-011 Part E4): step 4's own value, "
        "which `origin` replaces. Step 4's rows are never rewritten; this overlay is applied when read.",
    )
    origin_reconciliation_reason: str | None = Field(None, description="Why step 11 reconciled the origin, when it did.")
    entry_class: EntryClass = Field(
        description="'request' (a caller, message or trigger enters — what risk scoring, contract snapshots and test "
        "generation read) or 'lifecycle' (bootstrap and wiring: Global.asax, OWIN startup, HTTP modules, services, mains)."
    )
    handler_type: str = Field(description="The handling type as written, without namespace.")
    handler_member: str | None = Field(description="The handling member; null where the type itself is the entry point (a WebForms page).")
    file_path: str = Field(description="Repository-relative path of the handler's source file.")
    line_start: int
    line_end: int
    detail: dict[str, Any] = Field(
        description="The kind-specific block, camelCase as in the artifact: http {verb, routeTemplate, routing, parameters, "
        "returnType, authorisation, ...}, wcf, asmx, grpc, signalR, messaging, schedule, hosted, console or webForms."
    )
    confidence: float = Field(description="Below 1.0 only with a reason in confidence_reasons (syntax-only analysis).")
    confidence_reasons: list[str]
    auth_declared: AuthDeclared | None = Field(
        description="Authentication as declared in source and config: 'declared', 'none_declared' (nothing declared, or "
        "declared waived — [AllowAnonymous], a WCF endpoint with no client credential, an anonymous function) or "
        "'not_assessed' (where it would be declared says nothing readable). Null where it does not apply (hosted services, "
        "jobs, consumers, mains, application hooks). Gateway, proxy and header-based authentication are not visible to "
        "static analysis, so none_declared is a review prompt, not a security finding."
    )


class ProjectEntryPointsOut(BaseModel):
    project_id: uuid.UUID
    project_path: str
    status: ProjectScanStatus
    skip_reason: str | None
    request_entry_point_count: int
    lifecycle_hook_count: int
    count_by_kind: dict[str, int]
    count_by_origin: dict[str, int]
    count_by_verb: dict[str, int]
    no_declared_authentication_count: int
    authorisation_not_assessed_count: int
    global_authorisation: list[str] = Field(description="Project-wide authorisation written in source, with its location; already applied to the entry points it covers.")
    conventional_routes: list[str] = Field(description="Conventional route tables as written. Never used to guess a conventional action's template.")
    entry_points: list[EntryPointOut]


class EntryPointInventoryOut(BaseModel):
    repository_id: uuid.UUID
    scanner_version: str
    skip_source: str = Field(description="'application-fingerprint' (step 3's verdict) or 'solution-project-inventory' (step 2's rule, when no fingerprint was produced).")
    scanned_at: datetime.datetime | None
    entry_point_count: int
    request_entry_point_count: int = Field(description="Where external work enters — what downstream steps count.")
    lifecycle_hook_count: int = Field(description="Bootstrap and wiring; inventoried, never counted as surface.")
    count_by_kind: dict[str, int]
    count_by_origin: dict[str, int]
    count_by_verb: dict[str, int]
    no_declared_authentication_count: int = Field(description="Request entry points with auth_declared none_declared; lifecycle hooks never count.")
    authorisation_not_assessed_count: int
    auth_declared_scope: str = Field(description="What auth_declared can and cannot see — always shown with it.")
    capabilities_manifest_version: str | None = Field(description="The capability manifest the scan ran against; null for a pre-2.0.0 scan.")
    capability_kinds: list[str] = Field(description="The entry-point kinds that scan looked for. A kind not listed was not looked for.")
    projects: list[ProjectEntryPointsOut] = Field(description="Every project step 2 found, sorted by path, including skipped ones.")


class CapabilityKind(BaseModel):
    kind: str
    label: str
    detects: str
    identified_by: str
    auth_declared: str
    added_in: str
    entry_class: str
    found_in_estate: int = Field(description="Entry points of this kind across every repository's latest scan.")
    repositories_with_kind: int


class NotCoveredPattern(BaseModel):
    pattern: str
    marker: str
    note: str


class EntryPointCapabilitiesOut(BaseModel):
    manifest_version: str
    scanner_version: str
    description: str
    auth_declared_scope: str
    kinds: list[CapabilityKind]
    not_covered: list[NotCoveredPattern] = Field(description="Patterns step 4 does not look for: their absence from results means nothing.")
    repositories_scanned: int
    repositories_on_this_manifest: int = Field(description="Repositories whose latest scan ran against this manifest version.")


# ---------- outbound: step 5 ----------

OutboundMechanism = Literal[
    "http_client",
    "soap_client",
    "grpc_client",
    "database",
    "message_producer",
    "message_consumer",
    "cache",
    "secret_store",
    "file_share",
    "smtp",
    "ldap",
]
LinuxVerdict = Literal["incompatible", "requires_change", "unknown", "compatible"]
EndpointResolution = Literal["resolved", "partial", "unresolved"]
OutboundUsage = Literal["used", "unused"]


class OutboundInvocationOut(BaseModel):
    id: str = Field(description="Derived, stable across rescans: sha256 over repository, project, mechanism, normalised endpoint and contract, truncated.")
    mechanism: OutboundMechanism
    usage: OutboundUsage = Field(description="unused: a client constructed nowhere and configured nowhere. Not a dependency; left out of every count.")
    endpoint_scheme: str | None
    endpoint_host: str | None = Field(description="Lowercased. Userinfo, query and fragment are never stored.")
    endpoint_port: int | None
    endpoint_path: str | None
    resolution: EndpointResolution
    placeholder: str | None = Field(description="For an unresolved endpoint: the placeholder, environment variable or config key it waits on. Never guessed.")
    detail: dict[str, Any] = Field(description="{endpoint, block}: the full normalised endpoint and the mechanism's block (soap, database, http, ...), camelCase as in the artifact.")
    environment_bindings: list[dict[str, Any]] = Field(
        description="One logical endpoint's value per environment file, with the file and key it came from and that environment's own linuxVerdict and linuxReasons."
    )
    call_sites: list[dict[str, Any]] = Field(description="Step 5 1.3.0: where the dependency is invoked — each operation's call site.")
    construction_sites: list[dict[str, Any]] = Field(
        default_factory=list, description="Step 5 1.3.0: where the client is created, when that differs from where it is invoked."
    )
    credentials: list[dict[str, Any]] = Field(description="Kind and key path only, never a value.")
    auth_declared: AuthDeclared | None
    linux_verdict: LinuxVerdict = Field(description="The worst environment binding's verdict: a summary. Each binding carries its own.")
    linux_reasons: list[str]
    confidence: float
    confidence_reasons: list[str]


class ProjectOutboundOut(BaseModel):
    project_id: uuid.UUID
    project_path: str
    status: ProjectScanStatus
    skip_reason: str | None
    unused_count: int
    count_by_mechanism: dict[str, int] = Field(description="Used invocations only.")
    count_by_verdict: dict[str, int] = Field(description="Used invocations only.")
    invocations: list[OutboundInvocationOut] = Field(description="Incompatible first (the list someone will act on), then by mechanism and endpoint.")
    deploy_parameters: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Step 5 1.3.0: the project's Web Deploy SetParameters parameters — name, environment, kind and how it was linked. "
        "A value only for a path or a URL linked to a used endpoint; secrets and everything else are recorded as present.",
    )


class OutboundInventoryOut(BaseModel):
    repository_id: uuid.UUID
    scanner_version: str
    skip_source: str
    scanned_at: datetime.datetime | None
    invocation_count: int
    unused_count: int
    count_by_mechanism: dict[str, int] = Field(description="Used invocations only.")
    count_by_verdict: dict[str, int] = Field(description="Used invocations only.")
    auth_declared_scope: str
    projects: list[ProjectOutboundOut]


# ---------- inbound operations -> backend calls (step 5 1.3.0) ----------

BackendStatus = Literal["yes", "no", "unresolved", "not_assessed"]


class BackendHostOut(BaseModel):
    environment: str = Field(description="The environment this value is for: a configuration or SetParameters environment, or 'as found'.")
    host: str | None
    port: int | None
    path: str | None
    source_file: str | None
    deploy_parameter: str | None = Field(description="The SetParameters parameter that sets it, when one does.")
    host_project: str | None = Field(description="For a class library: the host project whose configuration this is.")
    linux_verdict: str | None


class BackendEndpointOut(BaseModel):
    shown: BackendHostOut = Field(description="The production environment's binding when the call has one, else the endpoint as found.")
    grouped_by: Literal["production_environment", "host"]
    others: list[BackendHostOut] = Field(description="Every other environment's value, for expanding.")


class BackendCallOut(BaseModel):
    invocation_id: str
    mechanism: str
    contract: str | None = Field(description="The SOAP or gRPC contract, when there is one.")
    operation: str | None = Field(description="The backend operation as step 5 records it; null for a mechanism without operations.")
    call_site: dict[str, Any] = Field(description="{filePath, lineStart, lineEnd}: where it is invoked.")
    depth: int = Field(description="0: in the entry point's own method; n: through n methods of the same class.")
    via: list[str] = Field(description="The methods walked, entry point first.")
    conditional: bool
    in_loop: bool
    context: list[str] = Field(description="The conditions and loops around the call, as written in code.")
    endpoint: BackendEndpointOut
    linux_verdict: str


class EntryPointBackendRowOut(BaseModel):
    number: int
    entry_point_id: str
    kind: str
    service: str = Field(description="The WCF contract, controller, gRPC service or handler type.")
    operation: str
    handler: dict[str, Any] = Field(description="{type, member, filePath, lineStart}.")
    status: BackendStatus = Field(
        description="yes: a backend call is reached. no: none, and no path left unfollowed. unresolved: none found, "
        "but a path through another class, an injected dependency or deeper calls was not followed. not_assessed: "
        "step 5 ran without step 4's entry points."
    )
    calls: list[BackendCallOut]
    unresolved: list[dict[str, Any]] = Field(description="{reason, callSite}: paths not followed — never guessed.")


class ApplicationBackendOut(BaseModel):
    project_id: uuid.UUID
    project_path: str
    rows: list[EntryPointBackendRowOut]


class EntryPointBackendOut(BaseModel):
    repository_id: uuid.UUID
    production_environment: str | None = Field(description="The engagement's setting the endpoint column is shown for.")
    applications: list[ApplicationBackendOut] = Field(description="One per project with request entry points, every operation listed.")
