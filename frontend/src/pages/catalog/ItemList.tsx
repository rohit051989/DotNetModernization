import { useEffect, useMemo, useState } from 'react'
import { listCatalogItems, listItemDecisions } from '../../api/items'
import {
  ITEM_CATEGORIES,
  type CatalogItem,
  type EngagementDecision,
  type EngagementDecisionStatus,
  type ItemScope,
  type ReadinessState,
} from '../../types/items'
import { EmptyState } from '../../components/EmptyState'
import { CategoryBadge, DeletedBadge, ItemDecisionStatusBadge, ReadinessBadge } from '../../components/Badge'
import { ReadinessReason } from './ReadinessReason'
import { ItemForm } from './ItemForm'

const SCOPES: { scope: ItemScope; label: string; hint: string }[] = [
  { scope: 'application', label: 'Application scope', hint: 'decided once per project' },
  { scope: 'occurrence', label: 'Occurrence scope', hint: 'located per file' },
]

type DecisionFilter = 'all' | 'none' | Exclude<EngagementDecisionStatus, 'superseded'>

interface ItemListProps {
  /** null = master catalog view; otherwise the client catalog for this engagement. */
  engagementId: string | null
  selectedItemId: string | null
  onSelectItem: (itemId: string) => void
  refreshToken: number
  /** Master view only: called after a new item is created. */
  onItemCreated?: (itemId: string, warnings: string[]) => void
}

