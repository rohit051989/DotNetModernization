import type { PolicySource, StepPolicy } from '../../../types/policy'

/** The shape every policy-bearing view needs — the job definition viewer's
 * per-step `policy` field and an `EffectivePolicy` from
 * `GET /api/workflow/effective-policies` are both this shape. Shared here so
 * the flow-card viewer and the engagement Policy section (two entry points
 * to the same operations — 23-WORKFLOW-ADMINISTRATION.md Part D) render
 * identical wording instead of drifting apart. */
export interface PolicyLike {
  enabled: boolean
  source: PolicySource
  reason: string | null
  global_policy: StepPolicy | null
  engagement_policy: StepPolicy | null
}

/** Part D: "Inheritance is shown." A globally disabled step reads "Disabled
 * globally — <reason>"; an engagement row overriding a global one reads
 * "Enabled for this engagement — overrides global disable". */
export function policyStatusText(policy: PolicyLike): string {
  if (policy.source === 'default') return 'Enabled'
  if (policy.source === 'global') {
    return `Disabled globally — ${policy.reason ?? 'no reason recorded'}`
  }
  // source === 'engagement'
  if (policy.enabled) {
    const overridesGlobalDisable = policy.global_policy !== null && !policy.global_policy.enabled
    return overridesGlobalDisable ? 'Enabled for this engagement — overrides global disable' : 'Enabled'
  }
  return `Disabled — ${policy.reason ?? 'no reason recorded'}`
}

/** This scope's own row, if one exists — determines whether a toggle
 * creates a new row (none exists yet) or reverts the existing one. Pass
 * `isMasterScope: true` for the global editor, `false` for an engagement
 * editor. */
export function policyOwnRow(policy: PolicyLike, isMasterScope: boolean): StepPolicy | null {
  return isMasterScope ? policy.global_policy : policy.engagement_policy
}

/** The row actually in effect, regardless of scope — used to show "who set
 * it" even when the winning row is the *global* one, not this engagement's. */
export function policyWinningRow(policy: PolicyLike): StepPolicy | null {
  if (policy.source === 'engagement') return policy.engagement_policy
  if (policy.source === 'global') return policy.global_policy
  return null
}

export function policyToggleLabel(policy: PolicyLike, isMasterScope: boolean): string {
  const ownRow = policyOwnRow(policy, isMasterScope)
  if (ownRow) return ownRow.enabled ? 'Remove override…' : 'Re-enable…'
  return policy.enabled ? 'Disable…' : 'Override…'
}
