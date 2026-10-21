import { useMemo, useState, type ReactNode } from 'react'

/** How many items a list shows before it is asked for more (rbc-release-6). */
export const LIST_PAGE = 20

interface LimitOptions<T> {
  /** The names a person sees for an item: what the filter box matches on. With it, a list of more than LIST_PAGE
   * items gets a filter box. */
  name?: (item: T) => string | readonly (string | null | undefined)[] | null | undefined
  /** What the items are, for the filter box's label and the empty-result line: "projects", "SOAP calls". */
  noun?: string
}

interface LimitedListProps<T> extends LimitOptions<T> {
  items: readonly T[]
  /** Renders the items currently shown — a list, table rows, cards. The controls are placed after it. */
  children: (visible: T[]) => ReactNode
  /** Rendered instead of the list when there are no items at all. */
  empty?: ReactNode
  className?: string
}

function names<T>(item: T, name: NonNullable<LimitOptions<T>['name']>): string {
  const value = name(item)
  return (Array.isArray(value) ? value.filter(Boolean).join(' ') : (value ?? '')).toString().toLowerCase()
}

/**
 * The limit, for a list that cannot be wrapped in an element of its own — rows of a table body: the items to show,
 * the filter box (null when the list does not need one), the controls to place below the list (null when there are
 * none), and the line for a filter that matches nothing. LimitedList is this hook, rendered.
 */
export function useLimitedList<T>(items: readonly T[], { name, noun = 'items' }: LimitOptions<T> = {}) {
  const [shown, setShown] = useState(LIST_PAGE)
  const [filter, setFilter] = useState('')
  const filterable = name !== undefined && items.length > LIST_PAGE
  const term = filterable ? filter.trim().toLowerCase() : ''
  const matching = useMemo(() => (term && name ? items.filter((item) => names(item, name).includes(term)) : [...items]), [items, name, term])
  const visible = matching.slice(0, shown)
  const remaining = matching.length - visible.length

  const filterBox = filterable ? (
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <input
        type="search"
        value={filter}
        onChange={(e) => {
          setFilter(e.target.value)
          setShown(LIST_PAGE)
        }}
        placeholder={`Filter ${items.length} ${noun}…`}
        aria-label={`Filter ${noun}`}
        className="w-full max-w-xs rounded border border-neutral-300 px-2 py-1 text-xs focus:border-violet-400 focus:outline-none"
      />
      {term && (
        <span className="text-xs text-neutral-500">
          {matching.length} of {items.length} match
        </span>
      )}
    </div>
  ) : null

  const noMatch = matching.length === 0 && items.length > 0 ? <p className="text-xs text-neutral-400">No {noun} match “{filter.trim()}”.</p> : null

  return {
    visible,
    filterBox,
    noMatch,
    controls: (
      <ListControls
        remaining={remaining}
        expanded={shown > LIST_PAGE}
        onMore={(n) => setShown((s) => s + n)}
        onAll={() => setShown(matching.length)}
        onLess={() => setShown(LIST_PAGE)}
      />
    ),
    hasControls: remaining > 0 || shown > LIST_PAGE,
  }
}

/**
 * Any list in the UI: its first 20 items, then, below it, "+N more" when 20 or fewer remain, or "Show 20 more · N
 * remaining" with "Show all" when more do; once more are shown, "Show less" returns to 20. A list of more than 20
 * items with names gets a filter box that matches on them, so one item among hundreds is found without paging.
 * A grouped summary line passed as an item counts as one; a list nested inside an item is limited on its own.
 */
export function LimitedList<T>({ items, children, name, noun, empty, className }: LimitedListProps<T>) {
  const list = useLimitedList(items, { name, noun })
  if (items.length === 0) return <>{empty ?? null}</>
  return (
    <div className={className}>
      {list.filterBox}
      {list.noMatch ?? children(list.visible)}
      {list.controls}
    </div>
  )
}

/** The controls below a limited list. */
function ListControls({
  remaining,
  expanded,
  onMore,
  onAll,
  onLess,
}: {
  remaining: number
  expanded: boolean
  onMore: (n: number) => void
  onAll: () => void
  onLess: () => void
}) {
  if (remaining <= 0 && !expanded) return null
  const button = 'text-xs text-violet-600 hover:text-violet-800 hover:underline'
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-3">
      {remaining > 0 && remaining <= LIST_PAGE && (
        <button type="button" onClick={onAll} className={button}>
          +{remaining} more
        </button>
      )}
      {remaining > LIST_PAGE && (
        <>
          <button type="button" onClick={() => onMore(LIST_PAGE)} className={button}>
            Show {LIST_PAGE} more · {remaining} remaining
          </button>
          <button type="button" onClick={onAll} className={button}>
            Show all
          </button>
        </>
      )}
      {expanded && (
        <button type="button" onClick={onLess} className={button}>
          Show less
        </button>
      )}
    </div>
  )
}
