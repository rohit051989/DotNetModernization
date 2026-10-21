import type { ReactNode } from 'react'
import type { DerivationAction, ItemResolution } from '../../types/items'
import { DefaultBadge, DeletedBadge, EffortBadge, FlagBadge, ImpactBadge } from '../../components/Badge'
import { LimitedList } from '../../components/LimitedList'

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
      {(resolution.derivations ?? []).length > 0 && (
        <div className="mt-2 rounded border border-violet-100 bg-violet-50/40 px-2 py-1.5">
          <p className="text-[11px] font-medium uppercase tracking-wide text-violet-700">Choosing this derives</p>
          <LimitedList
            items={resolution.derivations ?? []}
            name={(d) => [d.dependent_item_id, d.dependent_resolution_id]}
            noun="derivations"
            className="mt-1"
          >
            {(visible) => (
              <ul className="space-y-1">
                {visible.map((d) => (
                  <li key={d.dependent_item_id} className="text-xs text-neutral-700">
                    <span className="font-mono text-neutral-800">{d.dependent_item_id}</span>{' '}
                    <span className={`rounded border px-1 text-[10px] ${ACTION_STYLE[d.action]}`}>{ACTION_LABEL[d.action]}</span>
                    {d.dependent_resolution_id && <span className="font-mono text-neutral-600"> → {d.dependent_resolution_id}</span>}
                    {d.applies_to === 'internal_clients' && <span className="text-neutral-500"> (internal clients only)</span>}
                    <span className="block text-neutral-500">{d.reason}</span>
                  </li>
                ))}
              </ul>
            )}
          </LimitedList>
        </div>
      )}
    </div>
  )
}

const ACTION_LABEL: Record<DerivationAction, string> = {
  derive: 'derived',
  not_derived: 'not derived',
  subsume: 'subsumed',
  not_subsumed: 'not subsumed',
}

const ACTION_STYLE: Record<DerivationAction, string> = {
  derive: 'border-violet-200 bg-white text-violet-800',
  subsume: 'border-violet-200 bg-white text-violet-800',
  not_derived: 'border-neutral-200 bg-white text-neutral-600',
  not_subsumed: 'border-neutral-200 bg-white text-neutral-600',
}
