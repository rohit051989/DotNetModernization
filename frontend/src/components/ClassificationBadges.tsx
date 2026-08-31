import type { ClassificationStatus, ConfidenceLevel } from '../types/classification'

type BadgeTone = 'green' | 'teal' | 'amber' | 'red' | 'grey' | 'muted'

const TONE_CLASSES: Record<BadgeTone, string> = {
  green: 'bg-emerald-100 text-emerald-700',
  teal: 'bg-teal-100 text-teal-700',
  amber: 'bg-amber-100 text-amber-700',
  red: 'bg-red-100 text-red-700',
  grey: 'bg-neutral-100 text-neutral-600',
  muted: 'bg-neutral-50 text-neutral-400',
}

function Pill({ tone, children }: { tone: BadgeTone; children: React.ReactNode }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {children}
    </span>
  )
}

const STATUS_TONE: Record<ClassificationStatus, BadgeTone> = {
  MATCHED: 'green',
  MULTIPLE_MATCHES: 'teal',
  AMBIGUOUS: 'amber',
  NO_PATTERN_MATCHED: 'grey',
  INSUFFICIENT_FINGERPRINT: 'amber',
  NOT_ELIGIBLE: 'muted',
  SKIPPED: 'muted',
  CLASSIFICATION_FAILED: 'red',
}

export function ClassificationStatusBadge({ status }: { status: ClassificationStatus }) {
  return <Pill tone={STATUS_TONE[status]}>{status.replace(/_/g, ' ').toLowerCase()}</Pill>
}

const CONFIDENCE_TONE: Record<ConfidenceLevel, BadgeTone> = {
  HIGH: 'green',
  MEDIUM: 'teal',
  LOW: 'amber',
  VERY_LOW: 'grey',
}

export function ConfidenceLevelBadge({ level }: { level: ConfidenceLevel }) {
  return <Pill tone={CONFIDENCE_TONE[level]}>{level.replace('_', ' ').toLowerCase()}</Pill>
}

export function ProjectRoleBadge({ role }: { role: string }) {
  return <Pill tone="grey">{role.toLowerCase()}</Pill>
}
