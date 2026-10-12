import { api } from './client'
import type { EntryPointBackend, EntryPointCapabilities, EntryPointInventory, OutboundInventory, RepositorySoap } from '../types/surface'
import type { EngagementRuleConflicts, MasterRuleConflict, RepositoryImpact, WorkItemImpact } from '../types/impact'
import type { RepositoryTests } from '../types/tests'

/** 409 until step 4 (entry-point-inventory) has run for the repository. */
export function getRepositoryEntryPoints(repositoryId: string) {
  return api.get<EntryPointInventory>(`/api/repositories/${encodeURIComponent(repositoryId)}/entry-points`)
}

/** Step 4's capability manifest: every kind it detects, what it does not,
 * and how often each kind is found across the estate. */
export function getEntryPointCapabilities() {
  return api.get<EntryPointCapabilities>('/api/workflow/steps/entry-point-inventory/capabilities')
}

/** 409 until step 5 (outbound-invocation-inventory) has run for the repository. */
export function getRepositoryOutboundInvocations(repositoryId: string) {
  return api.get<OutboundInventory>(`/api/repositories/${encodeURIComponent(repositoryId)}/outbound-invocations`)
}

/** Step 5 1.3.0: per application, every inbound operation and the backend calls it reaches. 409 until step 5 has run. */
export function getRepositoryEntryPointBackend(repositoryId: string) {
  return api.get<EntryPointBackend>(`/api/repositories/${encodeURIComponent(repositoryId)}/entry-point-backend`)
}

/** Step 8 (test-coverage-assessment): tests, mapping, buckets, coverage, CI maturity. 409 until it has run. */
export function getRepositoryTests(repositoryId: string) {
  return api.get<RepositoryTests>(`/api/repositories/${encodeURIComponent(repositoryId)}/tests`)
}

/** Step 9 (impact-analysis): totals, hotspots, conflicts, work items and files. 409 until it has run. */
export function getRepositoryImpact(repositoryId: string) {
  return api.get<RepositoryImpact>(`/api/repositories/${encodeURIComponent(repositoryId)}/impact`)
}

/** Step 9: one work item's default and chosen resolutions side by side, with their files. */
export function getWorkItemImpact(repositoryId: string, itemId: string, projectPath: string) {
  const query = new URLSearchParams({ item_id: itemId, project_path: projectPath })
  return api.get<WorkItemImpact>(`/api/repositories/${encodeURIComponent(repositoryId)}/impact/work-item?${query}`)
}

/** Catalog rule conflicts across one engagement's estate, as of its last estate run. */
export function getEngagementRuleConflicts(engagementId: string) {
  return api.get<EngagementRuleConflicts>(`/api/engagements/${encodeURIComponent(engagementId)}/impact/rule-conflicts`)
}

/** Catalog rule conflicts across every engagement, for catalog authors (master view). */
export function listCatalogRuleConflicts() {
  return api.get<MasterRuleConflict[]>('/api/catalog/impact-rule-conflicts')
}

/** The repository's SOAP calls with both verdicts per environment and live matrix confirmation (31 Part J). 409 until step 5 has run. */
export function getRepositorySoapCompatibility(repositoryId: string) {
  return api.get<RepositorySoap>(`/api/repositories/${encodeURIComponent(repositoryId)}/soap-compatibility`)
}
