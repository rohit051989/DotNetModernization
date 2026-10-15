import { api } from './client'
import type { Engagement, HealthStatus } from '../types/catalog'

// The legacy pattern / target-state / decision-record endpoints still exist
// on the backend, but the Catalog tab now reads the item model — see
// api/items.ts (28-ITEM-AND-CONVERSION-MODEL.md).

export function getHealth() {
  return api.get<HealthStatus>('/api/health')
}

export function listEngagements() {
  return api.get<Engagement[]>('/api/engagements')
}

export interface EngagementCreate {
  id: string
  client_name: string
  target_framework: string
  target_platform?: string | null
  description?: string | null
}

export function createEngagement(body: EngagementCreate) {
  return api.post<Engagement>('/api/engagements', body)
}
