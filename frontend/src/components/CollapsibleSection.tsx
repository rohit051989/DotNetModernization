import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

/** A section listing more rows than this starts collapsed the first time it is seen (release 6). */
export const LARGE_SECTION_ROWS = 50

type Persistence = 'session' | 'browser'

/** Open/closed per section. 'session': this browser tab's session only; 'browser': kept in this browser across
 * visits. Storage can be unavailable (a private window, blocked site data); the section then just starts at its
 * default every time. */
function storageOf(persistence: Persistence): Storage | null {
  try {
    return persistence === 'browser' ? window.localStorage : window.sessionStorage
  } catch {
    return null
  }
}

function readOpen(storageKey: string, persistence: Persistence): boolean | null {
  try {
    const stored = storageOf(persistence)?.getItem(storageKey) ?? null
    return stored === null ? null : stored === 'open'
  } catch {
    return null
  }
}

function writeOpen(storageKey: string, persistence: Persistence, open: boolean): void {
  try {
    storageOf(persistence)?.setItem(storageKey, open ? 'open' : 'closed')
  } catch {
    // Not remembered; harmless.
  }
}

// ---------- a group of sections: expand all, collapse all, jump links ----------

type GroupCommand = { kind: 'expand' | 'collapse' } | { kind: 'open'; id: string }

interface SectionGroupValue {
  command: (GroupCommand & { seq: number }) | null
  send: (command: GroupCommand) => void
  register: (id: string, title: string) => () => void
}

const SectionGroupContext = createContext<SectionGroupValue | null>(null)

interface SectionGroupProps {
  /** The order the jump links follow, by section id; a section not listed comes last. */
  order?: string[]
  /** Rendered above the sections: the bar with jump links and Expand all / Collapse all. */
  label: string
  /** CSS class for the bar's sticky offset, below whatever is already stuck to the top of the page. */
  barClassName?: string
  children: ReactNode
}

/** Sections inside it can be expanded or collapsed together, and reached from a row of links at the top; only the
 * sections currently shown are linked. */
export function SectionGroup({ order = [], label, barClassName = 'top-0', children }: SectionGroupProps) {
  const [command, setCommand] = useState<SectionGroupValue['command']>(null)
  const [sections, setSections] = useState<Record<string, string>>({})
  const seq = useRef(0)

  const send = useCallback((next: GroupCommand) => {
    seq.current += 1
    setCommand({ ...next, seq: seq.current })
  }, [])

  const register = useCallback((id: string, title: string) => {
    setSections((current) => (current[id] === title ? current : { ...current, [id]: title }))
    return () =>
      setSections((current) => {
        const { [id]: _removed, ...rest } = current
        return rest
      })
  }, [])

  const value = useMemo(() => ({ command, send, register }), [command, send, register])
  const ids = Object.keys(sections).sort((a, b) => rank(order, a) - rank(order, b))

  return (
    <SectionGroupContext.Provider value={value}>
      <nav
        aria-label={label}
        className={`sticky z-10 flex flex-wrap items-center gap-1 border-b border-neutral-200 bg-white/95 px-4 py-1.5 backdrop-blur ${barClassName}`}
      >
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => send({ kind: 'open', id })}
            className="whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium text-neutral-600 hover:bg-violet-50 hover:text-violet-700"
          >
            {sections[id]}
          </button>
        ))}
        <span className="ml-auto flex gap-1">
          <button type="button" onClick={() => send({ kind: 'expand' })} className="rounded px-2 py-0.5 text-xs text-violet-700 hover:bg-violet-50">
            Expand all
          </button>
          <button type="button" onClick={() => send({ kind: 'collapse' })} className="rounded px-2 py-0.5 text-xs text-violet-700 hover:bg-violet-50">
            Collapse all
          </button>
        </span>
      </nav>
      {children}
    </SectionGroupContext.Provider>
  )
}

function rank(order: string[], id: string): number {
  const at = order.indexOf(id)
  return at < 0 ? order.length : at
}

// ---------- the section ----------

