import { useEffect, useState } from 'react'
import { getExtractorBacklog, getItemCoverage, getSignalCoverage } from '../../api/items'
import type { ExtractorBacklog, ItemCoverage, SignalCoverage } from '../../types/items'
import { EmptyState } from '../../components/EmptyState'
import { IdentifierText } from '../../components/IdentifierText'
import { ExtractorStatusBadge } from '../../components/Badge'

interface ExtractorBacklogViewProps {
  refreshToken: number
  onSelectItem: (itemId: string) => void
  /** Opens the Signals sub-tab, which lists referenced and unreferenced signals. */
  onOpenSignals: () => void
  /** Opens one signal in the Signals view. */
  onSelectSignal: (name: string) => void
}

function ItemLinks({ ids, onSelectItem }: { ids: string[]; onSelectItem: (itemId: string) => void }) {
  if (ids.length === 0) return <span className="text-neutral-300">—</span>
  return (
    <span className="flex flex-wrap gap-1">
      {ids.map((id) => (
        <button
          key={id}
          type="button"
          onClick={() => onSelectItem(id)}
          className="rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-[11px] text-violet-700 hover:bg-violet-50"
        >
          {id}
        </button>
      ))}
    </span>
  )
}

/** 28-ITEM-AND-CONVERSION-MODEL.md Part H — coverage views. The backlog is
 * the extractor build order: not-ready items' blocking signals grouped by
 * expected extractor, ordered by how many items each would unblock. */
export function ExtractorBacklogView({
  refreshToken,
  onSelectItem,
  onOpenSignals,
  onSelectSignal,
}: ExtractorBacklogViewProps) {
  const [backlog, setBacklog] = useState<ExtractorBacklog | null>(null)
  const [itemCoverage, setItemCoverage] = useState<ItemCoverage | null>(null)
  const [signalCoverage, setSignalCoverage] = useState<SignalCoverage | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([getExtractorBacklog(), getItemCoverage(), getSignalCoverage()])
      .then(([b, ic, sc]) => {
        if (cancelled) return
        setBacklog(b)
        setItemCoverage(ic)
        setSignalCoverage(sc)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load catalog coverage.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [refreshToken])

  if (loading) {
    return (
      <div className="space-y-4 p-8">
        <div className="h-16 animate-pulse rounded bg-neutral-100" />
        <div className="h-40 animate-pulse rounded bg-neutral-100" />
      </div>
    )
  }
  if (error || !backlog) return <EmptyState title="Could not load coverage" description={error ?? undefined} />

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-8">
      {itemCoverage && (
        <div className="grid grid-cols-3 gap-4">
          <div className="rounded border border-neutral-200 bg-white p-4">
            <p className="text-xs text-neutral-400">Active items ready</p>
            <p className="text-2xl font-semibold text-emerald-700">{itemCoverage.ready_count}</p>
          </div>
          <div className="rounded border border-neutral-200 bg-white p-4">
            <p className="text-xs text-neutral-400">Active items not ready</p>
            <p className={`text-2xl font-semibold ${itemCoverage.not_ready_count > 0 ? 'text-amber-700' : 'text-neutral-400'}`}>
              {itemCoverage.not_ready_count}
            </p>
          </div>
          {signalCoverage && (
            <div className="rounded border border-neutral-200 bg-white p-4">
              <p className="text-xs text-neutral-400">Ready signals referenced by an item</p>
              <p className="text-2xl font-semibold text-neutral-800">
                {signalCoverage.referenced_ready_count}
                <span className="text-sm font-normal text-neutral-400"> / {signalCoverage.ready_signal_count}</span>
              </p>
              <button
                type="button"
                onClick={onOpenSignals}
                className="mt-1 text-xs font-medium text-violet-600 hover:text-violet-700"
              >
                See unreferenced signals in Signals →
              </button>
            </div>
          )}
        </div>
      )}

      <section className="rounded border border-neutral-200 bg-white p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">Extractor backlog</h3>
        <p className="mt-0.5 text-xs text-neutral-400">
          Which extractor to build next. "Unblocks" counts items for which it is the only remaining blocker; "blocks"
          counts every item it contributes to.
        </p>
        {backlog.entries.length === 0 ? (
          <EmptyState
            title="Every catalog item is ready"
            description="No active item is waiting on a signal, so there is nothing to build. New entries appear here when an item references a signal whose extractor is not implemented yet."
          />
        ) : (
          <table className="mt-4 w-full text-left text-sm">
            <thead className="text-xs text-neutral-400">
              <tr className="border-b border-neutral-200">
                <th className="py-2 pr-3 font-medium">Expected extractor</th>
                <th className="py-2 pr-3 font-medium">Status</th>
                <th className="py-2 pr-3 font-medium">Blocking signals</th>
                <th className="py-2 pr-3 font-medium">Unblocks</th>
                <th className="py-2 font-medium">Blocks</th>
              </tr>
            </thead>
            <tbody>
              {backlog.entries.map((entry) => (
                <tr key={entry.expected_extractor ?? '(none)'} className="border-b border-neutral-100 align-top">
                  <td className="py-2 pr-3 font-mono text-xs text-neutral-800">
                    {entry.expected_extractor ?? <span className="text-red-600">no extractor declared</span>}
                  </td>
                  <td className="py-2 pr-3">
                    <ExtractorStatusBadge status={entry.extractor_status} />
                  </td>
                  <td className="py-2 pr-3">
                    <span className="flex max-w-[15rem] flex-col items-start gap-0.5 font-mono text-[11px] text-neutral-700">
                      {entry.signals.map((s) => (
                        <button
                          key={s}
                          type="button"
                          onClick={() => onSelectSignal(s)}
                          title="Open in Signals"
                          className="text-left hover:text-violet-700 hover:underline"
                        >
                          <IdentifierText name={s} />
                        </button>
                      ))}
                    </span>
                  </td>
                  <td className="py-2 pr-3">
                    <p className="mb-1 text-xs font-semibold text-neutral-700">{entry.items_unblocked.length}</p>
                    <ItemLinks ids={entry.items_unblocked} onSelectItem={onSelectItem} />
                  </td>
                  <td className="py-2">
                    <p className="mb-1 text-xs font-semibold text-neutral-700">{entry.items_blocked.length}</p>
                    <ItemLinks ids={entry.items_blocked} onSelectItem={onSelectItem} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

    </div>
  )
}
