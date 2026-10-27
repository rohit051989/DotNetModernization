// Lifecycle step 11's artifacts as GET /api/engagements/{eid}/estate returns
// them — 31-DEPENDENCY-AND-CONTEXT-MAP.md. Artifacts are camelCase files;
// annotations are the API's own snake_case rows.

export type ConversationStatus = 'not_started' | 'in_progress' | 'agreed' | 'resolved' | 'not_required'

export interface Coverage {
  repositoriesInEngagement: number
  repositoriesIncluded: number
  repositoriesPending: number
  coverageRatio: number
  partialEstate: boolean
}

export interface EstateSource {
  repositoryId: string
  repositorySlug: string
  included: boolean
  stepExecutions: Record<string, string>
}

interface ArtifactHeader {
  artifactType: string
  artifactVersion: string
  engagementId: string
  coverage: Coverage
  sources: EstateSource[]
}

export interface InternalTarget {
  repositoryId: string
  repositorySlug: string
  projectId: string
  projectPath: string
  entryPointId: string
  served: string
  sameRepository: boolean
}

export interface RegisterService {
  path: string
  contract: string | null
  ports: number[]
  schemes: string[]
  mechanisms: string[]
  bindings: string[]
  callingRepositories: string[]
  callingProjects: string[]
  worstVerdict: string | null
  /** Endpoint-register 1.5.0: platform matrix entries a probe contradicts — under review, counted apart. */
  underReview?: string[]
  requiresBackendChange: boolean
  backendChangeOwner?: 'this_migration' | 'another_team' | null
  internal: boolean
  internalTargets: InternalTarget[]
  matchedBy: string[]
}

export interface RegisterHost {
  host: string
  /** 'production_environment': keyed by the production environment's host;
   * 'host': no production binding, keyed by the host as found. */
  groupedBy: 'production_environment' | 'host'
  productionEnvironment: string | null
  /** Said when the row is not (wholly) keyed by the production host. */
  groupingNote: string | null
  otherHosts: { host: string; environments: string[] }[]
  /** Endpoint-register 1.2.0: annotated hosts carried to this row because the
   * production grouping moved their calls here. The annotations themselves are untouched. */
  annotationCarriedFrom?: string[]
  loopback: boolean
  classification: 'internal' | 'external'
  services: RegisterService[]
  callingRepositoryCount: number
  callingRepositories: string[]
  callingProjectCount: number
  callingProjects: string[]
  mechanisms: string[]
  bindings: string[]
  ports: number[]
  worstVerdict: string | null
  verdictByEnvironment: Record<string, string>
  /** Endpoint-register 1.5.0: platform matrix entries a probe contradicts — never shown as their verdict. */
  underReview?: string[]
  requiresBackendChange: boolean
  /** Endpoint-register 1.3.0: who must change — 'this_migration' (a service
   * inside this migration) or 'another_team'. Null when no change is needed. */
  backendChangeOwner?: 'this_migration' | 'another_team' | null
  backendChangeReasons: string[]
  invocationCount: number
}

export interface UnresolvedEndpoint {
  repositorySlug: string
  projectPath: string
  mechanism: string
  contract: string | null
  placeholder: string | null
  resolution: string | null
  invocationId: string
}

export interface EndpointRegisterArtifact extends ArtifactHeader {
  summary: {
    hosts: number
    requiresBackendChange: number
    internal: number
    external: number
    unresolved: number
    unusedExcluded: number
    noLongerCalled: number
    groupedByProductionHost: number
    /** Endpoint-register 1.5.0: hosts with a matrix entry under review. */
    underReview?: number
  }
  productionEnvironment: string | null
  /** Annotated host -> serving repository slug, as the run used them. */
  servedByAnnotations: Record<string, string>
  carriedAnnotations?: { fromHost: string; toHost: string }[]
  hosts: RegisterHost[]
  unresolved: UnresolvedEndpoint[]
  noLongerCalled: string[]
}

export interface PackageEstateRow {
  packageId: string
  repositoryCount: number
  repositories: string[]
  projectCount: number
  projects: string[]
  versionsInUse: Record<string, number>
  estateDrift: boolean
  crossRepositoryDrift: boolean
  recommendedVersion: string | null
  outcomes: Record<string, number>
  breakingMembers: { type: string | null; member: string | null; change: string | null }[]
  flags: { deprecated: boolean; vulnerable: boolean; notInClientFeed: boolean }
  feedSources: string[]
}

