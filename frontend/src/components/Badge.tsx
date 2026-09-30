import type { ReactNode } from 'react'
import type { ConsumerImpact, EffortLevel, ForcingPerspective, LifecycleStatus } from '../types/catalog'
import type { EngagementDecisionStatus, ExtractorStatus, ItemScope, ReadinessState, SignalUsage } from '../types/items'

type BadgeTone = 'green' | 'teal' | 'amber' | 'red' | 'grey' | 'muted' | 'violet' | 'indigo'

const TONE_CLASSES: Record<BadgeTone, string> = {
  green: 'bg-emerald-100 text-emerald-700',
  teal: 'bg-teal-100 text-teal-700',
  amber: 'bg-amber-100 text-amber-700',
  red: 'bg-red-100 text-red-700',
  grey: 'bg-neutral-100 text-neutral-600',
  muted: 'bg-neutral-50 text-neutral-400',
  violet: 'bg-violet-100 text-violet-700',
  indigo: 'bg-indigo-100 text-indigo-700',
}

function Badge({ tone, children, title }: { tone: BadgeTone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
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

export function ScopeBadge({ scope }: { scope: ItemScope }) {
  return <Badge tone="indigo">{scope} scope</Badge>
}

/** 25-STANDARDS-AND-VIEWPOINTS.md Part A1 — which quality concern forced a
 * higher-impact selection over the lowest-impact option. One neutral tone
 * for all seven values: this is a classification tag, not a status. */
export function PerspectiveBadge({ perspective }: { perspective: ForcingPerspective }) {
  return <Badge tone="teal">{perspective.replaceAll('_', ' ').toLowerCase()}</Badge>
}

/** 28-ITEM-AND-CONVERSION-MODEL.md Part C — two-state readiness. Computed by
 * the API; only `ready` items are evaluated by detection. */
export function ReadinessBadge({ state }: { state: ReadinessState }) {
  return state === 'ready' ? (
    <span className="inline-flex items-center whitespace-nowrap rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-emerald-700">
      READY
    </span>
  ) : (
    <span className="inline-flex items-center whitespace-nowrap rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-amber-700">
      NOT READY
    </span>
  )
}

const DECISION_TONE: Record<EngagementDecisionStatus | 'none', BadgeTone> = {
  none: 'muted',
  pending: 'grey',
  in_review: 'amber',
  approved: 'green',
  superseded: 'muted',
}

export function ItemDecisionStatusBadge({ status }: { status: EngagementDecisionStatus | 'none' }) {
  return (
    <Badge tone={DECISION_TONE[status]}>{status === 'none' ? 'no decision' : status.replace('_', ' ')}</Badge>
  )
}

export function ExtractorStatusBadge({ status }: { status: ExtractorStatus | null }) {
  if (status === null) return <Badge tone="red">not declared</Badge>
  return <Badge tone={status === 'implemented' ? 'green' : 'amber'}>{status}</Badge>
}

export function DeletedBadge() {
  return <Badge tone="red">deleted</Badge>
}

/** The master catalog's default resolution for an item — at most one. */
export function DefaultBadge() {
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-violet-700">
      DEFAULT
    </span>
  )
}

/** A yes/no property of a resolution, e.g. Linux-compatible. "No" is amber
 * rather than red: it is a trade-off to weigh, not an error. */
export function FlagBadge({ label, value }: { label: string; value: boolean }) {
  return (
    <Badge tone={value ? 'teal' : 'amber'} title={`${label}: ${value ? 'yes' : 'no'}`}>
      {value ? '✓' : '✕'} {label}
    </Badge>
  )
}

const USAGE_LABEL: Record<SignalUsage, { label: string; className: string; title: string }> = {
  match: {
    label: 'match',
    className: 'border-violet-200 bg-violet-50 text-violet-700',
    title: 'Used in match (all / any / atLeast): its presence can make the item apply.',
  },
  occurrence_source: {
    label: 'occurrence source',
    className: 'border-indigo-200 bg-indigo-50 text-indigo-700',
    title: 'The occurrence_source: each occurrence of the item is located by this signal.',
  },
  none: {
    label: 'none',
    className: 'border-neutral-300 bg-white text-neutral-600',
    title: 'Used in a none condition: its presence excludes the item.',
  },
}

/** Signal index — which part of an item's detection uses a signal. Small and
 * outlined so several fit beside an item name. */
export function SignalUsageBadge({ usage }: { usage: SignalUsage }) {
  const { label, className, title } = USAGE_LABEL[usage]
  return (
    <span
      title={title}
      className={`inline-flex items-center whitespace-nowrap rounded border px-1.5 text-[10px] font-medium leading-4 ${className}`}
    >
      {label}
    </span>
  )
}

/** A signal referenced only in `none` conditions: exclusion work, not detection. */
export function ExclusionOnlyBadge() {
  return (
    <Badge tone="amber" title="Referenced only in none conditions — exclusion work, not detection.">
      exclusion only
    </Badge>
  )
}

/** A signal name an item references that the signal registry does not have. */
export function UnregisteredBadge() {
  return (
    <Badge tone="red" title="An item references this name, but the signal registry does not have it.">
      not registered
    </Badge>
  )
}

/** Signal readiness; null means the name is not registered. */
export function SignalStateBadge({ state }: { state: ReadinessState | null }) {
  return state === null ? <UnregisteredBadge /> : <ReadinessBadge state={state} />
}
