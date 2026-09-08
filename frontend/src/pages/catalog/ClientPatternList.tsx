import { useEffect, useMemo, useState } from 'react'
import { listEngagementPatterns } from '../../api/catalog'
import type { EngagementPatternView } from '../../types/catalog'
import { EmptyState } from '../../components/EmptyState'
import { DeferredBadge } from '../../components/Badge'

const CATEGORIES = ['web-api', 'web-ui', 'service', 'batch', 'library', 'data-etl', 'desktop']

interface ClientPatternListProps {
  engagementId: string
  selectedPatternId: string | null
  onSelectPattern: (patternId: string) => void
  refreshToken: number
  onCatalogChanged: () => void
}

export function ClientPatternList({
  engagementId,
  selectedPatternId,
  onSelectPattern,
  refreshToken,
}: ClientPatternListProps) {
  const [patterns, setPatterns] = useState<EngagementPatternView[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const [showDeferred, setShowDeferred] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listEngagementPatterns(engagementId)
      .then((result) => {
        if (!cancelled) setPatterns(result)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load this engagement’s patterns.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [engagementId, refreshToken])

  const filteredPatterns = useMemo(() => {
    const term = searchInput.trim().toLowerCase()
    return patterns.filter((pattern) => {
      if (!showDeferred && pattern.scope_status === 'deferred') return false
      if (categoryFilter && pattern.category !== categoryFilter) return false
      if (
        term &&
        !pattern.name.toLowerCase().includes(term) &&
        !pattern.summary.toLowerCase().includes(term) &&
        !pattern.legacy_stack.toLowerCase().includes(term)
      ) {
        return false
      }
      return true
    })
  }, [patterns, categoryFilter, showDeferred, searchInput])

  useEffect(() => {
    if (!selectedPatternId && filteredPatterns.length > 0) {
      onSelectPattern(filteredPatterns[0].pattern_id)
    }
  }, [filteredPatterns, selectedPatternId, onSelectPattern])

  function clearFilters() {
    setSearchInput('')
    setCategoryFilter(null)
    setShowDeferred(true)
  }

  const filtersActive = searchInput !== '' || categoryFilter !== null || !showDeferred

  return (
    <div className="flex h-full w-[380px] shrink-0 flex-col border-r border-neutral-200 bg-white">
      <div className="border-b border-neutral-200 p-4">
        <input
          type="search"
          placeholder="Search name, summary, legacy stack…"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          className="w-full rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-900 focus:border-violet-400 focus:outline-none"
        />
        <div className="mt-3 flex flex-wrap gap-1.5">
          {CATEGORIES.map((category) => {
            const active = categoryFilter === category
            return (
              <button
                key={category}
                type="button"
                onClick={() => setCategoryFilter(active ? null : category)}
                className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
                  active
                    ? 'border-violet-600 bg-violet-600 text-white'
                    : 'border-neutral-300 text-neutral-600 hover:border-neutral-400'
                }`}
              >
                {category}
              </button>
            )
          })}
        </div>
        <label className="mt-3 flex items-center gap-2 text-xs text-neutral-500">
          <input
            type="checkbox"
            checked={showDeferred}
            onChange={(event) => setShowDeferred(event.target.checked)}
          />
          Show deferred
        </label>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="space-y-2 p-4">
            {Array.from({ length: 5 }, (_, idx) => (
              <div key={idx} className="h-14 animate-pulse rounded bg-neutral-100" />
            ))}
          </div>
        )}

        {!loading && error && <EmptyState title="Could not load patterns" description={error} />}

        {!loading && !error && filteredPatterns.length === 0 && (
          <EmptyState
            title="No patterns match"
            description="Try a different search or clear filters."
            action={filtersActive ? { label: 'Clear filters', onClick: clearFilters } : undefined}
          />
        )}

        {!loading &&
          !error &&
          filteredPatterns.map((pattern) => {
            const isSelected = pattern.pattern_id === selectedPatternId
            const isDeferred = pattern.scope_status === 'deferred'
            return (
              <button
                key={pattern.pattern_id}
                type="button"
                onClick={() => onSelectPattern(pattern.pattern_id)}
                className={`flex w-full flex-col gap-0.5 border-b border-neutral-100 px-4 py-3 text-left ${
                  isSelected ? 'bg-violet-50' : 'hover:bg-neutral-50'
                } ${isDeferred ? 'opacity-60' : ''}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-neutral-900">{pattern.name}</span>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {isDeferred && <DeferredBadge />}
                    <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 text-[11px] font-medium text-neutral-500">
                      {pattern.target_state_options.length}
                    </span>
                  </div>
                </div>
                <span className="truncate text-xs text-neutral-400">{pattern.legacy_stack}</span>
              </button>
            )
          })}
      </div>
    </div>
  )
}