export interface PackageEstateArtifact extends ArtifactHeader {
  summary: { packages: number; estateDrift: number; crossRepositoryDrift: number }
  packages: PackageEstateRow[]
}

export interface ProjectRef {
  projectId: string
  repositorySlug: string
  projectPath: string
}

export interface DependencyGraphArtifact extends ArtifactHeader {
  summary: { projects: number; edges: number; crossRepositoryEdges: number; sharedLibraries: number; cycles: number; originReconciliations: number }
  nodes: ProjectRef[]
  edges: { from: ProjectRef; to: ProjectRef; kind: string; crossRepository: boolean; via: string | null; clientFeed: boolean }[]
  sharedLibraries: { project: ProjectRef; consumerRepositoryCount: number; consumerProjectCount: number; consumers: ProjectRef[] }[]
  cycles: { cycleId: string; members: ProjectRef[]; crossRepository: boolean }[]
  originReconciliations: { entryPointId: string; originalOrigin: string; reconciledOrigin: string; reason: string }[]
}

export interface ContextSystem {
  id: string
  name: string
  kind: 'repository' | 'external'
  loopback?: boolean
  requiresBackendChange?: boolean
}

export interface ContextMapArtifact extends ArtifactHeader {
  format: 'structurizr-dsl'
  dsl: string
  systems: ContextSystem[]
  relationships: { from: string; to: string; label: string }[]
}

export type InternalCaller = 'internal_caller_found' | 'no_internal_caller_found'

export interface CallSiteRef {
  filePath: string | null
  lineStart: number | null
}

export interface IntegrationEdge {
  edgeId: string
  invocationId: string
  /** Every invocation claiming this call site (a code and a config endpoint of one client). */
  invocationIds: string[]
  mechanism: string
  operation: string
  callerRepositoryId: string
  callerRepositorySlug: string
  callerProjectId: string
  callerProjectPath: string
  callSite: CallSiteRef
  calleeRepositoryId: string
  calleeRepositorySlug: string
  calleeProjectId: string
  calleeProjectPath: string
  entryPointId: string
  entryPointKind: string
  served: string
  matchMethod: string
  confidence: number
  sameRepository: boolean
}

export interface IntegrationEntryPoint {
  entryPointId: string
  kind: string
  operation: string
  matchable: boolean
  repositoryId: string
  repositorySlug: string
  projectId: string
  projectPath: string
  internalCaller: InternalCaller
  callerCount: number
  crossRepositoryCallerCount: number
}

export interface IntegrationApplication {
  repositorySlug: string
  projectPath: string
  repositoryId: string
  projectId: string
  calls: {
    operation: string
    mechanism: string
    invocationId: string
    callSite: CallSiteRef
    targets: Pick<IntegrationEdge, 'entryPointId' | 'served' | 'calleeRepositorySlug' | 'calleeProjectPath' | 'matchMethod' | 'confidence' | 'sameRepository'>[]
    unmatchedReason: string | null
  }[]
  exposes: (IntegrationEntryPoint & {
    callers: Pick<IntegrationEdge, 'callerRepositorySlug' | 'callerProjectPath' | 'callSite' | 'operation' | 'matchMethod' | 'confidence' | 'sameRepository'>[]
  })[]
}

export interface IntegrationMapArtifact extends ArtifactHeader {
  summary: {
    edges: number
    crossRepositoryEdges: number
    sameRepositoryEdges: number
    operationsUnmatched: number
    operationsUnresolved: number
    entryPoints: number
    entryPointsInternalCallerFound: number
    entryPointsNoInternalCallerFound: number
  }
  edges: IntegrationEdge[]
  unmatched: (Omit<IntegrationEdge, 'edgeId' | 'calleeRepositoryId' | 'calleeRepositorySlug' | 'calleeProjectId' | 'calleeProjectPath' | 'entryPointId' | 'entryPointKind' | 'served' | 'matchMethod' | 'confidence' | 'sameRepository'> & {
    reason: string
    resolution: string | null
  })[]
  entryPoints: IntegrationEntryPoint[]
  applications: IntegrationApplication[]
}

