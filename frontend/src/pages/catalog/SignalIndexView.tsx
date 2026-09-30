import { useEffect, useMemo, useRef, useState } from 'react'
import { getSignalIndex } from '../../api/items'
import type { SignalIndexEntry, SignalReference } from '../../types/items'
import { EmptyState } from '../../components/EmptyState'
import { IdentifierText } from '../../components/IdentifierText'
import { ExclusionOnlyBadge, SignalStateBadge, UnregisteredBadge } from '../../components/Badge'

type ReferencedFilter = 'all' | 'referenced' | 'unreferenced'

interface SignalIndexViewProps {
  refreshToken: number
  /** The signal to highlight and scroll to — set when arriving from an item's detail. */
  selectedSignal: string | null
  onSelectSignal: (name: string) => void
  onSelectItem: (itemId: string) => void
}

/** Match: the signal can make the item apply (all / any / atLeast). An
 * occurrence_source is always also in match, so it belongs here too. */
function isMatchReference(ref: SignalReference) {
  return ref.usages.includes('match') || ref.usages.includes('occurrence_source')
}

function ItemReferenceList({
  refs,
  column,
  onSelectItem,
}: {
  refs: SignalReference[]
  column: 'match' | 'none'
  onSelectItem: (itemId: string) => void
}) {
  if (refs.length === 0) return <span className="text-neutral-300">—</span>
  // Capped, like the Signal column: a long list wraps rather than claiming
  // the width the other columns need.
  return (
    <span className="flex max-w-[17rem] flex-wrap gap-1">
      {refs.map((ref) => (
        <span key={ref.item_id} className="inline-flex items-center gap-0.5">
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation()
              onSelectItem(ref.item_id)
            }}
            title={`${ref.item_name} (${ref.item_scope} scope${ref.item_status === 'deprecated' ? ', deprecated' : ''})`}
            className={`whitespace-nowrap rounded bg-neutral-100 px-1.5 py-0.5 font-mono text-[11px] hover:bg-violet-50 ${
              ref.item_status === 'deprecated' ? 'text-neutral-400 line-through' : 'text-violet-700'
            }`}
          >
            {ref.item_id}
          </button>
          {column === 'match' && ref.usages.includes('occurrence_source') && (
            <span
              title="Also this item's occurrence_source: each occurrence is located by this signal."
              className="rounded border border-indigo-200 bg-indigo-50 px-1 text-[9px] font-semibold leading-4 text-indigo-700"
            >
              occ
            </span>
          )}
          {column === 'match' && ref.usages.includes('none') && (
            <span
              title="This item also uses the signal in a none condition."
              className="rounded border border-neutral-300 px-1 text-[9px] font-semibold leading-4 text-neutral-500"
            >
              +none
            </span>
          )}
        </span>
      ))}
    </span>
  )
}

const FILTERS: { key: ReferencedFilter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'referenced', label: 'Referenced' },
  { key: 'unreferenced', label: 'Unreferenced' },
]

/** Every signal, with the items that reference it and how — built
 * server-side by GET /api/catalog/signal-index. The reverse direction is the
 * Signals section of an item's detail (GET /api/catalog/items/{id}/signals). */
