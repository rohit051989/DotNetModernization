import { useCallback, useEffect, useState } from 'react'
import { getEffectivePolicies } from '../../api/policies'
import type { EffectivePolicy } from '../../types/policy'
import { StepPolicyDialog } from './definition/StepPolicyDialog'
import { policyStatusText, policyToggleLabel, policyWinningRow } from './definition/policyPresentation'

interface EngagementPolicySectionProps {
  engagementId: string
}

/** A second, more discoverable entry point to engagement step policy —
 * 23-WORKFLOW-ADMINISTRATION.md Part D, mirroring the structure Master
 * Catalog view already has for global policy (Part C3). The toggle inside
 * the job definition viewer's flow cards stays; this doesn't replace it,
 * it just means an operator doesn't have to already know to click into a
 * specific job's flow to find policy at all. */
export function EngagementPolicySection({ engagementId }: EngagementPolicySectionProps) {
  const [policies, setPolicies] = useState<EffectivePolicy[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [target, setTarget] = useState<EffectivePolicy | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    getEffectivePolicies(engagementId)
      .then(setPolicies)
      .catch(() => setLoadError('Could not load policy state for this engagement.'))
      .finally(() => setLoading(false))
  }, [engagementId])

  useEffect(() => {
    load()
  }, [load])

  if (loading) return <p className="p-4 text-sm text-neutral-400">Loading policy…</p>
  if (loadError) return <p className="p-4 text-sm text-red-600">{loadError}</p>

  // "The policy summary strip lists every step whose effective state
  // differs from default, with the layer responsible" — promoted to this
  // section rather than only inside the viewer (Part D).
  const deviations = policies.filter((p) => p.source !== 'default')

  return (
    <section className="rounded border border-neutral-200 bg-white">
      <h2 className="border-b border-neutral-100 px-4 py-3 text-sm font-semibold text-neutral-900">Policy</h2>

      {deviations.length > 0 && (
        <div className="border-b border-neutral-100 bg-amber-50 p-3 text-xs">
          <p className="mb-1 font-semibold uppercase tracking-wide text-amber-700">
            {deviations.length} step{deviations.length === 1 ? '' : 's'} {deviations.length === 1 ? 'differs' : 'differ'} from default
          </p>
          <ul className="space-y-1">
            {deviations.map((p) => (
              <li key={p.step_name} className="text-amber-800">
                <span className="font-medium">{p.step_name}</span>{' '}
                <span className="rounded bg-amber-100 px-1 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                  {p.source}
                </span>
                {p.reason ? ` — ${p.reason}` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}

      {policies.length === 0 ? (
        <p className="p-4 text-sm text-neutral-400">No steps appear in an active job definition yet.</p>
      ) : (
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-4 py-2 font-medium">Step</th>
              <th className="px-3 py-2 font-medium">Effective state</th>
              <th className="px-3 py-2 font-medium">Source</th>
              <th className="px-3 py-2 font-medium">Reason</th>
              <th className="px-3 py-2 font-medium">Set by</th>
              <th className="px-3 py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {policies.map((policy) => {
              const winningRow = policyWinningRow(policy)
              return (
                <tr key={policy.step_name} className="border-b border-neutral-100">
                  <td className="px-4 py-2 font-mono text-xs text-neutral-700">{policy.step_name}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`rounded-full border px-2 py-0.5 text-xs font-medium ${
                        policy.enabled ? 'border-teal-200 bg-teal-50 text-teal-700' : 'border-red-200 bg-red-50 text-red-700'
                      }`}
                    >
                      {policy.enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-neutral-600">
                      {policy.source}
                    </span>
                    {policy.source === 'global' && <span className="ml-1 text-[10px] italic text-neutral-400">inherited</span>}
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-500" title={policyStatusText(policy)}>
                    {policy.reason ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-xs text-neutral-500">{winningRow?.set_by ?? '—'}</td>
                  <td className="px-3 py-2 text-right">
                    <button type="button" onClick={() => setTarget(policy)} className="text-xs text-violet-600 hover:underline">
                      {policyToggleLabel(policy, false)}
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {target && (
        <StepPolicyDialog
          scope={{ engagementId }}
          stepName={target.step_name}
          displayName={target.step_name}
          effectiveEnabled={target.enabled}
          ownRow={target.engagement_policy}
          onClose={() => setTarget(null)}
          onChanged={load}
        />
      )}
    </section>
  )
}
