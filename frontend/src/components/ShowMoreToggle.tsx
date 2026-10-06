/** The "+N more" / "show fewer" control for a truncated list. A button, not a
 * tooltip: hover does not exist on touch screens, so a list hidden behind a
 * title attribute is unreachable on a phone. */
export function ShowMoreToggle({
  expanded,
  hidden,
  onToggle,
  className = '',
}: {
  expanded: boolean
  /** How many items are hidden while collapsed. */
  hidden: number
  onToggle: () => void
  className?: string
}) {
  if (hidden <= 0) return null
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={expanded}
      className={`text-violet-600 hover:text-violet-800 hover:underline ${className}`}
    >
      {expanded ? 'show fewer' : `+${hidden} more`}
    </button>
  )
}
