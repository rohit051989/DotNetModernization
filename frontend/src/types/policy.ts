/** Step policy — global and engagement layers. See
 * 23-WORKFLOW-ADMINISTRATION.md Part A: `engagement_id === null` means
 * global ("nobody should run this yet"); a non-null `engagement_id` means a
 * client-specific override ("this client does not want this"). Precedence
 * is engagement beats global beats default. */
export interface StepPolicy {
  id: string
  engagement_id: string | null
  step_name: string
  enabled: boolean
  reason: string
  set_by: string | null
  set_at: string
  created_at: string
  updated_at: string
}

export interface StepPolicyRequest {
  step_name: string
  enabled: boolean
  /** Required in either direction (Part A) — "why is this step running when
   * it is globally off" needs an answer as much as the reverse. */
  reason: string
  set_by?: string | null
  cascade?: boolean
}

export interface StepPolicySetResult {
  policy: StepPolicy
  cascaded: StepPolicy[]
  /** Set only by a global disable: engagement ids with their own row
   * explicitly re-enabling this step, and therefore unaffected by this
   * change. Always empty for engagement-scoped requests and global enables. */
  overriding_engagements: string[]
}

export interface StepPolicyValidateResponse {
  would_orphan: boolean
  dependent_steps: string[]
  message: string | null
}

/** The extra fields carried by a POLICY_ORPHANS_DEPENDENTS (409, disabling)
 * or POLICY_REVERT_ORPHANS_STEP (409, DELETE) error detail item, beyond the
 * generic { field, message } shape every other endpoint uses. */
export interface PolicyConflictDetail {
  code: 'POLICY_ORPHANS_DEPENDENTS' | 'POLICY_REVERT_ORPHANS_STEP'
  message: string
  dependent_steps?: string[]
  blocking_steps?: string[]
  resolution: string
}

export type PolicySource = 'default' | 'global' | 'engagement'

/** One step's resolved state, with the raw layer rows so a caller can show
 * inheritance without recomputing it (23-WORKFLOW-ADMINISTRATION.md Part B). */
export interface EffectivePolicy {
  step_name: string
  enabled: boolean
  source: PolicySource
  reason: string | null
  global_policy: StepPolicy | null
  engagement_policy: StepPolicy | null
}

/** The minimal state shown per policy-matrix cell. */
export interface PolicyState {
  enabled: boolean
  source: PolicySource
  reason?: string | null
}

export interface PolicyMatrixEngagement {
  id: string
  client_name: string
}

export interface PolicyMatrixStep {
  step_name: string
  lifecycle_step_no: number | null
  display_name: string
  implementation_status: string
  global: PolicyState
  engagements: Record<string, PolicyState>
}

export interface PolicyMatrix {
  engagements: PolicyMatrixEngagement[]
  steps: PolicyMatrixStep[]
}
