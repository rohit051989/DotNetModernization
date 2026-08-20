/** A registered lifecycle step — see 17-LIFECYCLE-STEPS.md and
 * 23-WORKFLOW-ADMINISTRATION.md Part C1. Read-only in the UI; registration
 * is a build-time, API-only operation. */
export interface ArtifactRef {
  artifact_type: string
  artifact_version?: string | null
  version_range?: string | null
  optional?: boolean | null
}

export interface StepRegistration {
  step_name: string
  lifecycle_step_no: number | null
  display_name: string
  owner_code: string
  version: string
  owner_team: string | null
  adapter_type: string
  adapter_config: Record<string, unknown>
  consumes: ArtifactRef[]
  produces: ArtifactRef[]
  implementation_status: 'stub' | 'implemented' | 'deprecated'
  registered_at: string
  updated_at: string
}