export function SignalIndexView({ refreshToken, selectedSignal, onSelectSignal, onSelectItem }: SignalIndexViewProps) {
  const [entries, setEntries] = useState<SignalIndexEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<ReferencedFilter>('all')
  const [search, setSearch] = useState('')
  const rowRefs = useRef(new Map<string, HTMLTableRowElement>())
  // A signal selected from outside (an item's Signals section) still needs
  // scrolling to once the index has loaded — and un-hiding if filtered out.
  // Clicking a row here selects it too, but it is already on screen, so that
  // selection is not a pending focus.
  const pendingFocus = useRef<string | null>(selectedSignal)
  const selectedFromHere = useRef(false)

  useEffect(() => {
    if (selectedFromHere.current) selectedFromHere.current = false
    else pendingFocus.current = selectedSignal
  }, [selectedSignal])

  function selectRow(name: string) {
    if (name === selectedSignal) return
    selectedFromHere.current = true
    onSelectSignal(name)
  }

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getSignalIndex()
      .then((result) => {
        if (!cancelled) setEntries([...result].sort((a, b) => a.name.localeCompare(b.name)))
      })
      .catch(() => {
        if (!cancelled) setError('Could not load the signal index.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [refreshToken])

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return entries.filter((entry) => {
      if (filter === 'referenced' && !entry.referenced) return false
      if (filter === 'unreferenced' && entry.referenced) return false
      if (
        term &&
        !entry.name.toLowerCase().includes(term) &&
        !(entry.category ?? '').toLowerCase().includes(term) &&
        !(entry.type ?? '').toLowerCase().includes(term) &&
        !(entry.expected_extractor ?? '').toLowerCase().includes(term) &&
        !entry.referenced_by.some(
          (ref) => ref.item_id.toLowerCase().includes(term) || ref.item_name.toLowerCase().includes(term),
        )
      ) {
        return false
      }
      return true
    })
  }, [entries, filter, search])

  useEffect(() => {
    const target = pendingFocus.current
    if (!target || loading || entries.length === 0) return
    if (!entries.some((e) => e.name === target)) {
      pendingFocus.current = null
      return
    }
    if (!filtered.some((e) => e.name === target)) {
      // Clear the filters so the selected signal is visible; this effect
      // runs again with the wider list and scrolls.
      setFilter('all')
      setSearch('')
      return
    }
    rowRefs.current.get(target)?.scrollIntoView({ block: 'center' })
    pendingFocus.current = null
  }, [entries, filtered, loading])

  const counts = useMemo(
    () => ({
      all: entries.length,
      referenced: entries.filter((e) => e.referenced).length,
      unreferenced: entries.filter((e) => !e.referenced).length,
      exclusionOnly: entries.filter((e) => e.exclusion_only).length,
      unregistered: entries.filter((e) => !e.registered).length,
    }),
    [entries],
  )

  if (loading && entries.length === 0) {
    return (
      <div className="space-y-4 p-8">
        <div className="h-10 animate-pulse rounded bg-neutral-100" />
        <div className="h-64 animate-pulse rounded bg-neutral-100" />
      </div>
    )
  }
  if (error) return <EmptyState title="Could not load signals" description={error} />

  const selectedMissing = selectedSignal !== null && !loading && !entries.some((e) => e.name === selectedSignal)

  return (
    <div className="mx-auto max-w-screen-2xl space-y-4 p-8">
      <div>
        <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">Signals</h3>
        <p className="mt-0.5 text-xs text-neutral-400">
          Every registered signal, plus any name an item references that the registry does not have, with the items
          that use it. A ready signal no item references means either the extractor does unneeded work or an item is
          missing. {counts.exclusionOnly} signal(s) are used only in <span className="font-mono">none</span> conditions
          (exclusion work, not detection){counts.unregistered > 0 ? `; ${counts.unregistered} are not registered` : ''}.
          <span className="font-medium text-neutral-500"> Match</span> lists the items the signal can make apply (
          <span className="font-mono">all</span>, <span className="font-mono">any</span>,{' '}
          <span className="font-mono">atLeast</span>), marked{' '}
          <span className="rounded border border-indigo-200 bg-indigo-50 px-1 text-[9px] font-semibold text-indigo-700">
            occ
          </span>{' '}
          where it is also the occurrence source; <span className="font-medium text-neutral-500">None</span> lists the
          items it only excludes.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex gap-1">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              onClick={() => setFilter(f.key)}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${
                filter === f.key
                  ? 'border-violet-600 bg-violet-600 text-white'
                  : 'border-neutral-300 text-neutral-600 hover:border-neutral-400'
              }`}
            >
              {f.label} <span className={filter === f.key ? 'text-violet-200' : 'text-neutral-400'}>{counts[f.key]}</span>
            </button>
          ))}
        </div>
        <input
          type="search"
          placeholder="Search signal, type, category, extractor, item…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="w-80 rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-900 focus:border-violet-400 focus:outline-none"
        />
        <span className="text-xs text-neutral-400">{filtered.length} shown</span>
      </div>

      {selectedMissing && (
        <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
          Signal <span className="font-mono">{selectedSignal}</span> is not in the index.
        </p>
      )}

      {/* Scrolls both ways itself, so the header row and the Signal column
          both stay pinned. */}
      <section className="max-h-[calc(100vh-15rem)] overflow-auto rounded border border-neutral-200 bg-white">
        {filtered.length === 0 ? (
          <EmptyState
            title="No signals match"
            action={
              filter !== 'all' || search
                ? {
                    label: 'Clear filters',
                    onClick: () => {
                      setFilter('all')
                      setSearch('')
                    },
                  }
                : undefined
            }
          />
        ) : (
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 z-20 bg-neutral-50 text-neutral-400">
              <tr className="border-b border-neutral-200">
                <th className="sticky left-0 z-30 bg-neutral-50 px-3 py-2 font-medium">Signal</th>
                <th className="px-3 py-2 font-medium">Type</th>
                <th className="px-3 py-2 font-medium">Category</th>
                <th className="px-3 py-2 font-medium">Extractor</th>
                <th className="px-3 py-2 font-medium">State</th>
                <th className="px-3 py-2 font-medium">Introduced in</th>
                <th className="min-w-[9rem] px-3 py-2 font-medium">Match</th>
                <th className="min-w-[7rem] px-3 py-2 font-medium">None</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((entry) => {
                const isSelected = entry.name === selectedSignal
                const matchRefs = entry.referenced_by.filter(isMatchReference)
                const noneRefs = entry.referenced_by.filter((ref) => !isMatchReference(ref))
                return (
                  <tr
                    key={entry.name}
                    ref={(el) => {
                      if (el) rowRefs.current.set(entry.name, el)
                      else rowRefs.current.delete(entry.name)
                    }}
                    onClick={() => selectRow(entry.name)}
                    className={`group cursor-pointer border-b border-neutral-100 align-top ${
                      isSelected ? 'bg-violet-50 ring-1 ring-inset ring-violet-300' : 'hover:bg-neutral-50'
                    } ${entry.registered ? '' : 'bg-red-50/40'}`}
                  >
                    {/* Pinned, so a row stays identifiable when a narrow
                        window scrolls the table sideways. It needs an opaque
                        background of its own, matching the row's. */}
                    <td
                      className={`sticky left-0 z-10 px-3 py-2 ${
                        isSelected
                          ? 'bg-violet-50'
                          : entry.registered
                            ? 'bg-white group-hover:bg-neutral-50'
                            : 'bg-red-50'
                      }`}
                    >
                      {/* The inner max width caps the column (a cell's own
                          max-width is ignored): a long name wraps at its
                          underscores instead of widening the table. */}
                      <div className="min-w-[10rem] max-w-[15rem]">
                        <span
                          className={`block font-mono ${entry.registered ? 'text-neutral-800' : 'text-red-700'}`}
                          title={entry.description ?? undefined}
                        >
                          <IdentifierText name={entry.name} />
                        </span>
                        {(!entry.registered || entry.exclusion_only) && (
                          <span className="mt-1 flex flex-wrap gap-1">
                            {!entry.registered && <UnregisteredBadge />}
                            {entry.exclusion_only && <ExclusionOnlyBadge />}
                          </span>
                        )}
                        {isSelected && entry.description && (
                          <span className="mt-1 block text-[11px] text-neutral-500">{entry.description}</span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 font-mono text-neutral-600">
                      {entry.type ? <IdentifierText name={entry.type} /> : '—'}
                    </td>
                    <td className="px-3 py-2 text-neutral-600">
                      {entry.category ? <IdentifierText name={entry.category} /> : '—'}
                    </td>
                    <td className="px-3 py-2 font-mono text-neutral-600">
                      {entry.expected_extractor ? <IdentifierText name={entry.expected_extractor} /> : '—'}
                    </td>
                    <td className="px-3 py-2">
                      <SignalStateBadge state={entry.state} />
                    </td>
                    <td className="px-3 py-2 text-neutral-600">{entry.signal_introduced_in_version ?? '—'}</td>
                    <td className="px-3 py-2">
                      <ItemReferenceList refs={matchRefs} column="match" onSelectItem={onSelectItem} />
                    </td>
                    <td className="px-3 py-2">
                      <ItemReferenceList refs={noneRefs} column="none" onSelectItem={onSelectItem} />
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
