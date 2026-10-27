import { api } from './client'
import type { EntryPointCapabilities } from '../types/surface'
import type { EngagementRuleConflicts, MasterRuleConflict, WorkItemImpact } from '../types/impact'

/** Step 4's capability manifest: every kind it detects, what it does not,
 * and how often each kind is found across the estate. */
export function getEntryPointCapabilities() {
  return api.get<EntryPointCapabilities>('/api/workflow/steps/entry-point-inventory/capabilities')
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

