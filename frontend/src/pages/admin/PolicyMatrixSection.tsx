import { useCallback, useEffect, useState } from 'react'
import { getEffectivePolicies, getPolicyMatrix } from '../../api/policies'
import type { EffectivePolicy, PolicyMatrix as PolicyMatrixData, PolicyState } from '../../types/policy'
import { StepPolicyDialog, type PolicyScope } from '../workflow/definition/StepPolicyDialog'

interface DialogTarget {
  scope: PolicyScope
  stepName: string
  displayName: string
  effectiveEnabled: boolean
  ownRow: EffectivePolicy['global_policy']
}

function cellClass(state: PolicyState): string {
  if (state.enabled) {
    return state.source === 'engagement'
      ? 'border-2 border-emerald-500 bg-white' // enabled, outlined — engagement overrides a global disable
      : 'bg-emerald-500' // solid enabled — default
  }
  return state.source === 'engagement'
    ? 'bg-[repeating-linear-gradient(45deg,#fca5a5,#fca5a5_3px,#fee2e2_3px,#fee2e2_6px)]' // disabled, hatched — engagement row
    : 'bg-red-500' // disabled, filled — global
}

function cellTitle(stepName: string, engagementLabel: string, state: PolicyState): string {
  const reason = state.reason ? ` — ${state.reason}` : ''
  return `${stepName} · ${engagementLabel}: ${state.enabled ? 'enabled' : 'disabled'} (${state.source})${reason}`
}

/** 23-WORKFLOW-ADMINISTRATION.md Part C4 — steps down, engagements across.
 * Sparse by design: most cells are default, so a deviation stands out
 * rather than needing to be hunted. */
export function PolicyMatrixSection() {
  const [matrix, setMatrix] = useState<PolicyMatrixData | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [target, setTarget] = useState<DialogTarget | null>(null)
  const [resolving, setResolving] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    getPolicyMatrix()
      .then(setMatrix)
      .catch(() => setLoadError('Could not load the policy matrix.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function openGlobalCell(stepName: string, displayName: string) {
    setResolving(`${stepName}:global`)
    try {
      const effective = await getEffectivePolicies()
      const match = effective.find((p) => p.step_name === stepName)
      if (!match) return
      setTarget({
        scope: 'global',
        stepName,
        displayName,
        effectiveEnabled: match.enabled,
        ownRow: match.global_policy,
      })
    } finally {
      setResolving(null)
    }
  }

  async function openEngagementCell(stepName: string, displayName: string, engagementId: string) {
    setResolving(`${stepName}:${engagementId}`)
    try {
      const effective = await getEffectivePolicies(engagementId)
      const match = effective.find((p) => p.step_name === stepName)
      if (!match) return
      setTarget({
        scope: { engagementId },
        stepName,
        displayName,
        effectiveEnabled: match.enabled,
        ownRow: match.engagement_policy,
      })
    } finally {
      setResolving(null)
    }
  }

  if (loading) return <p className="p-4 text-sm text-neutral-400">Loading policy matrix…</p>
  if (loadError) return <p className="p-4 text-sm text-red-600">{loadError}</p>
  if (!matrix) return null

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-4 text-xs text-neutral-500">
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm bg-emerald-500" /> Default — enabled
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm border-2 border-emerald-500 bg-white" /> Engagement overrides a global disable
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm bg-red-500" /> Disabled globally
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-3 w-3 rounded-sm bg-[repeating-linear-gradient(45deg,#fca5a5,#fca5a5_3px,#fee2e2_3px,#fee2e2_6px)]" /> Disabled by
          an engagement
        </span>
      </div>

      <div className="overflow-x-auto rounded border border-neutral-200 bg-white">
        <table className="text-left text-xs">
          <thead className="uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="sticky left-0 bg-white px-3 py-2 font-medium">Step</th>
              <th className="px-3 py-2 font-medium">Global</th>
              {matrix.engagements.map((e) => (
                <th key={e.id} className="px-3 py-2 font-medium">
                  {e.client_name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.steps.map((step) => (
              <tr key={step.step_name} className="border-t border-neutral-100">
                <td className="sticky left-0 bg-white px-3 py-2">
                  <div className="text-neutral-800">{step.display_name}</div>
                  <div className="font-mono text-[10px] text-neutral-400">
                    {step.lifecycle_step_no !== null ? `L${step.lifecycle_step_no} · ` : ''}
                    {step.step_name}
                  </div>
                </td>
                <td className="px-3 py-2">
                  <button
                    type="button"
                    disabled={resolving === `${step.step_name}:global`}
                    title={cellTitle(step.display_name, 'global', step.global)}
                    onClick={() => openGlobalCell(step.step_name, step.display_name)}
                    className={`h-6 w-10 rounded-sm ${cellClass(step.global)} disabled:opacity-50`}
                  />
                </td>
                {matrix.engagements.map((engagement) => {
                  const state = step.engagements[engagement.id]
                  return (
                    <td key={engagement.id} className="px-3 py-2">
                      {state && (
                        <button
                          type="button"
                          disabled={resolving === `${step.step_name}:${engagement.id}`}
                          title={cellTitle(step.display_name, engagement.client_name, state)}
                          onClick={() => openEngagementCell(step.step_name, step.display_name, engagement.id)}
                          className={`h-6 w-10 rounded-sm ${cellClass(state)} disabled:opacity-50`}
                        />
                      )}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {target && (
        <StepPolicyDialog
          scope={target.scope}
          stepName={target.stepName}
          displayName={target.displayName}
          effectiveEnabled={target.effectiveEnabled}
          ownRow={target.ownRow}
          onClose={() => setTarget(null)}
          onChanged={load}
        />
      )}
    </div>
  )
}
