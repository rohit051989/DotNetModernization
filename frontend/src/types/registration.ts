/** A registered lifecycle step — see 17-LIFECYCLE-STEPS.md and
 * 23-WORKFLOW-ADMINISTRATION.md Part C1. Read-only in the UI; registration
 * is a build-time, API-only operation. */
export interface ArtifactRef {
  artifact_type: string
  artifact_version?: string | null
  version_range?: string | null
  optional?: boolean | null
}

export type Viewpoint =
  | 'CONTEXT'
  | 'FUNCTIONAL'
  | 'INFORMATION'
  | 'CONCURRENCY'
  | 'DEVELOPMENT'
  | 'DEPLOYMENT'
  | 'OPERATIONAL'
  | 'NONE'

export interface StepRegistration {
  step_name: string
  lifecycle_step_no: number | null
  display_name: string
  owner_code: string
  version: string
  owner_team: string | null
  viewpoint: Viewpoint | null
  adapter_type: string
  adapter_config: Record<string, unknown>
  consumes: ArtifactRef[]
  produces: ArtifactRef[]
  implementation_status: 'stub' | 'implemented' | 'deprecated'
  registered_at: string
  updated_at: string
}

/** GET /api/engagements/{eid}/viewpoint-coverage — 25-STANDARDS-AND-VIEWPOINTS.md
 * Part A2. 'NONE' is never reported: it means "no viewpoint", not a coverage
 * dimension. */
export interface ViewpointCoverageEntry {
  viewpoint: Exclude<Viewpoint, 'NONE'>
  contributing_steps: string[]
  total_contributing: number
  implemented_count: number
  ran_count: number
  coverage_label: 'strong' | 'partial' | 'thin' | 'none'
}

export interface ViewpointCoverage {
  engagement_id: string
  viewpoints: ViewpointCoverageEntry[]
}
