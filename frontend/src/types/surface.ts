// The repository Surface section — 29-STEPS-004-005-INVENTORIES.md Part D.
// Inbound: step 4's entry points (GET /api/repositories/{id}/entry-points).

export type EntryPointKind =
  | 'http_controller_action'
  | 'http_minimal_api'
  | 'wcf_operation'
  | 'asmx_web_method'
  | 'grpc_service_method'
  | 'signalr_hub_method'
  | 'message_consumer'
  | 'hosted_service'
  | 'scheduled_job'
  | 'console_main'
  | 'webforms_page'
  | 'razor_page'
  | 'windows_service'
  | 'http_handler'
  | 'global_asax'
  | 'owin_startup'
  | 'blazor_component'
  | 'azure_function'
  | 'desktop_app'

/** Authentication as declared in source and config. Gateway, proxy and
 * header-based authentication are invisible to static analysis, so
 * none_declared is a review prompt, not a finding. */
export type AuthDeclared = 'declared' | 'none_declared' | 'not_assessed'

export interface HttpParameter {
  name: string
  type: string | null
  source: 'route' | 'query' | 'body' | 'header' | 'form' | 'inferred'
  inferredSource: 'route' | 'query' | 'body' | 'form' | null
}

export interface HttpDetail {
  verb: string
  routeTemplate: string | null
  routing: 'attribute' | 'conventional' | 'minimal_api' | 'razor_page'
  parameters: HttpParameter[]
  returnType: string | null
  authorisation: string | null
  controller: string | null
  action: string | null
  mappedTemplate: string | null
  groupPrefix: { resolution: 'resolved' | 'unresolved'; prefix: string | null; expression: string | null } | null
  handlerForm: 'lambda' | 'method_group' | null
  pageFile: string | null
  pageHandler: string | null
}

/** One endpoint serving a WCF contract, from config or code. */
export interface WcfEndpoint {
  hostKind: 'svc' | 'service_host' | 'corewcf'
  hostedAt: string
  binding: string
  securityMode: string | null
  clientCredentialType: string | null
  securitySource: 'declared' | 'binding_default' | 'unresolved'
  anonymous: boolean | null
  address: string | null
  source: 'config' | 'code'
  declaredAt: string
  condition: string | null
}

/** The kind-specific block, camelCase as in the artifact. Only the http
 * block is typed field by field; the others are summarised generically. */
export type EntryPointDetail = HttpDetail | Record<string, unknown>

/** framework: a registered framework or package type — migrates through its
 * package's own path. lifecycle: bootstrap and wiring, not a place external
 * work enters; never counted, snapshotted or tested as surface. */
export type Origin = 'application' | 'framework'
export type EntryClass = 'request' | 'lifecycle'

export interface EntryPoint {
  id: string
  kind: EntryPointKind
  origin: Origin
  entry_class: EntryClass
  handler_type: string
  handler_member: string | null
  file_path: string
  line_start: number
  line_end: number
  detail: EntryPointDetail
  confidence: number
  confidence_reasons: string[]
  auth_declared: AuthDeclared | null
}

export interface ProjectEntryPoints {
  project_id: string
  project_path: string
  status: 'SCANNED' | 'SKIPPED' | 'FAILED'
  skip_reason: string | null
  request_entry_point_count: number
  lifecycle_hook_count: number
  count_by_kind: Record<string, number>
  count_by_origin: Record<string, number>
  count_by_verb: Record<string, number>
  no_declared_authentication_count: number
  authorisation_not_assessed_count: number
  global_authorisation: string[]
  conventional_routes: string[]
  entry_points: EntryPoint[]
}

export interface EntryPointInventory {
  repository_id: string
  scanner_version: string
  skip_source: string
  scanned_at: string | null
  entry_point_count: number
  request_entry_point_count: number
  lifecycle_hook_count: number
  count_by_kind: Record<string, number>
  count_by_origin: Record<string, number>
  count_by_verb: Record<string, number>
  no_declared_authentication_count: number
  authorisation_not_assessed_count: number
  auth_declared_scope: string
  capabilities_manifest_version: string | null
  capability_kinds: string[]
  projects: ProjectEntryPoints[]
}

export interface CapabilityKind {
  kind: EntryPointKind
  label: string
  detects: string
  identified_by: string
  auth_declared: string
  added_in: string
  entry_class: string
  found_in_estate: number
  repositories_with_kind: number
}

export interface EntryPointCapabilities {
  manifest_version: string
  scanner_version: string
  description: string
  auth_declared_scope: string
  kinds: CapabilityKind[]
  not_covered: { pattern: string; marker: string; note: string }[]
  repositories_scanned: number
  repositories_on_this_manifest: number
}
