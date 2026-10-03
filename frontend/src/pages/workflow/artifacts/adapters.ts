import type {
  AuthDeclared,
  EntryClass,
  EntryPoint,
  EntryPointKind,
  OutboundInvocation,
  Origin,
  ProjectEntryPoints,
  ProjectOutbound,
} from '../../../types/surface'

// Artifacts are camelCase files; the Surface panels render the API's
// snake_case rows. These adapters map one to the other so the same panel
// components draw both — written once, not twice.

type Json = Record<string, unknown>

const str = (value: unknown): string | null => (typeof value === 'string' ? value : null)
const num = (value: unknown, fallback = 0): number => (typeof value === 'number' ? value : fallback)
const list = <T = Json>(value: unknown): T[] => (Array.isArray(value) ? (value as T[]) : [])
const obj = (value: unknown): Json => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {})

/** Fields every entry-point record has; anything else that is an object is
 * the kind's own block (http, wcf, console, ...) — the API's `detail`. */
const ENTRY_POINT_BASE = new Set([
  'entryPointId', 'kind', 'origin', 'entryClass', 'handler', 'authDeclared', 'confidence', 'confidenceReasons', 'projectPath',
])

function entryPoint(record: Json): EntryPoint {
  const handler = obj(record.handler)
  const block = Object.entries(record).find(([key, value]) => !ENTRY_POINT_BASE.has(key) && value && typeof value === 'object' && !Array.isArray(value))
  return {
    id: str(record.entryPointId) ?? '',
    kind: str(record.kind) as EntryPointKind,
    origin: (str(record.origin) ?? 'application') as Origin,
    entry_class: (str(record.entryClass) ?? 'request') as EntryClass,
    handler_type: str(handler.type) ?? '',
    handler_member: str(handler.member),
    file_path: str(handler.filePath) ?? '',
    line_start: num(handler.lineStart),
    line_end: num(handler.lineEnd),
    detail: block ? (block[1] as Json) : {},
    confidence: num(record.confidence, 1),
    confidence_reasons: list<string>(record.confidenceReasons),
    auth_declared: (str(record.authDeclared) as AuthDeclared | null) ?? null,
  }
}

export function entryPointProjects(artifact: Json): ProjectEntryPoints[] {
  return list(artifact.projects).map((project) => {
    const summary = obj(project.summary)
    return {
      project_id: str(project.projectId) ?? '',
      project_path: str(project.projectPath) ?? '',
      status: (str(project.status) ?? 'SCANNED') as ProjectEntryPoints['status'],
      skip_reason: str(project.skipReason),
      request_entry_point_count: num(summary.requestEntryPointCount),
      lifecycle_hook_count: num(summary.lifecycleHookCount),
      count_by_kind: obj(summary.countByKind) as Record<string, number>,
      count_by_origin: obj(summary.countByOrigin) as Record<string, number>,
      count_by_verb: obj(summary.countByVerb) as Record<string, number>,
      no_declared_authentication_count: num(summary.noDeclaredAuthenticationCount),
      authorisation_not_assessed_count: num(summary.authorisationNotAssessedCount),
      global_authorisation: list<string>(summary.globalAuthorisation),
      conventional_routes: list<string>(summary.conventionalRoutes),
      entry_points: list(project.entryPoints).map(entryPoint),
    }
  })
}

const OUTBOUND_BLOCKS = ['soap', 'http', 'grpc', 'database', 'messaging', 'cache', 'secretStore', 'fileShare', 'smtp', 'ldap']

function invocation(record: Json): OutboundInvocation {
  const endpoint = obj(record.endpoint)
  const blockKey = OUTBOUND_BLOCKS.find((key) => record[key])
  const linux = obj(record.linuxCompatibility)
  return {
    id: str(record.invocationId) ?? '',
    mechanism: str(record.mechanism) as OutboundInvocation['mechanism'],
    usage: str(record.usage) === 'unused' ? 'unused' : 'used',
    endpoint_scheme: str(endpoint.scheme),
    endpoint_host: str(endpoint.host),
    endpoint_port: typeof endpoint.port === 'number' ? endpoint.port : null,
    endpoint_path: str(endpoint.path),
    resolution: (str(endpoint.resolution) ?? 'unresolved') as OutboundInvocation['resolution'],
    placeholder: str(endpoint.placeholder),
    detail: {
      endpoint: { fragments: [], source: null, ...endpoint } as unknown as OutboundInvocation['detail']['endpoint'],
      block: blockKey ? (obj(record[blockKey]) as OutboundInvocation['detail']['block']) : {},
    },
    environment_bindings: list(record.environmentBindings).map((b) => ({ linuxVerdict: null, linuxReasons: [], ...b })) as unknown as OutboundInvocation['environment_bindings'],
    call_sites: list(record.callSites) as OutboundInvocation['call_sites'],
    credentials: list(record.credentials) as OutboundInvocation['credentials'],
    auth_declared: (str(record.authDeclared) as AuthDeclared | null) ?? null,
    linux_verdict: (str(linux.verdict) ?? 'unknown') as OutboundInvocation['linux_verdict'],
    linux_reasons: list<string>(linux.reasons),
    confidence: num(record.confidence, 1),
    confidence_reasons: list<string>(record.confidenceReasons),
  }
}

export function outboundProjects(artifact: Json): ProjectOutbound[] {
  return list(artifact.projects).map((project) => {
    const summary = obj(project.summary)
    return {
      project_id: str(project.projectId) ?? '',
      project_path: str(project.projectPath) ?? '',
      status: (str(project.status) ?? 'SCANNED') as ProjectOutbound['status'],
      skip_reason: str(project.skipReason),
      unused_count: num(summary.unusedCount),
      count_by_mechanism: obj(summary.countByMechanism) as Record<string, number>,
      count_by_verdict: obj(summary.countByVerdict) as Record<string, number>,
      invocations: list(project.invocations).map(invocation),
    }
  })
}

export { list, num, obj, str }
export type { Json }
