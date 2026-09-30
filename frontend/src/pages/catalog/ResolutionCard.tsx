import type { ReactNode } from 'react'
import type { ItemResolution } from '../../types/items'
import { DefaultBadge, DeletedBadge, EffortBadge, FlagBadge, ImpactBadge } from '../../components/Badge'

interface ResolutionCardProps {
  resolution: ItemResolution
  isLowestImpact: boolean
  /** Buttons rendered in the card header — master view only. */
  actions?: ReactNode
  /** Extra marker, e.g. "chosen by this engagement". */
  highlight?: ReactNode
}

export function ResolutionCard({ resolution, isLowestImpact, actions, highlight }: ResolutionCardProps) {
  const deleted = resolution.deleted_at !== null
  return (
    <div className={`rounded border border-neutral-200 p-4 ${deleted ? 'bg-neutral-50 opacity-70' : 'bg-white'}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-neutral-900">{resolution.name}</p>
          <p className="truncate font-mono text-[11px] text-neutral-400">{resolution.id}</p>
        </div>
        {actions && <div className="flex shrink-0 flex-wrap justify-end gap-1.5">{actions}</div>}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <ImpactBadge impact={resolution.consumer_impact} />
        <EffortBadge effort={resolution.effort} />
        {resolution.is_default && <DefaultBadge />}
        <FlagBadge label="Linux" value={resolution.linux_compatible} />
        <FlagBadge label="container" value={resolution.container_ready} />
        {isLowestImpact && !deleted && (
          <span className="text-[11px] font-medium text-emerald-700">lowest impact — presumptive</span>
        )}
        {resolution.status === 'deprecated' && (
          <span className="text-[11px] font-medium text-neutral-500">deprecated</span>
        )}
        {deleted && <DeletedBadge />}
        {highlight}
      </div>
      {resolution.description && <p className="mt-2 text-sm text-neutral-700">{resolution.description}</p>}
      {resolution.target_description && (
        <p className="mt-1.5 text-sm text-neutral-600">
          <span className="text-xs font-medium text-neutral-400">Target: </span>
          {resolution.target_description}
        </p>
      )}
      {resolution.notes && (
        <p className="mt-1.5 whitespace-pre-line text-xs text-neutral-500">
          <span className="font-medium text-neutral-400">Notes: </span>
          {resolution.notes}
        </p>
      )}
    </div>
  )
}
