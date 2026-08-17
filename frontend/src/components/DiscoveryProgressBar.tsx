interface Segment {
  tone: string
  title: string
}

interface DiscoveryProgressBarProps {
  stepsCompleted: number
  stepsNotImplemented: number
  stepsFailed: number
  stepsTotal: number
  isRunning: boolean
  currentStep?: string | null
}

/** One segment per lifecycle step: completed green, not-implemented grey
 * hatched, failed red, running amber pulsing, pending empty. At a glance it
 * shows which steps are real and which are stubs — see 16-DASHBOARD-SPEC.md
 * Band 2. Segment order is result-order (completed, then failed, then
 * running, then not-implemented, then pending), not necessarily lifecycle
 * order, since only aggregate counts are available here. */
export function DiscoveryProgressBar({
  stepsCompleted,
  stepsNotImplemented,
  stepsFailed,
  stepsTotal,
  isRunning,
  currentStep,
}: DiscoveryProgressBarProps) {
  const runningCount = isRunning ? 1 : 0
  const accountedFor = stepsCompleted + stepsFailed + runningCount + stepsNotImplemented
  const pending = Math.max(0, stepsTotal - accountedFor)

  const segments: Segment[] = [
    ...Array.from({ length: stepsCompleted }, () => ({ tone: 'bg-emerald-500', title: 'Completed' })),
    ...Array.from({ length: stepsFailed }, () => ({ tone: 'bg-red-500', title: 'Failed' })),
    ...Array.from({ length: runningCount }, () => ({
      tone: 'animate-pulse bg-amber-400',
      title: currentStep ? `Running: ${currentStep}` : 'Running',
    })),
    ...Array.from({ length: stepsNotImplemented }, () => ({
      tone: 'bg-[repeating-linear-gradient(45deg,#d4d4d4,#d4d4d4_3px,#e5e5e5_3px,#e5e5e5_6px)]',
      title: 'Not implemented yet',
    })),
    ...Array.from({ length: pending }, () => ({ tone: 'bg-neutral-100', title: 'Pending' })),
  ]

  return (
    <div
      className="flex h-2 w-full min-w-[90px] gap-0.5"
      role="img"
      aria-label={`${stepsCompleted} of ${stepsTotal} steps complete`}
    >
      {segments.map((segment, index) => (
        <div key={index} title={segment.title} className={`h-full flex-1 rounded-sm ${segment.tone}`} />
      ))}
    </div>
  )
}