export function ItemList({ engagementId, selectedItemId, onSelectItem, refreshToken, onItemCreated }: ItemListProps) {
  const isMaster = engagementId === null
  const [items, setItems] = useState<CatalogItem[]>([])
  const [decisions, setDecisions] = useState<EngagementDecision[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState<ReadinessState | ''>('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [decisionFilter, setDecisionFilter] = useState<DecisionFilter>('all')
  const [showDeprecated, setShowDeprecated] = useState(false)
  const [showDeleted, setShowDeleted] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    Promise.all([
      listCatalogItems({ includeDeleted: isMaster && showDeleted }),
      engagementId ? listItemDecisions(engagementId) : Promise.resolve([] as EngagementDecision[]),
    ])
      .then(([itemResult, decisionResult]) => {
        if (cancelled) return
        setItems(itemResult)
        setDecisions(decisionResult)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load the catalog items.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [engagementId, isMaster, showDeleted, refreshToken])

  /** The live (non-superseded) decision per item — at most one. */
  const liveDecisionByItem = useMemo(() => {
    const map = new Map<string, EngagementDecision>()
    for (const decision of decisions) {
      if (decision.status !== 'superseded') map.set(decision.item_id, decision)
    }
    return map
  }, [decisions])

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return items.filter((item) => {
      if (!showDeprecated && item.status === 'deprecated') return false
      if (stateFilter && item.state !== stateFilter) return false
      if (categoryFilter && item.category !== categoryFilter) return false
      if (!isMaster && decisionFilter !== 'all') {
        const status = liveDecisionByItem.get(item.id)?.status ?? 'none'
        if (status !== decisionFilter) return false
      }
      if (
        term &&
        !item.name.toLowerCase().includes(term) &&
        !item.id.toLowerCase().includes(term) &&
        !(item.description ?? '').toLowerCase().includes(term)
      ) {
        return false
      }
      return true
    })
  }, [items, search, stateFilter, categoryFilter, decisionFilter, showDeprecated, isMaster, liveDecisionByItem])

  useEffect(() => {
    if (!selectedItemId && filtered.length > 0) onSelectItem(filtered[0].id)
  }, [filtered, selectedItemId, onSelectItem])

  const filtersActive =
    search !== '' || stateFilter !== '' || categoryFilter !== '' || decisionFilter !== 'all' || showDeprecated
  function clearFilters() {
    setSearch('')
    setStateFilter('')
    setCategoryFilter('')
    setDecisionFilter('all')
    setShowDeprecated(false)
  }

  const readyCount = items.filter((i) => i.deleted_at === null && i.state === 'ready').length
  const liveCount = items.filter((i) => i.deleted_at === null).length
  const approvedCount = [...liveDecisionByItem.values()].filter((d) => d.status === 'approved').length

  const selectClass =
    'rounded border border-neutral-300 px-2 py-1 text-xs text-neutral-700 focus:border-violet-400 focus:outline-none'

  return (
    <div className="flex h-full w-[400px] shrink-0 flex-col border-r border-neutral-200 bg-white">
      <div className="border-b border-neutral-200 p-4">
        {isMaster && (
          // TODO: gate behind an admin check once auth exists (04-FRONTEND-SPEC.md,
          // "Future: access control") — creating an item is a master-scoped mutation.
          <button
            type="button"
            onClick={() => setShowCreateForm(true)}
            className="mb-3 w-full rounded border border-dashed border-violet-300 py-2 text-sm font-medium text-violet-600 hover:border-violet-400 hover:bg-violet-50"
          >
            + New Item
          </button>
        )}
        <input
          type="search"
          placeholder="Search name, id, description…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="w-full rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-900 focus:border-violet-400 focus:outline-none"
        />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <select
            value={stateFilter}
            onChange={(event) => setStateFilter(event.target.value as ReadinessState | '')}
            className={selectClass}
            aria-label="Readiness"
          >
            <option value="">Any readiness</option>
            <option value="ready">Ready</option>
            <option value="not_ready">Not ready</option>
          </select>
          <select
            value={categoryFilter}
            onChange={(event) => setCategoryFilter(event.target.value)}
            className={selectClass}
            aria-label="Category"
          >
            <option value="">Any category</option>
            {ITEM_CATEGORIES.map((category) => (
              <option key={category} value={category}>
                {category}
              </option>
            ))}
          </select>
          {!isMaster && (
            <select
              value={decisionFilter}
              onChange={(event) => setDecisionFilter(event.target.value as DecisionFilter)}
              className={selectClass}
              aria-label="Decision status"
            >
              <option value="all">Any decision</option>
              <option value="none">No decision</option>
              <option value="pending">Pending</option>
              <option value="in_review">In review</option>
              <option value="approved">Approved</option>
            </select>
          )}
        </div>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-neutral-500">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={showDeprecated} onChange={(e) => setShowDeprecated(e.target.checked)} />
            Show deprecated
          </label>
          {isMaster && (
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={showDeleted} onChange={(e) => setShowDeleted(e.target.checked)} />
              Show deleted
            </label>
          )}
        </div>
        {!loading && !error && (
          <p className="mt-3 text-xs text-neutral-400">
            {readyCount} of {liveCount} item(s) ready
            {!isMaster && ` · ${approvedCount} approved decision(s)`}
          </p>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }, (_, idx) => (
              <div key={idx} className="h-14 animate-pulse rounded bg-neutral-100" />
            ))}
          </div>
        )}

        {!loading && error && <EmptyState title="Could not load items" description={error} />}

        {!loading && !error && filtered.length === 0 && (
          <EmptyState
            title={items.length === 0 ? 'No catalog items yet' : 'No items match'}
            description={items.length === 0 ? undefined : 'Try different filters.'}
            action={filtersActive ? { label: 'Clear filters', onClick: clearFilters } : undefined}
          />
        )}

        {!loading &&
          !error &&
          SCOPES.map(({ scope, label, hint }) => {
            const group = filtered.filter((item) => item.scope === scope)
            if (group.length === 0) return null
            return (
              <div key={scope}>
                <div className="sticky top-0 z-10 border-b border-neutral-200 bg-neutral-50 px-4 py-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                  {label} <span className="font-normal normal-case tracking-normal text-neutral-400">· {hint} · {group.length}</span>
                </div>
                {group.map((item) => {
                  const decision = liveDecisionByItem.get(item.id)
                  const isSelected = item.id === selectedItemId
                  return (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => onSelectItem(item.id)}
                      className={`flex w-full flex-col border-b border-neutral-100 px-4 py-2.5 text-left ${
                        isSelected ? 'bg-violet-50' : 'hover:bg-neutral-50'
                      } ${item.deleted_at ? 'opacity-60' : ''}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="text-sm font-medium text-neutral-900">{item.name}</span>
                        <ReadinessBadge state={item.state} />
                      </div>
                      <span className="truncate font-mono text-[11px] text-neutral-400">{item.id}</span>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <CategoryBadge category={item.category} />
                        {item.status === 'deprecated' && (
                          <span className="text-[11px] font-medium text-neutral-500">deprecated</span>
                        )}
                        {item.deleted_at && <DeletedBadge />}
                        {!isMaster && <ItemDecisionStatusBadge status={decision?.status ?? 'none'} />}
                      </div>
                      {!isMaster && decision?.resolution_name && (
                        <span className="mt-1 truncate text-xs text-neutral-600">→ {decision.resolution_name}</span>
                      )}
                      {isMaster && <ReadinessReason item={item} compact />}
                    </button>
                  )
                })}
              </div>
            )
          })}
      </div>

      {showCreateForm && (
        <ItemForm
          mode="create"
          onClose={() => setShowCreateForm(false)}
          onSaved={(itemId, warnings) => {
            setShowCreateForm(false)
            onItemCreated?.(itemId, warnings)
          }}
        />
      )}
    </div>
  )
}
