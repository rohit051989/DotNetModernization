import type { ReactNode } from 'react'
import type {
  ConsumerImpact,
  DecisionStatus,
  EffortLevel,
  EngineCoverage,
  LifecycleStatus,
} from '../types/catalog'

type BadgeTone = 'green' | 'teal' | 'amber' | 'red' | 'grey' | 'muted'

const TONE_CLASSES: Record<BadgeTone, string> = {
  green: 'bg-emerald-100 text-emerald-700',
  teal: 'bg-teal-100 text-teal-700',
  amber: 'bg-amber-100 text-amber-700',
  red: 'bg-red-100 text-red-700',
  grey: 'bg-neutral-100 text-neutral-600',
  muted: 'bg-neutral-50 text-neutral-400',
}

function Badge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  )
}

const IMPACT_TONE: Record<ConsumerImpact, BadgeTone> = {
  none: 'green',
  low: 'teal',
  medium: 'amber',
  high: 'red',
}

export function ImpactBadge({ impact }: { impact: ConsumerImpact }) {
  return <Badge tone={IMPACT_TONE[impact]}>impact: {impact}</Badge>
}

export function EffortBadge({ effort }: { effort: EffortLevel }) {
  return <Badge tone="grey">effort: {effort}</Badge>
}

const COVERAGE_TONE: Record<EngineCoverage, BadgeTone> = {
  strong: 'green',
  partial: 'amber',
  none: 'red',
}

export function CoverageBadge({ coverage }: { coverage: EngineCoverage }) {
  return <Badge tone={COVERAGE_TONE[coverage]}>engine coverage: {coverage}</Badge>
}

const STATUS_TONE: Record<LifecycleStatus, BadgeTone> = {
  draft: 'amber',
  active: 'green',
  deprecated: 'grey',
}

export function StatusBadge({ status }: { status: LifecycleStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{status}</Badge>
}

export function CategoryBadge({ category }: { category: string }) {
  return <Badge tone="grey">{category}</Badge>
}

const DECISION_STATUS_TONE: Record<DecisionStatus, BadgeTone> = {
  parked: 'grey',
  in_review: 'amber',
  approved: 'green',
  superseded: 'muted',
}

export function DecisionStatusBadge({ status }: { status: DecisionStatus }) {
  return <Badge tone={DECISION_STATUS_TONE[status]}>{status.replace('_', ' ')}</Badge>
}

export function LiftAndShiftPill() {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-violet-700">
      LIFT &amp; SHIFT
    </span>
  )
}

/** Editorial marker, deliberately distinct from the impact/effort badges — this
 * is the master catalog's own recommendation, not a status. */
export function RecommendedBadge() {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-full bg-indigo-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-indigo-700">
      RECOMMENDED
    </span>
  )
}

export function DeferredBadge() {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-neutral-500">
      DEFERRED
    </span>
  )
}
