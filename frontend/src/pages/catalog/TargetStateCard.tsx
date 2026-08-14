import { useState } from 'react'
import type { TargetStateDetail } from '../../types/catalog'
import {
  CoverageBadge,
  EffortBadge,
  ImpactBadge,
  LiftAndShiftPill,
  RecommendedBadge,
} from '../../components/Badge'
import { Markdown } from '../../components/Markdown'

interface TargetStateCardProps {
  option: TargetStateDetail
  isPresumptive: boolean
  /** Omit to render read-only (no Edit button) — used in the client catalog view. */
  onEdit?: () => void
}

export function TargetStateCard({ option, isPresumptive, onEdit }: TargetStateCardProps) {
  const [showPlaybook, setShowPlaybook] = useState(false)

  return (
    <div className="rounded border border-neutral-200 p-4">
      {isPresumptive && (
        <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-violet-500">
          Presumptive choice
        </p>
      )}

      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-neutral-900">{option.name}</p>
          <p className="text-xs text-neutral-400">{option.target_stack}</p>
        </div>
        {onEdit && (
          <button
            type="button"
            onClick={onEdit}
            className="shrink-0 rounded border border-neutral-300 px-2.5 py-1 text-xs text-neutral-700 hover:bg-neutral-50"
          >
            Edit
          </button>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        {option.is_recommended && <RecommendedBadge />}
        <ImpactBadge impact={option.consumer_impact} />
        <EffortBadge effort={option.effort} />
        {option.is_lift_and_shift && <LiftAndShiftPill />}
      </div>

      <div className="mt-3 flex items-center gap-4 text-xs text-neutral-500">
        <CompatIndicator label="Linux" ok={option.linux_compatible} />
        <CompatIndicator label="Container-ready" ok={option.container_ready} />
      </div>

      {option.engine_support?.coverage && (
        <div className="mt-3">
          <CoverageBadge coverage={option.engine_support.coverage} />
          {option.engine_support.gaps.length > 0 && (
            <ul className="mt-1.5 list-inside list-disc text-xs text-neutral-500">
              {option.engine_support.gaps.map((gap) => (
                <li key={gap}>{gap}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {option.playbook_md && (
        <div className="mt-3 border-t border-neutral-100 pt-3">
          <button
            type="button"
            onClick={() => setShowPlaybook((value) => !value)}
            className="text-xs font-medium text-violet-600 hover:text-violet-700"
          >
            {showPlaybook ? 'Hide playbook' : 'Show playbook'}
          </button>
          {showPlaybook && (
            <div className="mt-2">
              <Markdown text={option.playbook_md} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CompatIndicator({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className={ok ? 'text-emerald-600' : 'text-neutral-300'}>{ok ? '✓' : '✕'}</span>
      {label}
    </span>
  )
}
