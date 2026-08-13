import { api } from './client'
import type { Engagement, HealthStatus } from '../types/catalog'

export function getHealth() {
  return api.get<HealthStatus>('/api/health')
}

export function listEngagements() {
  return api.get<Engagement[]>('/api/engagements')
}
