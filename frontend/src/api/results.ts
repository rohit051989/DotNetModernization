import { api } from './client'
import type { Page, PageLoader } from '../components/PagedList'
import type { ContextMapArtifact, SoapBackendHost } from '../types/estate'
import type { BackendSummary, EntryPointSummary, ImpactSummary, OutboundSummary, RepositoryResults, SoapSummary, TestsSummary } from '../types/results'

/** A paged list's loader: `path` with the filter box's text, the offset and limit, and the list's own parameters.
 * Untyped (never) unless named: the list that uses it says what its items are. */
export function pages<T = never>(path: string, params: Record<string, string | number | boolean | null | undefined> = {}): PageLoader<T> {
  return (q, offset, limit) => {
    const query = new URLSearchParams({ q, offset: String(offset), limit: String(limit) })
    for (const [key, value] of Object.entries(params)) if (value !== null && value !== undefined) query.set(key, String(value))
    return api.get<Page<T>>(`${path}?${query}`)
  }
}

const repo = (repositoryId: string) => `/api/repositories/${encodeURIComponent(repositoryId)}`
const result = (artifactId: string) => `/api/results/${encodeURIComponent(artifactId)}`
const estate = (engagementId: string) => `/api/engagements/${encodeURIComponent(engagementId)}/estate`

/** The newest stored result of each kind the repository page reads, without its lists (app.results). */
export function getRepositoryResults(repositoryId: string) {
  return api.get<RepositoryResults>(`${repo(repositoryId)}/results`)
}

// ---------- stored results: fingerprint, dependencies, work list ----------

export function getFingerprintOverview(artifactId: string) {
  return api.get<{ status_counts: Record<string, number>; categories: { category: string; signals: number; distinct: number }[] }>(
    `${result(artifactId)}/fingerprint`,
  )
}
export const fingerprintSignals = (artifactId: string, category: string) => pages(`${result(artifactId)}/fingerprint/signals`, { category })

export function listDependencyFeeds(artifactId: string) {
  return api.get<Record<string, unknown>[]>(`${result(artifactId)}/dependencies/feeds`)
}
export const dependencyPackages = (artifactId: string, showCurrent: boolean) =>
  pages(`${result(artifactId)}/dependencies/packages`, { show_current: showCurrent })
/** One version's projects; version null: every version's. */
export const dependencyUses = (artifactId: string, packageId: string, version: string | null) =>
  pages(`${result(artifactId)}/dependencies/uses`, { package_id: packageId, version })
export function getDependencyProject(artifactId: string, path: string) {
  return api.get<Record<string, unknown> | null>(`${result(artifactId)}/dependencies/project?${new URLSearchParams({ path })}`)
}

export function getWorkItemTotals(artifactId: string) {
  return api.get<{ occurrence_rows: number; possible_rows: number }>(`${result(artifactId)}/work-items/totals`)
}
export const workItems = (artifactId: string, showAll: boolean) => pages(`${result(artifactId)}/work-items`, { show_all: showAll })
export const workItemFiles = (artifactId: string, projectId: string, itemId: string, byFile: boolean) =>
  pages(`${result(artifactId)}/work-items/files`, { project_id: projectId, item_id: itemId, by_file: byFile })

// ---------- Surface ----------

export const getEntryPointSummary = (repositoryId: string) => api.get<EntryPointSummary>(`${repo(repositoryId)}/entry-points/summary`)
export const entryPointProjects = (repositoryId: string, withRequests: boolean) =>
  pages(`${repo(repositoryId)}/entry-points/projects`, { with_requests: withRequests })
export const entryPoints = (repositoryId: string, projectId: string, entryClass: string, kind: string) =>
  pages(`${repo(repositoryId)}/entry-points/list`, { project_id: projectId, entry_class: entryClass, kind })

export const getOutboundSummary = (repositoryId: string) => api.get<OutboundSummary>(`${repo(repositoryId)}/outbound-invocations/summary`)
export const outboundProjects = (repositoryId: string, withInvocations: boolean) =>
  pages(`${repo(repositoryId)}/outbound-invocations/projects`, { with_invocations: withInvocations })
export const outboundInvocations = (repositoryId: string, projectId: string, mechanism: string) =>
  pages(`${repo(repositoryId)}/outbound-invocations/list`, { project_id: projectId, mechanism })

