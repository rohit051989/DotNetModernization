/** Engagement step policy — see 22-STEP-SEQUENCING-AND-POLICY.md Part C. */
export interface StepPolicy {
  id: string
  engagement_id: string
  step_name: string
  enabled: boolean
  reason: string | null
  set_by: string | null
  set_at: string
  created_at: string
  updated_at: string
}

export interface StepPolicyRequest {
  step_name: string
  enabled: boolean
  reason?: string | null
  set_by?: string | null
  cascade?: boolean
}

export interface StepPolicySetResult {
  policy: StepPolicy
  cascaded: StepPolicy[]
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
