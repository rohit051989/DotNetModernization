import { api } from './client'
import type {
  DecisionRecord,
  DecisionRecordUpdateInput,
  DecisionRecordUpsertInput,
  Engagement,
  EngagementPatternDeferRequest,
  EngagementPatternSoftDeleteResponse,
  EngagementPatternView,
  HealthStatus,
  PatternCreateInput,
  PatternDeprecateResponse,
  PatternDetail,
  PatternSoftDeleteResponse,
  PatternSummary,
  PatternUpdateInput,
  TargetStateCreateInput,
  TargetStateDeprecateResponse,
  TargetStateDetail,
  TargetStateSoftDeleteResponse,
  TargetStateUpdateInput,
} from '../types/catalog'

export function getHealth() {
  return api.get<HealthStatus>('/api/health')
}

export function listEngagements() {
  return api.get<Engagement[]>('/api/engagements')
}

export function listPatterns(params: { q?: string } = {}) {
  const query = new URLSearchParams()
  if (params.q) query.set('q', params.q)
  const qs = query.toString()
  return api.get<PatternSummary[]>(`/api/patterns${qs ? `?${qs}` : ''}`)
}

export function getPattern(patternId: string) {
  return api.get<PatternDetail>(`/api/patterns/${encodeURIComponent(patternId)}`)
}

export function createPattern(payload: PatternCreateInput) {
  return api.post<PatternDetail>('/api/patterns', payload)
}

export function updatePattern(patternId: string, payload: PatternUpdateInput) {
  return api.put<PatternDetail>(`/api/patterns/${encodeURIComponent(patternId)}`, payload)
}

export function deprecatePattern(patternId: string) {
  return api.post<PatternDeprecateResponse>(`/api/patterns/${encodeURIComponent(patternId)}/deprecate`)
}

export function deletePattern(patternId: string) {
  return api.delete<PatternSoftDeleteResponse>(`/api/patterns/${encodeURIComponent(patternId)}`)
}

export function listTargetStates(patternId: string) {
  return api.get<TargetStateDetail[]>(`/api/patterns/${encodeURIComponent(patternId)}/target-states`)
}

export function createTargetState(patternId: string, payload: TargetStateCreateInput) {
  return api.post<TargetStateDetail>(`/api/patterns/${encodeURIComponent(patternId)}/target-states`, payload)
}

export function updateTargetState(targetStateId: string, payload: TargetStateUpdateInput) {
  return api.put<TargetStateDetail>(`/api/target-states/${encodeURIComponent(targetStateId)}`, payload)
}

export function deprecateTargetState(targetStateId: string) {
  return api.post<TargetStateDeprecateResponse>(
    `/api/target-states/${encodeURIComponent(targetStateId)}/deprecate`,
  )
}

export function deleteTargetState(targetStateId: string) {
  return api.delete<TargetStateSoftDeleteResponse>(
    `/api/target-states/${encodeURIComponent(targetStateId)}`,
  )
}

export function listDecisions(engagementId: string) {
  return api.get<DecisionRecord[]>(`/api/engagements/${encodeURIComponent(engagementId)}/decisions`)
}

export function getEngagementPatternDecision(engagementId: string, patternId: string) {
  return api.get<DecisionRecord>(
    `/api/engagements/${encodeURIComponent(engagementId)}/patterns/${encodeURIComponent(patternId)}/decision`,
  )
}

export function upsertEngagementPatternDecision(
  engagementId: string,
  patternId: string,
  payload: DecisionRecordUpsertInput,
) {
  return api.put<DecisionRecord>(
    `/api/engagements/${encodeURIComponent(engagementId)}/patterns/${encodeURIComponent(patternId)}/decision`,
    payload,
  )
}

export function updateDecision(decisionId: string, payload: DecisionRecordUpdateInput) {
  return api.put<DecisionRecord>(`/api/decisions/${encodeURIComponent(decisionId)}`, payload)
}

export function supersedeDecision(decisionId: string) {
  return api.post<DecisionRecord>(`/api/decisions/${encodeURIComponent(decisionId)}/supersede`)
}

export function listEngagementPatterns(engagementId: string) {
  return api.get<EngagementPatternView[]>(
    `/api/engagements/${encodeURIComponent(engagementId)}/patterns`,
  )
}

export function getEngagementPattern(engagementId: string, patternId: string) {
  return api.get<EngagementPatternView>(
    `/api/engagements/${encodeURIComponent(engagementId)}/patterns/${encodeURIComponent(patternId)}`,
  )
}

export function deferEngagementPattern(
  engagementId: string,
  patternId: string,
  payload: EngagementPatternDeferRequest,
) {
  return api.post<EngagementPatternView>(
    `/api/engagements/${encodeURIComponent(engagementId)}/patterns/${encodeURIComponent(patternId)}/defer`,
    payload,
  )
}

export function reactivateEngagementPattern(engagementId: string, patternId: string) {
  return api.post<EngagementPatternView>(
    `/api/engagements/${encodeURIComponent(engagementId)}/patterns/${encodeURIComponent(patternId)}/reactivate`,
  )
}

export function deleteEngagementPattern(engagementId: string, patternId: string) {
  return api.delete<EngagementPatternSoftDeleteResponse>(
    `/api/engagements/${encodeURIComponent(engagementId)}/patterns/${encodeURIComponent(patternId)}`,
  )
}

export function restoreEngagementPattern(engagementId: string, patternId: string) {
  return api.post<EngagementPatternSoftDeleteResponse>(
    `/api/engagements/${encodeURIComponent(engagementId)}/patterns/${encodeURIComponent(patternId)}/restore`,
  )
}
