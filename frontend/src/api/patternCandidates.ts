import { api } from './client'
import type { PatternCandidatesResponse, RetryNarrationResult } from '../types/patternCandidates'

export function listPatternCandidates(engagementId: string) {
  return api.get<PatternCandidatesResponse>(`/api/engagements/${engagementId}/pattern-candidates`)
}

/** Re-runs narration against the stored clusters. It does not re-cluster, and
 * cannot change the pattern-candidate-clusters artifact or its checksum —
 * narration is not an input to it. To re-cluster, launch the
 * phase0-estate-consolidation job instead. */
export function retryNarration(engagementId: string) {
  return api.post<RetryNarrationResult>(`/api/engagements/${engagementId}/pattern-candidates/retry-narration`, {})
}
