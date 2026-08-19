import { api } from './client'
import type { StepPolicy, StepPolicyRequest, StepPolicySetResult, StepPolicyValidateResponse } from '../types/policy'

const base = (engagementId: string) => `/api/engagements/${encodeURIComponent(engagementId)}/step-policies`

export function listStepPolicies(engagementId: string) {
  return api.get<StepPolicy[]>(base(engagementId))
}

export function setStepPolicy(engagementId: string, payload: StepPolicyRequest) {
  return api.post<StepPolicySetResult>(base(engagementId), payload)
}

/** Dry run — no row is created or changed either way. Lets the UI warn
 * before the operator commits (22-STEP-SEQUENCING-AND-POLICY.md Part F). */
export function validateStepPolicy(engagementId: string, stepName: string, enabled: boolean) {
  return api.post<StepPolicyValidateResponse>(`${base(engagementId)}/validate`, { step_name: stepName, enabled })
}

/** `force: true` bypasses the re-enable guard (POLICY_REVERT_ORPHANS_STEP) —
 * only pass it after the operator has explicitly confirmed the orphaned
 * state via the 409's detail. */
export function deleteStepPolicy(engagementId: string, stepName: string, force = false) {
  const query = force ? '?force=true' : ''
  return api.delete<void>(`${base(engagementId)}/${encodeURIComponent(stepName)}${query}`)
}
