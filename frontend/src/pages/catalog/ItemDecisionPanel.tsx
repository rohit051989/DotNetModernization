import { useEffect, useState } from 'react'
import { listItemDecisions, supersedeItemDecision } from '../../api/items'
import { ApiError } from '../../api/client'
import type { Engagement } from '../../types/catalog'
import type { CatalogItem, EngagementDecision, ItemResolution } from '../../types/items'
import { ItemDecisionStatusBadge, PerspectiveBadge } from '../../components/Badge'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { useToast } from '../../components/Toast'
import { ItemDecisionForm } from './ItemDecisionForm'
import { formatDate } from './itemHelpers'

interface ItemDecisionPanelProps {
  item: CatalogItem
  engagement: Engagement
  resolutions: ItemResolution[]
  refreshToken: number
  onDecisionChanged: () => void
}

function Detail({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-xs text-neutral-400">{label}</dt>
      <dd className="whitespace-pre-line text-sm text-neutral-700">{value || '—'}</dd>
    </div>
  )
}

function DecisionBody({ decision, resolutions }: { decision: EngagementDecision; resolutions: ItemResolution[] }) {
  const nameOf = (id: string) => resolutions.find((r) => r.id === id)?.name ?? id
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-3">
      <div className="col-span-2">
        <dt className="text-xs text-neutral-400">Chosen resolution</dt>
        <dd className="text-sm font-medium text-neutral-800">
          {decision.resolution_name ?? (decision.resolution_id ? decision.resolution_id : '— not selected yet —')}
        </dd>
      </div>
      {decision.needs_review && (
        <div className="col-span-2 rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-xs text-amber-900">
          <p className="font-semibold">Needs review</p>
          <p>{decision.review_note}</p>
        </div>
      )}
      {(decision.derived_from || (decision.followers ?? []).length > 0) && (
        <div className="col-span-2 rounded border border-violet-100 bg-violet-50/50 px-2 py-1.5 text-xs">
          {decision.derived_from && (
            <p className={decision.source === 'derived' ? 'text-violet-800' : 'text-amber-800'}>
              {decision.source === 'derived'
                ? `Derived from the ${decision.derived_from.item_name} decision (${decision.derived_from.resolution_name ?? '—'}). Recording a decision here overrides it.`
                : decision.derived_from.would_derive
                  ? `Overridden by hand: the ${decision.derived_from.item_name} decision (${decision.derived_from.resolution_name ?? '—'}) would give ${decision.derived_from.would_derive}.`
                  : `Overridden by hand, against the ${decision.derived_from.item_name} decision.`}
              {decision.source === 'derived' && decision.derived_from.derivation_reason && (
                <span className="block text-neutral-500">{decision.derived_from.derivation_reason}</span>
              )}
            </p>
          )}
          {(decision.followers ?? []).length > 0 && (
            <p className="text-neutral-700">
              Drives:{' '}
              {decision.followers!
                .map((f) => `${f.item_name} → ${f.resolution_name ?? '—'} (${f.source === 'derived' ? 'derived' : f.needs_review ? 'overridden by hand, needs review' : 'overridden by hand'})`)
                .join('; ')}
            </p>
          )}
        </div>
      )}
      <div className="col-span-2">
        <dt className="text-xs text-neutral-400">Candidates considered</dt>
        <dd className="text-sm text-neutral-700">
          {decision.candidates_considered && decision.candidates_considered.length > 0
            ? decision.candidates_considered.map(nameOf).join(' · ')
            : '—'}
        </dd>
      </div>
      <div className="col-span-2">
        <Detail label="Rationale" value={decision.rationale} />
      </div>
      <div>
        <dt className="text-xs text-neutral-400">Forcing perspective</dt>
        <dd className="text-sm">
          {decision.forcing_perspective ? <PerspectiveBadge perspective={decision.forcing_perspective} /> : '—'}
        </dd>
      </div>
      <Detail label="Forcing rationale" value={decision.forcing_rationale} />
      <div className="col-span-2">
        <Detail label="Evaluation notes" value={decision.evaluation_notes} />
      </div>
      <Detail
        label="Approver"
        value={decision.approver_name ? `${decision.approver_name}${decision.approver_role ? ` (${decision.approver_role})` : ''}` : null}
      />
      <Detail label="Decision date" value={decision.decision_date} />
    </dl>
  )
}

