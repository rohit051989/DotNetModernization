import type { CloneUrlVerification, Criticality, IngestStatus } from '../types/repositories'

const INGEST_STATUS_TONE: Record<IngestStatus, string> = {
  registered: 'bg-neutral-100 text-neutral-600',
  scanned: 'bg-teal-100 text-teal-700',
  scan_failed: 'bg-red-100 text-red-700',
  path_missing: 'bg-amber-100 text-amber-700',
}

export function IngestStatusBadge({ status }: { status: IngestStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${INGEST_STATUS_TONE[status]}`}
    >
      {status === 'path_missing' && <span aria-hidden="true">⚠</span>}
      {status.replace('_', ' ')}
    </span>
  )
}

const CRITICALITY_TONE: Record<Criticality, string> = {
  critical: 'bg-red-100 text-red-700',
  high: 'bg-amber-100 text-amber-700',
  medium: 'bg-neutral-100 text-neutral-600',
  low: 'bg-neutral-50 text-neutral-400',
}

export function CriticalityBadge({ criticality }: { criticality: Criticality }) {
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${CRITICALITY_TONE[criticality]}`}
    >
      {criticality}
    </span>
  )
}

const GIT_TONE: Record<CloneUrlVerification, string> = {
  verified: 'bg-emerald-100 text-emerald-700',
  mismatch: 'bg-amber-100 text-amber-700',
  unverifiable: 'bg-neutral-50 text-neutral-400',
}

const GIT_LABEL: Record<CloneUrlVerification, string> = {
  verified: 'verified',
  mismatch: 'mismatch',
  unverifiable: 'unverifiable',
}

export function CloneUrlVerificationBadge({ verification }: { verification: CloneUrlVerification }) {
  return (
    <span
      title={
        verification === 'mismatch'
          ? "Does not match the folder's git remote"
          : verification === 'unverifiable'
            ? 'No git remote found in this folder'
            : "Verified against the folder's git remote"
      }
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${GIT_TONE[verification]}`}
    >
      {verification === 'mismatch' && <span aria-hidden="true">⚠</span>}
      {GIT_LABEL[verification]}
    </span>
  )
}

export function RetirementBadge({ status }: { status: string }) {
  if (status === 'active') return null
  return (
    <span className="inline-flex items-center whitespace-nowrap rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-neutral-500">
      {status.replace(/_/g, ' ').toUpperCase()}
    </span>
  )
}
