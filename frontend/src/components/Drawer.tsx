import type { ReactNode } from 'react'

interface DrawerProps {
  title: string
  onRequestClose: () => void
  children: ReactNode
  /** Wider panel for forms with code-like fields (e.g. a JSON editor). */
  wide?: boolean
}

/** A right-side slide-over. Mount/unmount controls visibility — the parent
 * decides whether it's safe to close (e.g. confirming a dirty form first). */
export function Drawer({ title, onRequestClose, children, wide = false }: DrawerProps) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-neutral-900/30" onClick={onRequestClose} aria-hidden="true" />
      <div className={`relative flex h-full w-full ${wide ? 'max-w-2xl' : 'max-w-lg'} flex-col bg-white shadow-xl`}>
        <div className="flex items-center justify-between border-b border-neutral-200 px-5 py-4">
          <h2 className="text-base font-semibold text-neutral-900">{title}</h2>
          <button
            type="button"
            onClick={onRequestClose}
            aria-label="Close"
            className="text-neutral-400 hover:text-neutral-600"
          >
            ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>
  )
}
