import { api } from './client'
import type {
  EffectivePolicy,
  PolicyMatrix,
  StepPolicy,
  StepPolicyRequest,
  StepPolicySetResult,
  StepPolicyValidateResponse,
} from '../types/policy'

// ---- Engagement layer — 22-STEP-SEQUENCING-AND-POLICY.md Part C ----

const engagementBase = (engagementId: string) => `/api/engagements/${encodeURIComponent(engagementId)}/step-policies`

export function listStepPolicies(engagementId: string) {
  return api.get<StepPolicy[]>(engagementBase(engagementId))
}

export function setStepPolicy(engagementId: string, payload: StepPolicyRequest) {
  return api.post<StepPolicySetResult>(engagementBase(engagementId), payload)
}

/** Dry run — no row is created or changed either way. Lets the UI warn
 * before the operator commits. */
export function validateStepPolicy(engagementId: string, stepName: string, enabled: boolean) {
  return api.post<StepPolicyValidateResponse>(`${engagementBase(engagementId)}/validate`, { step_name: stepName, enabled })
}

/** `force: true` bypasses the re-enable guard (POLICY_REVERT_ORPHANS_STEP) —
 * only pass it after the operator has explicitly confirmed the orphaned
 * state via the 409's detail. */
export function deleteStepPolicy(engagementId: string, stepName: string, force = false) {
  const query = force ? '?force=true' : ''
  return api.delete<void>(`${engagementBase(engagementId)}/${encodeURIComponent(stepName)}${query}`)
}

// ---- Global layer — 23-WORKFLOW-ADMINISTRATION.md Part A/B ----

const GLOBAL_BASE = '/api/workflow/step-policies'

export function listGlobalStepPolicies() {
  return api.get<StepPolicy[]>(GLOBAL_BASE)
}

export function setGlobalStepPolicy(payload: StepPolicyRequest) {
  return api.post<StepPolicySetResult>(GLOBAL_BASE, payload)
}

export function validateGlobalStepPolicy(stepName: string, enabled: boolean) {
  return api.post<StepPolicyValidateResponse>(`${GLOBAL_BASE}/validate`, { step_name: stepName, enabled })
}

export function deleteGlobalStepPolicy(stepName: string, force = false) {
  const query = force ? '?force=true' : ''
  return api.delete<void>(`${GLOBAL_BASE}/${encodeURIComponent(stepName)}${query}`)
}

// ---- Cross-layer read views — 23-WORKFLOW-ADMINISTRATION.md Part B ----

/** Resolved state for every step in scope. Omit `engagementId` to resolve
 * global-vs-default only. */
export function getEffectivePolicies(engagementId?: string | null) {
  const query = engagementId ? `?engagement_id=${encodeURIComponent(engagementId)}` : ''
  return api.get<EffectivePolicy[]>(`/api/workflow/effective-policies${query}`)
}

/** The master-view steps x engagements overview. */
export function getPolicyMatrix() {
  return api.get<PolicyMatrix>('/api/workflow/policy-matrix')
}
