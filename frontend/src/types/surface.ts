// The repository Surface section — 29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part D.
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

// ---------- outbound: step 5 (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md Part C) ----------

export type OutboundMechanism =
  | 'http_client'
  | 'soap_client'
  | 'grpc_client'
  | 'database'
  | 'message_producer'
  | 'message_consumer'
  | 'cache'
  | 'secret_store'
  | 'file_share'
  | 'smtp'
  | 'ldap'

export type LinuxVerdict = 'incompatible' | 'requires_change' | 'unknown' | 'compatible'
export type EndpointResolution = 'resolved' | 'partial' | 'unresolved'

export interface OutboundEndpoint {
  scheme: string | null
  host: string | null
  port: number | null
  path: string | null
  resolution: EndpointResolution
  placeholder: string | null
  fragments: string[]
  source: { sourceFile: string; keyPath: string } | null
}

export interface EnvironmentBinding {
  environment: string
  sourceFile: string
  keyPath: string
  scheme: string | null
  host: string | null
  port: number | null
  path: string | null
  resolution: EndpointResolution
  placeholder: string | null
  authentication: string | null
  /** This environment's own verdict; the invocation's is the worst of these. */
  linuxVerdict: LinuxVerdict | null
  linuxReasons: string[]
}

export interface OutboundCallSite {
  filePath: string
  lineStart: number
  lineEnd: number
}

/** Kind and key path only; a value is never stored. */
export interface OutboundCredential {
  kind: 'certificate' | 'password' | 'api_key' | 'token' | 'client_secret' | 'windows'
  keyPath: string | null
  sourceFile: string | null
  declaredAt: string | null
}

/** The mechanism's block, camelCase as in the artifact: soap, http,
 * database, messaging, ... Only the fields the panel shows are typed. */
export interface OutboundBlock {
  contract?: string | null
  binding?: string
  securityMode?: string | null
  clientCredentialType?: string | null
  securitySource?: string
  bindingSource?: string
  clientSource?: string
  clientType?: string
  condition?: string | null
  via?: string | null
  library?: string
  clientName?: string | null
  typedClient?: string | null
  name?: string | null
  provider?: string | null
  authentication?: string
  localDb?: boolean
  transport?: string
  topics?: string[]
  authenticationSource?: string | null
  share?: string
  api?: string
  usesDefaultCredentials?: boolean
}

export interface OutboundInvocation {
  id: string
  mechanism: OutboundMechanism
  /** unused: constructed nowhere and configured nowhere — not a dependency, left out of every count. */
  usage: 'used' | 'unused'
  endpoint_scheme: string | null
  endpoint_host: string | null
  endpoint_port: number | null
  endpoint_path: string | null
  resolution: EndpointResolution
  placeholder: string | null
  detail: { endpoint: OutboundEndpoint; block: OutboundBlock }
  environment_bindings: EnvironmentBinding[]
  /** Step 5 1.3.0: where the dependency is invoked — each operation's call site. */
  call_sites: OutboundCallSite[]
  /** Step 5 1.3.0: where the client is created, when that differs. */
  construction_sites?: OutboundCallSite[]
  credentials: OutboundCredential[]
  auth_declared: AuthDeclared | null
  linux_verdict: LinuxVerdict
  linux_reasons: string[]
  confidence: number
  confidence_reasons: string[]
}

export interface ProjectOutbound {
  project_id: string
  project_path: string
  status: 'SCANNED' | 'SKIPPED' | 'FAILED'
  skip_reason: string | null
  unused_count: number
  count_by_mechanism: Record<string, number>
  count_by_verdict: Record<string, number>
  invocations: OutboundInvocation[]
  /** Step 5 1.3.0: Web Deploy SetParameters parameters; a value only for a path or a used endpoint URL. */
  deploy_parameters?: DeployParameter[]
}

export interface DeployParameter {
  projectPath: string | null
  sourceFile: string
  environment: string
  name: string
  kind: 'url' | 'path' | 'connection_string' | 'sensitive' | 'other'
  line: number
  value: string | null
  linkedKind: string | null
  linkedName: string | null
  linkMethod: 'parameters_xml' | 'name_and_path' | null
  linkConfidence: number | null
  linkNote: string | null
}

export interface OutboundInventory {
  repository_id: string
  scanner_version: string
  skip_source: string
  scanned_at: string | null
  invocation_count: number
  unused_count: number
  count_by_mechanism: Record<string, number>
  count_by_verdict: Record<string, number>
  auth_declared_scope: string
  projects: ProjectOutbound[]
}

// ---------- inbound operations -> backend calls (step 5 1.3.0) ----------

export type BackendStatus = 'yes' | 'no' | 'unresolved' | 'not_assessed'

export interface BackendHost {
  environment: string
  host: string | null
  port: number | null
  path: string | null
  source_file: string | null
  deploy_parameter: string | null
  host_project: string | null
  linux_verdict: string | null
}

export interface BackendCall {
  invocation_id: string
  mechanism: string
  contract: string | null
  operation: string | null
  call_site: OutboundCallSite
  depth: number
  via: string[]
  conditional: boolean
  in_loop: boolean
  context: string[]
  endpoint: { shown: BackendHost; grouped_by: 'production_environment' | 'host'; others: BackendHost[] }
  linux_verdict: string
}

export interface EntryPointBackendRow {
  number: number
  entry_point_id: string
  kind: string
  service: string
  operation: string
  handler: { type: string; member: string | null; filePath: string; lineStart: number }
  status: BackendStatus
  calls: BackendCall[]
  unresolved: { reason: string; callSite: OutboundCallSite }[]
}

export interface EntryPointBackend {
  repository_id: string
  production_environment: string | null
  applications: { project_id: string; project_path: string; rows: EntryPointBackendRow[] }[]
}

/** One verdict as the last scan recorded it, with what is live in the WCF client matrix. */
export interface SoapVerdictLive {
  /** 'under_review' when a probe contradicts the entry: never its unrevised verdict. */
  verdict: string | null
  unrevisedVerdict: string | null
  matrixEntry: string | null
  /** Null when no matrix entry matched. */
  /** In plain words: the matrix entry that decided the verdict and its evidence, or why it is unknown. */
  why?: string | null
  matrixConfirmed: boolean | null
  confirmedBy: string | null
  confirmedOn: string | null
  /** The recorded decision that authorised the confirmation. */
  decision: string | null
  confirmationSource: 'shipped' | 'engagement' | null
  /** This engagement's evidence for the confirmation or a probe is gone or changed. */
  evidenceMissing: boolean
  probeContradictions: string[]
  evidenceCovers: { wcfClient: string; runtimes: string[]; probes: number } | null
  evidencePredatesTarget: boolean
}

export interface RepositorySoapEnvironment {
  environment: string
  address: string | null
  sourceFile: string | null
  binding: string | null
  securityMode: string | null
  credentialType: string | null
  securitySource: string | null
  runtime: SoapVerdictLive
  platform: SoapVerdictLive
}

export interface RepositorySoapCall {
  invocationId: string
  projectPath: string
  contract: string | null
  clientType: string | null
  endpoint: string
  environments: RepositorySoapEnvironment[]
  /** The estate report's row for this call; null when the newest estate run does not have it. */
  estateHost: string | null
}

export interface RepositorySoap {
  repository_id: string
  engagement_id: string
  scanned_at: string | null
  estate_run_at: string | null
  /** The estate report has not been rerun since this repository's last scan. */
  estate_stale: boolean
  estate_note: string | null
  target_wcf_client_version: string | null
  unused_count: number
  calls: RepositorySoapCall[]
}
