import { useCallback, useEffect, useState } from 'react'
import { getValidationQueueSummary, listValidationQueue } from '../../api/validationQueue'
import type { QueueItem, QueueSummary } from '../../types/validationQueue'
import { EmptyState } from '../../components/EmptyState'
import { usePolling } from '../../hooks/usePolling'

const POLL_INTERVAL_MS = 15000

/** Human-readable labels for gate item types. Every gate step's type is listed,
 * including the ones whose steps do not exist yet — steps 22, 38 and 50 inherit
 * this surface with no further work. Unknown types fall back to the raw value.
 * `pattern_candidate` belongs to the retired pattern-validation step; it stays
 * only so queue items it raised before retirement still read sensibly. */
const ITEM_TYPE_LABEL: Record<string, string> = {
  pattern_candidate: 'Pattern candidate (retired)',
  target_state_selection: 'Target state',
  migration_plan: 'Migration plan',
  code_review: 'Code review',
  release_approval: 'Release approval',
}

const STEP_LABEL: Record<string, string> = {
  'pattern-validation': 'Pattern validation (retired)',
  'target-state-approval': 'Target state approval (step 16)',
  'plan-approval-gate': 'Plan approval (step 22)',
  'code-review-gate': 'Code review (step 38)',
  'release-approval-gate': 'Release approval (step 50)',
}

function age(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h`
  return `${Math.round(hours / 24)}d`
}

interface PendingApprovalsProps {
  engagementId: string
  onSelectExecution: (executionId: string) => void
}

export function PendingApprovals({ engagementId, onSelectExecution }: PendingApprovalsProps) {
  const [items, setItems] = useState<QueueItem[]>([])
  const [summary, setSummary] = useState<QueueSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showDeferred, setShowDeferred] = useState(false)

  const load = useCallback(async () => {
    try {
      // No step_name filter: this list is cross-cutting by design.
      const [queue, sum] = await Promise.all([
        listValidationQueue(engagementId, { status: 'open', includeDeferred: showDeferred }),
        getValidationQueueSummary(engagementId),
      ])
      setItems(queue)
      setSummary(sum)
      setError(null)
    } catch {
      setError('Could not load pending approvals.')
    } finally {
      setLoading(false)
    }
  }, [engagementId, showDeferred])

  useEffect(() => {
    setLoading(true)
    load()
  }, [load])

  usePolling(load, POLL_INTERVAL_MS, true)

  const blocking = items.filter((i) => !i.is_deferred)
  const byStep = new Map<string, QueueItem[]>()
  for (const item of items) {
    const list = byStep.get(item.step_name) ?? []
    list.push(item)
    byStep.set(item.step_name, list)
  }

  return (
    <section className="rounded border border-neutral-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-100 px-4 py-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold text-neutral-900">Pending approvals</h2>
          {summary && blocking.length > 0 && (
            <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
              {blocking.length} waiting on you
            </span>
          )}
        </div>
        {summary && summary.deferred_count > 0 && (
          <label className="flex items-center gap-1.5 text-xs text-neutral-600">
            <input
              type="checkbox"
              checked={showDeferred}
              onChange={(event) => setShowDeferred(event.target.checked)}
              className="rounded border-neutral-300"
            />
            Show {summary.deferred_count} deferred
          </label>
        )}
      </div>

      {loading && <p className="p-4 text-sm text-neutral-400">Loading…</p>}
      {!loading && error && <EmptyState title="Could not load pending approvals" description={error} />}

      {!loading && !error && items.length === 0 && (
        <EmptyState
          title="Nothing is waiting for a decision"
          description="Human gates raise items here when a job reaches one."
        />
      )}

      {!loading && !error && items.length > 0 && (
        <>
          {/* Executions held open by these items. An execution in
              STOPPED/AWAITING_APPROVAL is not stuck — it ended cleanly and is
              waiting — so it reads as a call to action rather than a fault. */}
          {summary && summary.blocked_executions.length > 0 && (
            <div className="border-b border-neutral-100 bg-amber-50 px-4 py-3">
              <p className="text-xs font-medium text-amber-900">Executions waiting on these decisions</p>
              <ul className="mt-1 space-y-1">
                {summary.blocked_executions.map((execution) => (
                  <li key={execution.job_execution_id} className="flex flex-wrap items-center gap-2 text-xs text-amber-900">
                    <span className="rounded bg-white px-1.5 py-0.5 font-medium">
                      {execution.batch_status} / {execution.exit_status}
                    </span>
                    <span>
                      blocked by {execution.open_item_count} item{execution.open_item_count === 1 ? '' : 's'}
                    </span>
                    <button
                      type="button"
                      onClick={() => onSelectExecution(execution.job_execution_id)}
                      className="font-mono text-sky-700 hover:underline"
                    >
                      {execution.job_execution_id.slice(0, 8)}…
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {[...byStep.entries()]
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([stepName, stepItems]) => (
              <div key={stepName} className="border-b border-neutral-100 last:border-b-0">
                <div className="px-4 py-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-neutral-500">
                    {STEP_LABEL[stepName] ?? stepName}
                  </h3>
                </div>
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-neutral-400">
                    <tr>
                      <th className="px-4 py-1 font-medium">Item</th>
                      <th className="px-3 py-1 font-medium">Type</th>
                      <th className="px-3 py-1 font-medium">Age</th>
                      <th className="px-3 py-1 font-medium">Priority</th>
                      <th className="px-3 py-1 font-medium">Blocks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stepItems
                      .slice()
                      .sort((a, b) => a.priority - b.priority || a.created_at.localeCompare(b.created_at))
                      .map((item) => (
                        <tr key={item.id} className="border-t border-neutral-50">
                          <td className="px-4 py-2">
                            <span className="text-neutral-900">{item.title}</span>
                            {item.is_deferred && (
                              <span className="ml-2 rounded bg-neutral-100 px-1.5 py-0.5 text-xs text-neutral-600">
                                deferred
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-xs text-neutral-600">
                            {ITEM_TYPE_LABEL[item.item_type] ?? item.item_type}
                          </td>
                          <td className="px-3 py-2 text-xs text-neutral-600">{age(item.created_at)}</td>
                          <td className="px-3 py-2 text-xs text-neutral-600">{item.priority}</td>
                          <td className="px-3 py-2">
                            <button
                              type="button"
                              onClick={() => onSelectExecution(item.job_execution_id)}
                              className="font-mono text-xs text-sky-700 hover:underline"
                            >
                              {item.job_execution_id.slice(0, 8)}…
                            </button>
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            ))}
        </>
      )}
    </section>
  )
}
