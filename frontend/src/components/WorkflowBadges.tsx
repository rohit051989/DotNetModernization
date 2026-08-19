import type { BatchStatus } from '../types/workflow'

const BATCH_STATUS_STYLES: Record<BatchStatus, string> = {
  COMPLETED: 'bg-teal-50 text-teal-700 border-teal-200',
  FAILED: 'bg-red-50 text-red-700 border-red-200',
  STARTED: 'bg-amber-50 text-amber-700 border-amber-200 animate-pulse',
  STARTING: 'bg-amber-50 text-amber-700 border-amber-200 animate-pulse',
  STOPPING: 'bg-neutral-100 text-neutral-600 border-neutral-300',
  STOPPED: 'bg-neutral-100 text-neutral-600 border-neutral-300',
  ABANDONED: 'bg-red-50 text-red-400 border-red-100',
  UNKNOWN: 'bg-neutral-100 text-neutral-500 border-neutral-200',
}

export function BatchStatusBadge({ status }: { status: BatchStatus }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${BATCH_STATUS_STYLES[status] ?? BATCH_STATUS_STYLES.UNKNOWN}`}>
      {status}
    </span>
  )
}

export function ExitStatusBadge({ status }: { status: string | null }) {
  if (!status) return <span className="text-xs text-neutral-300">—</span>
  const style =
    status === 'COMPLETED'
      ? 'bg-teal-50 text-teal-700 border-teal-200'
      : status === 'FAILED'
        ? 'bg-red-50 text-red-700 border-red-200'
        : status === 'NOT_IMPLEMENTED'
          ? 'bg-neutral-100 text-neutral-500 border-neutral-200'
          : status === 'AWAITING_APPROVAL'
            ? 'bg-amber-50 text-amber-700 border-amber-200'
            : 'bg-neutral-50 text-neutral-600 border-neutral-200'
  return <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${style}`}>{status}</span>
}

export function OwnerCodeBadge({ code }: { code: string }) {
  return (
    <span className="rounded border border-neutral-300 bg-neutral-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-neutral-500">
      {code}
    </span>
  )
}

export function StubChip() {
  return <span className="rounded bg-neutral-200 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-neutral-600">STUB</span>
}

export function ImplementationStatusChip({ status }: { status: string }) {
  if (status === 'implemented') {
    return <span className="rounded bg-teal-100 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-teal-700">IMPLEMENTED</span>
  }
  if (status === 'deprecated') {
    return <span className="rounded bg-neutral-200 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-neutral-500">DEPRECATED</span>
  }
  return <StubChip />
}

export function AdapterTypeChip({ adapterType }: { adapterType: string }) {
  return (
    <span className="rounded border border-neutral-200 bg-white px-1.5 py-0.5 font-mono text-[10px] text-neutral-500">
      {adapterType || '—'}
    </span>
  )
}

/** Part D's five skip reasons, each with its own chip label — the marker
 * itself is rendered by the caller (hollow, dashed for POLICY_DISABLED). */
const SKIP_REASON_LABELS: Record<string, string> = {
  POLICY_DISABLED: 'SKIPPED',
  CONDITION_FALSE: 'NOT APPLICABLE',
  TIER_NOT_APPLICABLE: 'TIER N/A',
  UPSTREAM_SKIPPED: 'UPSTREAM SKIPPED',
  CASCADED_POLICY: 'CASCADED',
}

export function SkipReasonChip({ reason }: { reason: string | null }) {
  const label = (reason && SKIP_REASON_LABELS[reason]) || 'SKIPPED'
  return (
    <span className="rounded border border-dashed border-violet-300 bg-violet-50 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-violet-700">
      {label}
    </span>
  )
}

export function GateChip() {
  return <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-amber-700">GATE</span>
}

export function CarriedForwardChip() {
  return (
    <span className="rounded bg-teal-100 px-1.5 py-0.5 text-[10px] font-semibold tracking-wide text-teal-700">
      CARRIED FORWARD
    </span>
  )
}
