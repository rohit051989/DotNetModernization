import { useCallback, useEffect, useMemo, useState } from 'react'
import { getEffectivePolicies, getPolicyMatrix } from '../../api/policies'
import type { EffectivePolicy, PolicyMatrix } from '../../types/policy'
import { StepPolicyDialog } from '../workflow/definition/StepPolicyDialog'
import { LimitedList } from '../../components/LimitedList'

/** 23-WORKFLOW-ADMINISTRATION.md Part C3 — one row per step appearing in an
 * active job definition, showing effective global state, reason, set by/at,
 * and how many engagements override it. */
export function GlobalPolicySection() {
  const [policies, setPolicies] = useState<EffectivePolicy[]>([])
  const [matrix, setMatrix] = useState<PolicyMatrix | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [onlyDisabled, setOnlyDisabled] = useState(false)
  const [target, setTarget] = useState<EffectivePolicy | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    Promise.all([getEffectivePolicies(), getPolicyMatrix()])
      .then(([effective, matrixData]) => {
        setPolicies(effective)
        setMatrix(matrixData)
      })
      .catch(() => setLoadError('Could not load global policy state.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const overridingEngagements = useMemo(() => {
    const byStep = new Map<string, string[]>()
    if (matrix) {
      for (const step of matrix.steps) {
        const overriding = Object.entries(step.engagements)
          .filter(([, state]) => state.source === 'engagement')
          .map(([engagementId]) => engagementId)
        byStep.set(step.step_name, overriding)
      }
    }
    return byStep
  }, [matrix])

  const displayNames = useMemo(() => {
    const byStep = new Map<string, string>()
    matrix?.steps.forEach((s) => byStep.set(s.step_name, s.display_name))
    return byStep
  }, [matrix])

  const disabledCount = policies.filter((p) => p.source === 'global' && !p.enabled).length
  const visiblePolicies = onlyDisabled ? policies.filter((p) => p.source === 'global' && !p.enabled) : policies

  if (loading) return <p className="p-4 text-sm text-neutral-400">Loading global policy…</p>
  if (loadError) return <p className="p-4 text-sm text-red-600">{loadError}</p>

  return (
    <div className="space-y-3">
      {disabledCount > 0 && (
        <button
          type="button"
          onClick={() => setOnlyDisabled((v) => !v)}
          className="w-full rounded border border-amber-300 bg-amber-50 px-3 py-2 text-left text-sm text-amber-800 hover:bg-amber-100"
        >
          <span className="font-semibold">
            {disabledCount} step{disabledCount === 1 ? ' is' : 's are'} globally disabled
          </span>{' '}
          <span className="underline">{onlyDisabled ? 'show all steps' : 'show only these'}</span>
        </button>
      )}

      <section className="rounded border border-neutral-200 bg-white">
        <LimitedList
          items={visiblePolicies}
          name={(p) => [displayNames.get(p.step_name), p.step_name]}
          noun="steps"
        >
          {(visible) => (
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Step</th>
                  <th className="px-3 py-2 font-medium">Global state</th>
                  <th className="px-3 py-2 font-medium">Reason</th>
                  <th className="px-3 py-2 font-medium">Set by</th>
                  <th className="px-3 py-2 font-medium">Set at</th>
                  <th className="px-3 py-2 font-medium">Overriding engagements</th>
                  <th className="px-3 py-2 font-medium" />
                </tr>
              </thead>
              <tbody>
                {visible.map((policy) => {
                  const overriding = overridingEngagements.get(policy.step_name) ?? []
                  return (
                    <tr key={policy.step_name} className="border-b border-neutral-100">
                      <td className="px-4 py-2">
                        <div className="text-neutral-800">{displayNames.get(policy.step_name) ?? policy.step_name}</div>
                        <div className="font-mono text-[10px] text-neutral-400">{policy.step_name}</div>
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                            policy.enabled ? 'border-teal-200 bg-teal-50 text-teal-700' : 'border-red-200 bg-red-50 text-red-700'
                          }`}
                        >
                          {policy.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-xs text-neutral-500">{policy.reason ?? '—'}</td>
                      <td className="px-3 py-2 text-xs text-neutral-500">{policy.global_policy?.set_by ?? '—'}</td>
                      <td className="px-3 py-2 text-xs text-neutral-500">
                        {policy.global_policy ? new Date(policy.global_policy.set_at).toLocaleString() : '—'}
                      </td>
                      <td className="px-3 py-2 text-xs text-neutral-500">
                        {overriding.length === 0 ? '—' : <OverridingEngagements names={overriding} />}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <button type="button" onClick={() => setTarget(policy)} className="text-xs text-violet-600 hover:underline">
                          {policy.source === 'global' ? (policy.enabled ? 'Remove override…' : 'Re-enable…') : 'Disable…'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </LimitedList>
      </section>

      {target && (
        <StepPolicyDialog
          scope="global"
          stepName={target.step_name}
          displayName={displayNames.get(target.step_name) ?? target.step_name}
          effectiveEnabled={target.enabled}
          ownRow={target.global_policy}
          onClose={() => setTarget(null)}
          onChanged={load}
        />
      )}
    </div>
  )
}

/** The engagements overriding a global policy, named — not a count with the
 * names behind a tooltip, which a touch screen cannot open. */
function OverridingEngagements({ names }: { names: string[] }) {
  return (
    <span className="block">
      <span className="font-medium text-violet-700">
        {names.length} engagement{names.length === 1 ? '' : 's'}:
      </span>{' '}
      <LimitedList items={names} name={(n) => n} noun="engagements" className="inline">
        {(visible) => visible.join(', ')}
      </LimitedList>
    </span>
  )
}
