import { api } from './client'
import type {
  Engagement,
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
