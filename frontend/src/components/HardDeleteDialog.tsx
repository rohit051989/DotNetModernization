import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import type { DeletionPlan, DeletionSummary } from '../types/deletion'
import { inputClass } from './FormField'

interface HardDeleteDialogProps {
  title: string
  loadPlan: () => Promise<DeletionPlan>
  onDelete: (typed: string) => Promise<DeletionSummary>
  onClose: () => void
  onDeleted: (summary: DeletionSummary) => void
}

function mb(bytes: number) {
  return `${(bytes / 1_048_576).toFixed(1)} MB`
}

/** A hard delete (docs/VDI-SETUP.md: Deleting a repository or an engagement): shows exactly what will go — rows, folders, the worktrees and branches
 * the platform made in the checkout, and every conversion that has been run, whose agent work lives only on its
 * branch — and deletes only once the repository's or engagement's name is typed. Refused while one of its jobs runs.
 * TODO: gate behind an admin check once auth exists (04-FRONTEND-SPEC.md, "Future: access control"). */
export function HardDeleteDialog({ title, loadPlan, onDelete, onClose, onDeleted }: HardDeleteDialogProps) {
  const [plan, setPlan] = useState<DeletionPlan | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [typed, setTyped] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showRows, setShowRows] = useState(false)

  useEffect(() => {
    loadPlan()
      .then(setPlan)
      .catch((e) => setLoadError(e instanceof ApiError ? e.message : 'Could not work out what would be deleted.'))
  }, [loadPlan])

  async function submit() {
    setBusy(true)
    setError(null)
    try {
      onDeleted(await onDelete(typed))
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not delete.')
    } finally {
      setBusy(false)
    }
  }

  const rows = plan ? Object.values(plan.rows).reduce((a, b) => a + b, 0) : 0
  const run = plan ? plan.checkouts.flatMap((c) => c.run) : []
  const blocked = !!plan && plan.running.length > 0
  const ready = !!plan && typed === plan.confirm && !blocked && !busy

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-neutral-900/40 p-4" role="dialog" aria-modal="true">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl">
        <div className="border-b border-neutral-200 px-5 py-3">
          <h2 className="text-base font-semibold text-red-800">{title}</h2>
          <p className="text-xs text-neutral-500">A hard delete. It cannot be undone.</p>
        </div>
        <div className="flex-1 space-y-3 overflow-y-auto px-5 py-3 text-sm">
          {loadError && <p className="text-red-600">{loadError}</p>}
          {!plan && !loadError && <div className="h-24 animate-pulse rounded bg-neutral-100" />}
          {plan && (
            <>
              {plan.kind === 'engagement' && (
                <p>
                  Engagement <span className="font-medium">{plan.name}</span> ({plan.engagement}) and its{' '}
                  {plan.repositories?.length ?? 0} repositor{plan.repositories?.length === 1 ? 'y' : 'ies'}:{' '}
                  <span className="font-mono text-xs">{plan.repositories?.join(', ') || 'none'}</span>
                </p>
              )}
              <div className="rounded border border-emerald-300 bg-emerald-50 px-2 py-1 text-xs text-emerald-900">
                {plan.checkouts.length === 0 ? (
                  <p>No repository folder is touched.</p>
                ) : (
                  plan.checkouts.map((c) => <p key={c.checkout}>{c.stays}</p>)
                )}
              </div>
              {blocked && (
                <p className="rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-900">
                  Refused while these run: {plan.running.map((r) => `${r.job} (${r.status})`).join(', ')}. Wait for them
                  to end.
                </p>
              )}
              {run.length > 0 && (
                <div className="rounded border border-red-300 bg-red-50 px-2 py-1 text-xs text-red-900">
                  <p className="font-medium">Conversions that have been run — the agent's work lives only on these branches, and goes with them:</p>
                  <ul className="list-disc pl-5">
                    {run.map((r) => (
                      <li key={`${r.repository}-${r.number}`}>
                        {r.repository} conversion {r.number}: <span className="font-mono">{r.branch}</span>, {r.agent_commits}{' '}
                        commit(s) by the agent
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div>
                <button type="button" onClick={() => setShowRows(!showRows)} className="text-xs font-medium text-neutral-700 hover:underline">
                  {rows} database row(s) in {Object.keys(plan.rows).length} table(s) {showRows ? '▾' : '▸'}
                </button>
                {showRows && (
                  <table className="mt-1 text-xs">
                    <tbody>
                      {Object.entries(plan.rows).map(([t, n]) => (
                        <tr key={t}>
                          <td className="pr-4 font-mono text-neutral-600">{t}</td>
                          <td className="text-right">{n}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div className="text-xs">
                <p className="font-medium text-neutral-700">Folders under RUNS_DIR</p>
                {plan.folders.length === 0 ? (
                  <p className="text-neutral-400">none</p>
                ) : (
                  plan.folders.map((f) => (
                    <p key={f.path} className="break-all font-mono">
                      {f.path} <span className="text-neutral-500">({f.files} files, {mb(f.bytes)})</span>
                    </p>
                  ))
                )}
              </div>
              {plan.checkouts.map((c) => (
                <div key={c.checkout} className="text-xs">
                  <p className="font-medium text-neutral-700">
                    What goes in <span className="break-all font-mono font-normal">{c.checkout}</span>
                  </p>
                  {!c.available && <p className="text-neutral-500">Not a git checkout here any more: nothing to remove in it.</p>}
                  {c.worktrees.length > 0 && <p className="text-neutral-600">{c.worktrees.length} worktree(s) the platform made</p>}
                  {c.branches.length > 0 && (
                    <ul className="ml-4 list-disc">
                      {c.branches.map((b) => (
                        <li key={b.branch}>
                          branch <span className="font-mono">{b.branch}</span> <span className="text-neutral-500">({b.source}; {b.commits_only_here} commit(s) on no other branch)</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {c.kept.map((k) => (
                    <p key={k.branch} className="text-neutral-500">
                      kept: <span className="font-mono">{k.branch}</span> — {k.why}
                    </p>
                  ))}
                  {c.available && c.worktrees.length === 0 && c.branches.length === 0 && (
                    <p className="text-neutral-400">nothing the platform created</p>
                  )}
                </div>
              ))}
              <p className="text-xs text-neutral-500">
                Kept: {plan.kept_shared}.{plan.estate_note && ` Note: ${plan.estate_note}.`}
              </p>
              <label className="block text-xs">
                <span className="text-neutral-700">
                  Type the {plan.kind}'s name, <span className="font-mono font-medium">{plan.confirm}</span>, to confirm
                </span>
                <input className={`${inputClass(false)} mt-1 font-mono`} value={typed} onChange={(e) => setTyped(e.target.value)} />
              </label>
              {error && <p className="whitespace-pre-wrap text-xs text-red-600">{error}</p>}
            </>
          )}
        </div>
        <div className="flex justify-end gap-2 border-t border-neutral-200 px-5 py-3">
          <button type="button" onClick={onClose} className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50">
            Cancel
          </button>
          <button
            type="button"
            disabled={!ready}
            onClick={submit}
            className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-40"
          >
            {busy ? 'Deleting…' : 'Delete permanently'}
          </button>
        </div>
      </div>
    </div>
  )
}