interface CollapsibleSectionProps {
  /** Stable key, unique app-wide: the section's open state is remembered under it. */
  id: string
  title: string
  /** One line describing the content — always shown, so a closed section still says what is in it. */
  summary?: ReactNode
  /** Header controls shown only while open (filters, toggles). */
  actions?: ReactNode
  /** Open the first time it is seen, unless rowCount says otherwise. */
  defaultOpen?: boolean
  /** How many rows the section lists, when known: more than LARGE_SECTION_ROWS starts it collapsed the first time it
   * is seen. Undefined while loading. */
  rowCount?: number
  /** Where the open state is kept: this tab's session (the default), or this browser across visits. */
  persist?: Persistence
  /** 'nested': a section inside another, with a smaller header. */
  variant?: 'page' | 'nested'
  /** Rendered with this id so a section bar can jump to it. */
  anchorId?: string
  children: ReactNode
}

/** A bordered section whose header — title, chevron and summary — toggles its body. Inside a SectionGroup it also
 * answers Expand all, Collapse all and its jump link. */
export function CollapsibleSection({
  id,
  title,
  summary,
  actions,
  defaultOpen = true,
  rowCount,
  persist = 'session',
  variant = 'page',
  anchorId,
  children,
}: CollapsibleSectionProps) {
  const storageKey = `section:${id}`
  const [stored, setStored] = useState<boolean | null>(() => readOpen(storageKey, persist))
  const open = stored ?? (rowCount !== undefined ? rowCount <= LARGE_SECTION_ROWS : defaultOpen)
  const group = useContext(SectionGroupContext)
  const element = useRef<HTMLElement>(null)
  const handled = useRef(0)

  const set = useCallback(
    (next: boolean) => {
      setStored(next)
      writeOpen(storageKey, persist, next)
    },
    [storageKey, persist],
  )

  const register = group?.register
  useEffect(() => register?.(id, title), [register, id, title])

  const command = group?.command
  useEffect(() => {
    if (!command || command.seq === handled.current) return
    handled.current = command.seq
    if (command.kind === 'expand') set(true)
    else if (command.kind === 'collapse') set(false)
    else if (command.kind === 'open' && command.id === id) {
      set(true)
      // Instant, once the opened body is rendered: a smooth scroll is not run everywhere (a background tab, reduced motion).
      requestAnimationFrame(() => element.current?.scrollIntoView({ block: 'start' }))
    }
  }, [command, id, set])

  const nested = variant === 'nested'
  const bodyId = `${id}:body`
  return (
    <section
      id={anchorId}
      ref={element}
      className={`${nested ? 'scroll-mt-24 rounded border border-neutral-200' : 'scroll-mt-14 rounded border border-neutral-200 bg-white'} min-w-0`}
    >
      <div className={`flex flex-wrap items-center gap-x-3 gap-y-2 ${nested ? 'px-3 py-2' : 'px-4 py-3'} ${open ? 'border-b border-neutral-100' : ''}`}>
        <button
          type="button"
          onClick={() => set(!open)}
          aria-expanded={open}
          aria-controls={bodyId}
          className="flex min-w-0 flex-1 items-baseline gap-2 text-left"
        >
          <span className="flex-none text-xs text-neutral-400" aria-hidden>
            {open ? '▾' : '▸'}
          </span>
          {nested ? (
            <h3 className="flex-none text-xs font-semibold uppercase tracking-wide text-neutral-500">{title}</h3>
          ) : (
            <h2 className="flex-none text-sm font-semibold text-neutral-900">{title}</h2>
          )}
          {summary && <span className="min-w-0 truncate text-xs text-neutral-500">{summary}</span>}
        </button>
        {open && actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {open && (
        <div id={bodyId} className={nested ? 'p-3' : undefined}>
          {children}
        </div>
      )}
    </section>
  )
}

/** A single line standing for many items with nothing to show — "187 projects with no request entry points" —
 * that opens to list them. */
export function GroupedItems({ label, actions, children }: { label: string; actions?: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="rounded border border-dashed border-neutral-200">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5">
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="flex min-w-0 flex-1 items-baseline gap-2 text-left text-xs text-neutral-600">
          <span className="text-neutral-400" aria-hidden>
            {open ? '▾' : '▸'}
          </span>
          {label}
        </button>
        {actions}
      </div>
      {open && <div className="border-t border-neutral-100 px-3 py-2">{children}</div>}
    </div>
  )
}
