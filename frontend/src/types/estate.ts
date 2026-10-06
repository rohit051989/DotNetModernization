// Lifecycle step 11's artifacts as GET /api/engagements/{eid}/estate returns
// them — 31-STEP-011-ESTATE-DEPENDENCY-MAP.md. Artifacts are camelCase files;
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
  deploy_parameter_globs: string[]
  deploy_parameter_globs_default: boolean
  environments: string[]
  repositories: string[]
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
  }
  annotations: EndpointAnnotation[]
  settings: EstateSettings
}
