import { api } from './client'
import type { Engagement, HealthStatus, PatternDetail, PatternSummary, TargetStateDetail } from '../types/catalog'

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

export function listTargetStates(patternId: string) {
  return api.get<TargetStateDetail[]>(`/api/patterns/${encodeURIComponent(patternId)}/target-states`)
}
