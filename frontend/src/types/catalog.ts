// Types shared across the app. The item catalog's own types live in
// types/items.ts (28-ITEM-AND-CONVERSION-MODEL.md).

export type LifecycleStatus = 'draft' | 'active' | 'deprecated'
export type ConsumerImpact = 'none' | 'low' | 'medium' | 'high'
export type EffortLevel = 'low' | 'medium' | 'high'
export type ForcingPerspective =
  | 'SECURITY'
  | 'EVOLUTION'
  | 'REGULATION'
  | 'PERFORMANCE_SCALABILITY'
  | 'AVAILABILITY_RESILIENCE'
  | 'LOCATION'
  | 'DEVELOPMENT_RESOURCE'

export interface Engagement {
  id: string
  client_name: string
  description: string | null
  target_platform: string | null
  default_posture: string
  status: LifecycleStatus
  created_at: string
  updated_at: string
  deleted_at: string | null
  deleted_by: string | null
}

export interface HealthStatus {
  status: string
  database: 'connected' | 'error'
  version: string
  /** Set once the admin has updated the database while this backend runs: what to do. It refuses changes until then. */
  platform_update?: string | null
}
