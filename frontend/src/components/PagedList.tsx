import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { LIST_PAGE, ListControls } from './LimitedList'

/** One page of a list the server pages (backend app.results.paging): the items before the filter box's text
 * (`total`), those it matches (`matching`), and the page itself. */
export interface Page<T> {
  total: number
  matching: number
  offset: number
  items: T[]
}

/** Fetches `limit` items from `offset`, matching the filter box's text `q`. */
export type PageLoader<T> = (q: string, offset: number, limit: number) => Promise<Page<T>>

/** A loader over items already in hand (an execution's whole artifact), filtered and paged as the server would. */
export function localPages<T>(items: readonly T[], name: (item: T) => string | readonly (string | null | undefined)[] | null | undefined): PageLoader<T> {
  return async (q, offset, limit) => {
    const term = q.trim().toLowerCase()
    const text = (item: T) => {
      const value = name(item)
      return (Array.isArray(value) ? value.filter(Boolean).join(' ') : (value ?? '')).toString().toLowerCase()
    }
    const hit = term ? items.filter((item) => text(item).includes(term)) : [...items]
    return { total: items.length, matching: hit.length, offset, items: hit.slice(offset, offset + limit) }
  }
}

/** The most one request asks for: "Show all" asks again until it has them all. */
const MOST = 500
const DEBOUNCE_MS = 250

interface PagedOptions<T> {
  /** What the items are, for the filter box's label and the empty-result line. */
  noun?: string
  /** The first page, when it came with something else (a row's nested list): no request until more is asked for. */
  initial?: Page<T> | null
  /** False: no filter box (a list filtered by controls of its own). */
  filterable?: boolean
}

/**
 * LimitedList for a list the server pages: the first 20 items, then "+N more", "Show 20 more · N remaining" and
 * "Show all", each asking the server for what is needed; "Show less" returns to 20. A list of more than 20 gets a
 * filter box, matched by the server, so one item among thousands is found without loading them. `resetKey` names
 * what the list is of (a repository, a checkbox's state): when it changes, the list starts again.
 */
export function usePagedList<T>(load: PageLoader<T>, resetKey: string, { noun = 'items', initial = null, filterable = true }: PagedOptions<T> = {}) {
  const [items, setItems] = useState<T[]>(initial?.items ?? [])
  const [total, setTotal] = useState<number | null>(initial ? initial.total : null)
  const [matching, setMatching] = useState(initial?.matching ?? 0)
  const [filter, setFilter] = useState('')
  const [term, setTerm] = useState('')
  const [loading, setLoading] = useState(!initial)
  const [error, setError] = useState<string | null>(null)
  const loadRef = useRef(load)
  loadRef.current = load
  const request = useRef(0)
  const usedInitial = useRef(!!initial)

  /** Asks for `limit` items from `offset`; `append`: after what is shown, else in place of it. */
  const fetchPage = useCallback(async (q: string, offset: number, limit: number, append: boolean) => {
    const mine = ++request.current
    setLoading(true)
    setError(null)
    try {
      let got: T[] = []
      let page: Page<T> | null = null
      // "Show all" may need more than one request; each asks for what is left, up to MOST.
      while (got.length < limit) {
        page = await loadRef.current(q, offset + got.length, Math.min(MOST, limit - got.length))
        if (mine !== request.current) return
        got = got.concat(page.items)
        if (page.items.length === 0 || offset + got.length >= page.matching) break
      }
      if (!page) return
      setItems((current) => (append ? [...current.slice(0, offset), ...got] : got))
      setMatching(page.matching)
      setTotal(page.total)
    } catch (err) {
      if (mine === request.current) setError(err instanceof Error ? err.message : `Could not load the ${noun}.`)
    } finally {
      if (mine === request.current) setLoading(false)
    }
  }, [noun])

  // A new list (or a changed choice above it): from its first page, with no filter.
  useEffect(() => {
    setFilter('')
    setTerm('')
    if (usedInitial.current) {
      usedInitial.current = false
      return
    }
    setItems([])
    setTotal(null)
    void fetchPage('', 0, LIST_PAGE, false)
  }, [resetKey, fetchPage])

  // The filter box's text, once typing pauses.
  useEffect(() => {
    const value = filter.trim()
    if (value === term) return
    const timer = setTimeout(() => {
      setTerm(value)
      void fetchPage(value, 0, LIST_PAGE, false)
    }, DEBOUNCE_MS)
    return () => clearTimeout(timer)
  }, [filter, term, fetchPage])

  const remaining = Math.max(matching - items.length, 0)
  const showFilter = filterable && (total ?? 0) > LIST_PAGE

  const filterBox = showFilter ? (
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <input
        type="search"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        placeholder={`Filter ${total} ${noun}…`}
        aria-label={`Filter ${noun}`}
        className="w-full max-w-xs rounded border border-neutral-300 px-2 py-1 text-xs focus:border-violet-400 focus:outline-none"
      />
      {term && (
        <span className="text-xs text-neutral-500">
          {matching} of {total} match
        </span>
      )}
      {loading && <span className="text-xs text-neutral-400">Loading…</span>}
    </div>
  ) : null

  const noMatch = !loading && term && matching === 0 ? <p className="text-xs text-neutral-400">No {noun} match “{term}”.</p> : null

  return {
    items,
    total,
    loading,
    error,
    filterBox,
    noMatch,
    reload: () => void fetchPage(term, 0, Math.max(items.length, LIST_PAGE), false),
    controls: (
      <ListControls
        remaining={remaining}
        expanded={items.length > LIST_PAGE}
        onMore={(n) => void fetchPage(term, items.length, n, true)}
        onAll={() => void fetchPage(term, items.length, remaining, true)}
        onLess={() => {
          setItems((current) => current.slice(0, LIST_PAGE))
        }}
      />
    ),
  }
}

interface PagedListProps<T> extends PagedOptions<T> {
  load: PageLoader<T>
  resetKey: string
  /** Renders the items shown; the controls are placed after it. */
  children: (visible: T[]) => ReactNode
  /** Rendered instead of the list when it has no items at all. */
  empty?: ReactNode
  className?: string
}

/** A list the server pages, rendered: the filter box, the items, the controls (usePagedList). */
export function PagedList<T>({ load, resetKey, children, empty, className, ...options }: PagedListProps<T>) {
  const list = usePagedList(load, resetKey, options)
  if (list.total === null) {
    return list.error ? <p className="text-xs text-red-600">{list.error}</p> : <p className="text-xs text-neutral-400">Loading…</p>
  }
  if (list.total === 0) return <>{empty ?? null}</>
  return (
    <div className={className}>
      {list.filterBox}
      {list.error && <p className="text-xs text-red-600">{list.error}</p>}
      {list.noMatch ?? children(list.items)}
      {list.controls}
    </div>
  )
}