export const getBackendSummary = (repositoryId: string) => api.get<BackendSummary>(`${repo(repositoryId)}/entry-point-backend/summary`)
export const backendApplications = (repositoryId: string) => pages(`${repo(repositoryId)}/entry-point-backend/applications`)
export const backendOperations = (repositoryId: string, projectId: string) =>
  pages(`${repo(repositoryId)}/entry-point-backend/operations`, { project_id: projectId })

export const getSoapSummary = (repositoryId: string) => api.get<SoapSummary>(`${repo(repositoryId)}/soap-compatibility/summary`)
export const soapCalls = (repositoryId: string) => pages(`${repo(repositoryId)}/soap-compatibility/calls`)

// ---------- Projects (structure) ----------

export const structureWarnings = (repositoryId: string) => pages(`${repo(repositoryId)}/structure/warnings`)
export const solutionsPage = (repositoryId: string) => pages(`${repo(repositoryId)}/solutions/page`)
export const solutionMembers = (repositoryId: string, solutionId: string) =>
  pages(`${repo(repositoryId)}/solutions/${encodeURIComponent(solutionId)}/members`)
export const projectsPage = (repositoryId: string, standalone?: boolean) => pages(`${repo(repositoryId)}/projects/page`, { standalone })
export const artifactsPage = (repositoryId: string) => pages(`${repo(repositoryId)}/artifacts/page`)

// ---------- Impact ----------

export const getImpactSummary = (repositoryId: string) => api.get<ImpactSummary>(`${repo(repositoryId)}/impact/summary`)
export const impactFiles = (repositoryId: string, hotspots: boolean) => pages(`${repo(repositoryId)}/impact/files`, { hotspots })
export const impactWorkItems = (repositoryId: string) => pages(`${repo(repositoryId)}/impact/work-items`)
export const impactRuleConflicts = (repositoryId: string) => pages(`${repo(repositoryId)}/impact/rule-conflicts`)
export const impactRuleConflictInstances = (repositoryId: string, ruleKey: string) =>
  pages(`${repo(repositoryId)}/impact/rule-conflicts/instances`, { rule_key: ruleKey })
export const impactWorkItemConflicts = (repositoryId: string) => pages(`${repo(repositoryId)}/impact/work-item-conflicts`)

// ---------- Tests ----------

export const getTestsSummary = (repositoryId: string) => api.get<TestsSummary>(`${repo(repositoryId)}/tests/summary`)
export const testProjects = (repositoryId: string) => pages(`${repo(repositoryId)}/tests/test-projects`)
export const testClasses = (repositoryId: string) => pages(`${repo(repositoryId)}/tests/test-classes`)
export const testCoverageProjects = (repositoryId: string) => pages(`${repo(repositoryId)}/tests/projects`)
export const testSourceFiles = (repositoryId: string, bucket: string | null) => pages(`${repo(repositoryId)}/tests/source-files`, { bucket })

// ---------- Estate ----------

export const registerHosts = (engagementId: string) => pages(`${estate(engagementId)}/register/hosts`)
export const registerUnresolved = (engagementId: string) => pages(`${estate(engagementId)}/register/unresolved`)
export const integrationApplications = (engagementId: string, exposed: 'called' | 'all') =>
  pages(`${estate(engagementId)}/integration/applications`, { exposed })
export const integrationList = (engagementId: string, repositorySlug: string, projectPath: string, which: 'calls' | 'called' | 'uncalled') =>
  pages(`${estate(engagementId)}/integration/lists`, { repository_slug: repositorySlug, project_path: projectPath, which })
export const estatePackages = (engagementId: string, driftOnly: boolean) => pages(`${estate(engagementId)}/packages`, { drift_only: driftOnly })
export const estateDependencies = (engagementId: string, which: 'shared-libraries' | 'cycles' | 'cross-repository' | 'origin-reconciliations') =>
  pages(`${estate(engagementId)}/dependencies/${which}`)
export function getContextMap(engagementId: string) {
  return api.get<ContextMapArtifact>(`${estate(engagementId)}/context-map`)
}
export const soapHosts = (engagementId: string) => pages(`${estate(engagementId)}/soap/hosts`)
export const soapCallers = (engagementId: string, host: string) => pages(`${estate(engagementId)}/soap/callers`, { host })
export function locateSoapCall(engagementId: string, invocationId: string) {
  return api.get<{ host: SoapBackendHost | null; position: number | null }>(
    `${estate(engagementId)}/soap/locate?${new URLSearchParams({ invocation_id: invocationId })}`,
  )
}
