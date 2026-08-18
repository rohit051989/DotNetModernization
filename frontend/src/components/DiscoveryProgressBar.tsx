import type { DashboardStepBrief } from '../types/dashboard'

interface Segment {
  tone: string
  title: string
}

interface DiscoveryProgressBarProps {
  steps: DashboardStepBrief[]
  stepsTotal: number
  /** Deep-links to the execution's detail — 20-WORKFLOW-OBSERVABILITY-UI.md
   * Part C: "the discovery progress bar links to the latest execution
   * detail. Each segment tooltips with its step name and status." */
  onClick?: () => void
}

function segmentFor(step: DashboardStepBrief): Segment {
  if (step.batch_status === 'FAILED') {
    return { tone: 'bg-red-500', title: `${step.display_name} — failed` }
  }
  if (step.batch_status === 'STARTED' || step.batch_status === 'STARTING') {
    return { tone: 'animate-pulse bg-amber-400', title: `${step.display_name} — running` }
  }
  if (step.exit_status === 'NOT_IMPLEMENTED') {
    return {
      tone: 'bg-[repeating-linear-gradient(45deg,#d4d4d4,#d4d4d4_3px,#e5e5e5_3px,#e5e5e5_6px)]',
      title: `${step.display_name} — not implemented yet`,
    }
  }
  if (step.exit_status === 'COMPLETED') {
    return { tone: 'bg-emerald-500', title: `${step.display_name} — completed` }
  }
  return { tone: 'bg-neutral-200', title: `${step.display_name} — ${step.batch_status.toLowerCase()}` }
}

/** One segment per lifecycle step, in flow order — completed green,
 * not-implemented grey hatched, failed red, running amber pulsing, pending
 * (not yet reached, no row at all) empty. At a glance it shows which steps
 * are real and which are stubs — see 16-DASHBOARD-SPEC.md Band 2. */
export function DiscoveryProgressBar({ steps, stepsTotal, onClick }: DiscoveryProgressBarProps) {
  const pending = Math.max(0, stepsTotal - steps.length)
  const segments: Segment[] = [
    ...steps.map(segmentFor),
    ...Array.from({ length: pending }, () => ({ tone: 'bg-neutral-100', title: 'Pending' })),
  ]
  const completedCount = steps.filter((s) => s.exit_status === 'COMPLETED').length

  const Wrapper = onClick ? 'button' : 'div'
  return (
    <Wrapper
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      className={`flex h-2 w-full min-w-[90px] gap-0.5 ${onClick ? 'cursor-pointer' : ''}`}
      role="img"
      aria-label={`${completedCount} of ${stepsTotal} steps complete`}
    >
      {segments.map((segment, index) => (
        <div key={index} title={segment.title} className={`h-full flex-1 rounded-sm ${segment.tone}`} />
      ))}
    </Wrapper>
  )
}
