import { api } from './client'
import type {
  DraftPattern,
  ItemType,
  MergeProposal,
  QueueItem,
  QueueItemStatus,
  QueueSummary,
} from '../types/validationQueue'

/** Generic across gate types — no step-6 knowledge here. Omitting `stepName`
 * is what makes the Workflow tab's pending-approvals list cross-cutting. */
export function listValidationQueue(
  engagementId: string,
  params: { status?: QueueItemStatus; itemType?: ItemType; stepName?: string; includeDeferred?: boolean } = {},
) {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.itemType) query.set('item_type', params.itemType)
  if (params.stepName) query.set('step_name', params.stepName)
  if (params.includeDeferred) query.set('include_deferred', 'true')
  const qs = query.toString()
  return api.get<QueueItem[]>(`/api/engagements/${engagementId}/validation-queue${qs ? `?${qs}` : ''}`)
}

export function getValidationQueueSummary(engagementId: string) {
  return api.get<QueueSummary>(`/api/engagements/${engagementId}/validation-queue/summary`)
}

/** Records the answer. Does NOT apply it — the step does that on the next
 * resume — and does NOT resume the job. */
export function decideQueueItem(
  itemId: string,
  body: { outcome: string; outcome_detail?: Record<string, unknown> | null; note?: string | null; decided_by: string },
) {
  return api.post<QueueItem>(`/api/validation-queue/${itemId}/decide`, body)
}

export function deferQueueItem(
  itemId: string,
  body: { until_coverage?: number | null; until_member_count?: number | null; note?: string | null; deferred_by?: string },
) {
  return api.post<QueueItem>(`/api/validation-queue/${itemId}/defer`, body)
}

/** Returns a draft for the rule builder. Nothing is persisted. */
export function createPatternDraft(engagementId: string, clusterId: string) {
  return api.post<DraftPattern>(
    `/api/engagements/${engagementId}/pattern-candidates/${clusterId}/create-pattern`,
    {},
  )
}

/** Returns the suggested rule diff. The target pattern is not modified. */
export function getMergeProposal(engagementId: string, clusterId: string, patternId: string) {
  return api.post<MergeProposal>(
    `/api/engagements/${engagementId}/pattern-candidates/${clusterId}/merge-proposal?pattern_id=${encodeURIComponent(patternId)}`,
    {},
  )
}