/** Client-scoped: writes `engagement_decisions` only (CLAUDE.md rule 9). This
 * replaces the old lifecycle steps 13–15 — 28-ITEM-AND-CONVERSION-MODEL.md
 * Part F. */
export function ItemDecisionPanel({ item, engagement, resolutions, refreshToken, onDecisionChanged }: ItemDecisionPanelProps) {
  const { showToast } = useToast()
  const [decisions, setDecisions] = useState<EngagementDecision[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [showSupersedeConfirm, setShowSupersedeConfirm] = useState(false)
  const [superseding, setSuperseding] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [localToken, setLocalToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    listItemDecisions(engagement.id)
      .then((result) => {
        if (!cancelled) setDecisions(result.filter((d) => d.item_id === item.id))
      })
      .catch(() => {
        if (!cancelled) setError('Could not load this engagement’s decision.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [engagement.id, item.id, refreshToken, localToken])

  const live = decisions.find((d) => d.status !== 'superseded') ?? null
  const history = decisions
    .filter((d) => d.status === 'superseded')
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at))

  function changed() {
    setLocalToken((t) => t + 1)
    onDecisionChanged()
  }

  async function handleSupersede() {
    if (!live) return
    setSuperseding(true)
    try {
      await supersedeItemDecision(live.id)
      showToast('success', 'Decision superseded. Record a new one when ready.')
      setShowSupersedeConfirm(false)
      changed()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not supersede this decision.')
    } finally {
      setSuperseding(false)
    }
  }

  return (
    <section className="rounded border-2 border-violet-200 bg-white p-5">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold uppercase tracking-wide text-violet-700">
            Decision — {engagement.client_name}
          </h3>
          <p className="mt-0.5 text-xs text-neutral-400">
            What this engagement chose for this item. Captured upfront, before repository ingestion.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          {live && (
            <button
              type="button"
              onClick={() => setShowSupersedeConfirm(true)}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Supersede
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowForm(true)}
            disabled={loading}
            className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
          >
            {live ? 'Edit decision' : 'Record decision'}
          </button>
        </div>
      </div>

      {loading && <div className="h-20 animate-pulse rounded bg-neutral-100" />}
      {!loading && error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && live && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-neutral-400">
            <ItemDecisionStatusBadge status={live.status} />
            <span>updated {formatDate(live.updated_at)}</span>
          </div>
          {live.warnings.length > 0 && (
            <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
              {live.warnings.map((w, i) => (
                <p key={i}>⚠ {w}</p>
              ))}
            </div>
          )}
          <DecisionBody decision={live} resolutions={resolutions} />
        </div>
      )}

      {!loading && !error && !live && (
        <p className="rounded bg-neutral-50 px-3 py-3 text-sm text-neutral-500">
          No decision recorded yet for this engagement.
          {history.length > 0 && ' Earlier decisions were superseded — see history below.'}
        </p>
      )}

      {!loading && history.length > 0 && (
        <div className="mt-4 border-t border-neutral-100 pt-3">
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="text-xs font-medium text-violet-600 hover:text-violet-700"
          >
            {showHistory ? 'Hide' : 'Show'} decision history ({history.length} superseded)
          </button>
          {showHistory && (
            <ul className="mt-3 space-y-3">
              {history.map((d) => (
                <li key={d.id} className="rounded border border-neutral-200 bg-neutral-50 p-3 opacity-80">
                  <div className="mb-2 flex items-center gap-2 text-xs text-neutral-400">
                    <ItemDecisionStatusBadge status={d.status} />
                    <span>
                      created {formatDate(d.created_at)} · superseded {formatDate(d.updated_at)}
                    </span>
                  </div>
                  <DecisionBody decision={d} resolutions={resolutions} />
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {showForm && (
        <ItemDecisionForm
          item={item}
          engagement={engagement}
          resolutions={resolutions}
          decision={live}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            changed()
          }}
        />
      )}

      <ConfirmDialog
        open={showSupersedeConfirm}
        title="Supersede decision"
        message="Supersede this decision? It moves to history and the item has no live decision until a new one is recorded."
        confirmLabel={superseding ? 'Superseding…' : 'Supersede'}
        destructive
        onConfirm={handleSupersede}
        onCancel={() => setShowSupersedeConfirm(false)}
      />
    </section>
  )
}
