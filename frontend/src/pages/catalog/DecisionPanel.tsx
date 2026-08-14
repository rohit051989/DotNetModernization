import { useEffect, useState } from 'react'
import { getEngagementPatternDecision, supersedeDecision } from '../../api/catalog'
import { ApiError } from '../../api/client'
import { DecisionStatusBadge } from '../../components/Badge'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { useToast } from '../../components/Toast'
import type { DecisionRecord, TargetStateSummary } from '../../types/catalog'
import { DecisionForm } from './DecisionForm'

interface DecisionPanelProps {
  patternId: string
  patternName: string
  engagementId: string
  engagementName: string
  targetStates: TargetStateSummary[]
}

export function DecisionPanel({
  patternId,
  patternName,
  engagementId,
  engagementName,
  targetStates,
}: DecisionPanelProps) {
  const { showToast } = useToast()
  const [decision, setDecision] = useState<DecisionRecord | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const [showForm, setShowForm] = useState(false)
  const [showSupersedeConfirm, setShowSupersedeConfirm] = useState(false)
  const [superseding, setSuperseding] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getEngagementPatternDecision(engagementId, patternId)
      .then((result) => {
        if (!cancelled) setDecision(result)
      })
      .catch((err) => {
        if (cancelled) return
        // 404 means "nothing decided yet" — the normal empty state, not an error.
        if (err instanceof ApiError && err.status === 404) {
          setDecision(null)
        } else {
          setError('Could not load decision.')
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [engagementId, patternId, refreshToken])

  function refresh() {
    setRefreshToken((token) => token + 1)
  }

  async function handleSupersede() {
    if (!decision) return
    setSuperseding(true)
    try {
      await supersedeDecision(decision.id)
      showToast('success', 'Decision superseded.')
      setShowSupersedeConfirm(false)
      refresh()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not supersede this decision.')
    } finally {
      setSuperseding(false)
    }
  }

  return (
    <section className="rounded border border-neutral-200 bg-white p-5">
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500">
        Decision — {engagementName}
      </h3>

      {loading && <div className="h-20 animate-pulse rounded bg-neutral-100" />}

      {!loading && error && <EmptyState title="Could not load decision" description={error} />}

      {!loading && !error && decision && (
        <div className="space-y-3">
          <DecisionStatusBadge status={decision.status} />

          <p className="text-sm text-neutral-700">
            Selected:{' '}
            {decision.selected_target_state_name ? (
              <span className="font-medium">{decision.selected_target_state_name}</span>
            ) : (
              <span className="text-neutral-400">none yet</span>
            )}
          </p>

          {decision.rationale && (
            <div>
              <p className="text-xs font-medium text-neutral-500">Rationale</p>
              <p className="text-sm text-neutral-700">{decision.rationale}</p>
            </div>
          )}

          {decision.forcing_factor && (
            <div>
              <p className="text-xs font-medium text-neutral-500">Forcing factor</p>
              <p className="text-sm text-neutral-700">{decision.forcing_factor}</p>
            </div>
          )}

          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-neutral-500">
            {decision.approver_name && (
              <span>
                Approver: {decision.approver_name}
                {decision.approver_role ? ` (${decision.approver_role})` : ''}
              </span>
            )}
            {decision.decision_date && <span>Date: {decision.decision_date}</span>}
          </div>

          <div className="flex gap-2 pt-2">
            <button
              type="button"
              onClick={() => setShowForm(true)}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Edit
            </button>
            <button
              type="button"
              onClick={() => setShowSupersedeConfirm(true)}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Supersede
            </button>
          </div>
        </div>
      )}

      {!loading && !error && !decision && (
        <EmptyState
          title="No decision recorded"
          description="Record which target state this engagement has chosen for this pattern."
          action={{ label: 'Record a decision', onClick: () => setShowForm(true) }}
        />
      )}

      {showForm && (
        <DecisionForm
          patternId={patternId}
          patternName={patternName}
          engagementId={engagementId}
          engagementName={engagementName}
          targetStates={targetStates}
          decision={decision}
          onClose={() => setShowForm(false)}
          onSaved={() => {
            setShowForm(false)
            refresh()
          }}
        />
      )}

      <ConfirmDialog
        open={showSupersedeConfirm}
        title="Supersede decision"
        message="Supersede this decision? It becomes historical, freeing this pattern for a new decision in this engagement."
        confirmLabel={superseding ? 'Superseding…' : 'Supersede'}
        onConfirm={handleSupersede}
        onCancel={() => setShowSupersedeConfirm(false)}
      />
    </section>
  )
}
