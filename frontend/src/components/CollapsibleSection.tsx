import { useState, type ReactNode } from 'react'

/** Open/closed per section, for this browser session only. Storage can be
 * unavailable (a private window, blocked site data); the section then just
 * starts at its default every time. */
function readOpen(storageKey: string, fallback: boolean): boolean {
  try {
    const stored = sessionStorage.getItem(storageKey)
    return stored === null ? fallback : stored === 'open'
  } catch {
    return fallback
  }
}

function writeOpen(storageKey: string, open: boolean): void {
  try {
    sessionStorage.setItem(storageKey, open ? 'open' : 'closed')
  } catch {
    // Not remembered; harmless.
  }
}

interface CollapsibleSectionProps {
  /** Stable key, unique app-wide: the section's open state is remembered under it. */
  id: string
  title: string
  /** One line describing the content — always shown, so a closed section still says what is in it. */
  summary?: ReactNode
  /** Header controls shown only while open (filters, toggles). */
  actions?: ReactNode
  defaultOpen?: boolean
  /** Rendered with this id so a section bar can jump to it. */
  anchorId?: string
  children: ReactNode
}

/** A bordered section whose header toggles its body. */
export function CollapsibleSection({ id, title, summary, actions, defaultOpen = true, anchorId, children }: CollapsibleSectionProps) {
  const storageKey = `section:${id}`
  const [open, setOpen] = useState(() => readOpen(storageKey, defaultOpen))

  function toggle() {
    setOpen((current) => {
      writeOpen(storageKey, !current)
      return !current
    })
  }

  return (
    <section id={anchorId} className="scroll-mt-14 rounded border border-neutral-200 bg-white">
      <div className={`flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 ${open ? 'border-b border-neutral-100' : ''}`}>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-baseline gap-2 text-left"
        >
          <span className="flex-none text-xs text-neutral-400" aria-hidden>
            {open ? '▾' : '▸'}
          </span>
          <h2 className="flex-none text-sm font-semibold text-neutral-900">{title}</h2>
          {summary && <span className="min-w-0 truncate text-xs text-neutral-500">{summary}</span>}
        </button>
        {open && actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {open && children}
    </section>
  )
}
