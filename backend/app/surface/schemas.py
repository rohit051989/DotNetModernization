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
    call_sites: list[dict[str, Any]]
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