export interface EndpointAnnotation {
  host: string
  owning_team: string | null
  contact: string | null
  conversation_status: ConversationStatus
  target_date: string | null
  notes: string | null
  /** Slug of the engagement repository that serves this host: HTTP calls to
   * it are matched against that repository's routes on the next run. */
  served_by_repository: string | null
  updated_by: string | null
  updated_at: string
}

export type EndpointAnnotationInput = Omit<EndpointAnnotation, 'host' | 'updated_at'>

export interface EstateSettings {
  production_environment: string | null
  /** The WCF client package version the engagement targets; null: the matrices' version for the target framework. */
  target_wcf_client_version: string | null
  target_wcf_client_version_effective: string | null
  deploy_parameter_globs: string[]
  deploy_parameter_globs_default: boolean
  environments: string[]
  repositories: string[]
  /** The engagement's version: sent back as If-Match when changing the settings. */
  version?: number
}

/** Part K: will each SOAP backend's calls still work on the target .NET? */
export type RuntimeVerdict = 'supported' | 'supported_with_caveat' | 'unsupported' | 'unknown' | 'not_assessed' | 'under_review'

/** A verdict resting on a matrix entry a probe contradicts reads this until a reviewer revises the entry. */
export const UNDER_REVIEW = 'under_review'
export const UNDER_REVIEW_LABEL = 'contradicted by probe — under review'

/** we: the calling application's side, in this migration; backend_owner: the service's side;
 *  we_or_backend_owner: either, not yet known which (Windows credentials: Kerberos on our side, or another credential on theirs). */
export type ChangeOwner = 'we' | 'backend_owner' | 'we_or_backend_owner'

export interface SoapChange {
  who: ChangeOwner
  change: string
  note: string | null
  /** The verdict it follows from: a contradicted entry withdraws its own changes only. */
  source?: 'runtime' | 'platform' | 'configuration'
}

/** What a probe's evidence covers: the WCF client package and .NET runtime it ran against. */
export interface ProbeCovers {
  wcfClient: string
  runtime: string | null
  os: string
}

/** A probe recorded on a matrix entry (29-ENTRY-POINT-AND-OUTBOUND-INVENTORIES.md C11): evidence, not a verdict. */
export interface MatrixProbe {
  probedOn: string
  outcome: 'passed' | 'failed' | 'error' | 'not_probed'
  scenario?: string
  where?: string
  summary?: string
  /** not_probed: why, e.g. needs Kerberos. */
  reason?: string
  service?: string
  address?: string
  client?: { image: string; os: string; framework: string; wcfClient: string; cryptographyXml: string | null }
  covers?: ProbeCovers
  /** 'platform-sample', or the client engagement whose environment it ran in (29 C10, the evidence boundary). */
  source?: 'platform-sample' | { engagement: string }
  /** A client engagement's evidence, kept with that engagement: the entry holds only this reference. */
  evidenceRef?: { engagement: string; id: string }
  /** The exception's type alone: what a client engagement's probe keeps of a failure. */
  errorType?: string
  /** not_probed: what it would take, and who. */
  openItem?: string
  evidence?: string
  sha256?: string
  controls?: { where: string; outcome: string; summary: string; os: string; evidence: string; sha256: string }[]
  /** A Linux failure that passed on Windows with the same client is the platform's. */
  attribution?: 'platform' | 'undetermined'
}

/** What is read live from the matrix entry a verdict rests on. */
interface MatrixEntryLive {
  matrixEntry: string | null
  /** Has a person confirmed the matrix entry? null when no entry matched. */
  /** In plain words: the matrix entry that decided the verdict and its evidence, or why it is unknown. */
  why?: string | null
  matrixConfirmed: boolean | null
  confirmedBy: string | null
  confirmedOn: string | null
  sources: string[]
  probes: MatrixProbe[]
  /** Where the entry's latest probes disagree with its verdict. */
  probeContradictions: string[]
  /** The newest WCF client and the runtimes the entry's probes ran against; null when none has run. */
  evidenceCovers: { wcfClient: string; runtimes: string[]; probes: number } | null
  /** The evidence covers an older WCF client than the engagement targets. */
  evidencePredatesTarget: boolean
  /** Set when the verdict reads under_review: the entry's own verdict, for the reviewer. */
  unrevisedVerdict?: string
  /** 'shipped': the platform's matrix; 'engagement': this client's own confirmation on its own evidence (29 C10). */
  confirmationSource: 'shipped' | 'engagement' | null
  /** This engagement's evidence for the confirmation or a probe is gone or no longer matches its hash. */
  evidenceMissing: boolean
}

