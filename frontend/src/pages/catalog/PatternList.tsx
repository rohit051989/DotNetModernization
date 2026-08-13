import { useEffect, useMemo, useState } from 'react'
import { listPatterns } from '../../api/catalog'
import type { PatternSummary } from '../../types/catalog'
import { EmptyState } from '../../components/EmptyState'
import { PatternForm } from './PatternForm'

const CATEGORIES = ['web-api', 'web-ui', 'service', 'batch', 'library', 'data-etl']

interface PatternListProps {
  selectedPatternId: string | null
  onSelectPattern: (patternId: string) => void
  refreshToken: number
  onCatalogChanged: () => void
}

export function PatternList({
  selectedPatternId,
  onSelectPattern,
  refreshToken,
  onCatalogChanged,
}: PatternListProps) {
  const [patterns, setPatterns] = useState<PatternSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const [showDeprecated, setShowDeprecated] = useState(false)
  const [showCreateForm, setShowCreateForm] = useState(false)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput.trim()), 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listPatterns({ q: debouncedSearch || undefined })
      .then((result) => {
        if (!cancelled) setPatterns(result)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load patterns.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [debouncedSearch, refreshToken])

  const filteredPatterns = useMemo(
    () =>
      patterns.filter((pattern) => {
        if (!showDeprecated && pattern.status === 'deprecated') return false
        if (categoryFilter && pattern.category !== categoryFilter) return false
        return true
      }),
    [patterns, categoryFilter, showDeprecated],
  )

  useEffect(() => {
    if (!selectedPatternId && filteredPatterns.length > 0) {
      onSelectPattern(filteredPatterns[0].id)
    }
  }, [filteredPatterns, selectedPatternId, onSelectPattern])

  function clearFilters() {
    setSearchInput('')
    setCategoryFilter(null)
    setShowDeprecated(false)
  }

  const filtersActive = searchInput !== '' || categoryFilter !== null || showDeprecated

  return (
    <div className="flex h-full w-[380px] shrink-0 flex-col border-r border-neutral-200 bg-white">
      <div className="border-b border-neutral-200 p-4">
        <button
          type="button"
          onClick={() => setShowCreateForm(true)}
          className="mb-3 w-full rounded border border-dashed border-violet-300 py-2 text-sm font-medium text-violet-600 hover:border-violet-400 hover:bg-violet-50"
        >
          + New Pattern
        </button>
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
            checked={showDeprecated}
            onChange={(event) => setShowDeprecated(event.target.checked)}
          />
          Show deprecated
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
            const isSelected = pattern.id === selectedPatternId
            return (
              <button
                key={pattern.id}
                type="button"
                onClick={() => onSelectPattern(pattern.id)}
                className={`flex w-full flex-col gap-0.5 border-b border-neutral-100 px-4 py-3 text-left ${
                  isSelected ? 'bg-violet-50' : 'hover:bg-neutral-50'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-neutral-900">{pattern.name}</span>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {pattern.status !== 'active' && (
                      <span
                        title={pattern.status}
                        className={`h-1.5 w-1.5 rounded-full ${
                          pattern.status === 'draft' ? 'bg-amber-400' : 'bg-neutral-400'
                        }`}
                      />
                    )}
                    <span className="rounded-full bg-neutral-100 px-1.5 py-0.5 text-[11px] font-medium text-neutral-500">
                      {pattern.target_state_count}
                    </span>
                  </div>
                </div>
                <span className="truncate text-xs text-neutral-400">{pattern.legacy_stack}</span>
              </button>
            )
          })}
      </div>

      {showCreateForm && (
        <PatternForm
          mode="create"
          onClose={() => setShowCreateForm(false)}
          onSaved={(patternId) => {
            setShowCreateForm(false)
            onCatalogChanged()
            onSelectPattern(patternId)
          }}
        />
      )}
    </div>
  )
}