export interface SoapEnvironment {
  environment: string
  address: string | null
  sourceFile: string | null
  deployParameter: string | null
  binding: string | null
  securityMode: string | null
  credentialType: string | null
  /** declared, binding_default or unresolved. */
  securitySource: string | null
  runtime: MatrixEntryLive & { verdict: RuntimeVerdict; reasons: string[] }
  platform: MatrixEntryLive & { verdict: string | null; reasons: string[] }
  changes: SoapChange[]
  /** The contradictions that put a verdict under review; empty when none. */
  underReview?: string[]
}

export interface SoapCaller {
  invocationId: string
  application: string
  projectPath: string
  contract: string | null
  endpointName: string | null
  clientType: string | null
  operations: string[]
  environments: SoapEnvironment[]
}

export interface SoapBackendHost {
  host: string
  servedBy: string[]
  backendOwner: 'this_migration' | 'another_team'
  owningTeam: string | null
  callingApplications: string[]
  worstRuntime: RuntimeVerdict
  worstPlatform: string
  changeOwners: ChangeOwner[]
  matrixEntries: string[]
  /** Environments with a verdict under review, counted apart from every worst verdict. */
  underReview?: number
  callers: SoapCaller[]
}

export interface MatrixSource {
  id: string
  title: string
  version: string
  url: string
  note?: string
  commit?: string
  committedOn?: string
  retrievedOn?: string
}

export interface SoapCompatibilityArtifact {
  artifactType: 'soap-backend-compatibility'
  coverage: Coverage
  summary: { hosts: number; runtimeUnsupported: number; platformIncompatible: number; backendOwnerMustChange: number; underReview: number }
  hosts: SoapBackendHost[]
  matrix: {
    version: string | null
    runVersion: string | null
    platformVersion: string | null
    /** The run used an older matrix than the newest: rescan. */
    newerMatrices: Record<string, { run: string | null; newest: string }>
    targetWcfClientVersion: string | null
    targetWcfClientVersionSource: 'engagement' | 'matrix'
    sources: MatrixSource[]
    platformSources: MatrixSource[]
    entriesUsed: string[]
    unconfirmedEntries: string[]
    contradictedEntries: string[]
    /** Entries whose evidence covers an older WCF client than the targeted one: re-probe. */
    evidencePredatesTarget: string[]
    /** Entries no probe has run against (not probed counts). */
    unprobedEntries: string[]
    /** Entries whose engagement evidence is gone or changed: the report is not ready. */
    evidenceMissingEntries: string[]
    entries: Record<string, {
      kind: 'support' | 'platform'
      verdict: string
      basis: string
      probes: MatrixProbe[]
      probeContradictions: string[]
      evidenceCovers: { wcfClient: string; runtimes: string[]; probes: number } | null
      evidencePredatesTarget: boolean
      revision: { by: string; on: string; decision: string } | null
    }>
    /** Every entry confirmed, none contradicted, none with evidence older than the targeted WCF client, newest matrices. */
    readyForClient: boolean
  }
}

export interface EstateView {
  engagement_id: string
  run: { step_execution_id: string; job_execution_id: string; completed_at: string | null; exit_message: string | null } | null
  artifacts: {
    'endpoint-register'?: EndpointRegisterArtifact
    'package-estate'?: PackageEstateArtifact
    'dependency-graph'?: DependencyGraphArtifact
    'context-map'?: ContextMapArtifact
    'integration-map'?: IntegrationMapArtifact
    'soap-backend-compatibility'?: SoapCompatibilityArtifact
  }
  annotations: EndpointAnnotation[]
  settings: EstateSettings
}

/** What "confirmed" means wherever it is shown (the column under each verdict, the CSV's *_confirmed columns). */
export const CONFIRMED_HELP =
  'Confirmed: a named person reviewed the evidence of the matrix entry behind this verdict and accepted it. ' +
  'Unconfirmed: nobody has reviewed that entry yet, so the verdict is a draft. Confirming is a person\'s decision, never automatic.'
