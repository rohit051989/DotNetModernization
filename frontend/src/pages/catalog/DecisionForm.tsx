import { useState, type FormEvent } from 'react'
import { upsertEngagementPatternDecision } from '../../api/catalog'
import { ApiError } from '../../api/client'
import { Drawer } from '../../components/Drawer'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Field, inputClass } from '../../components/FormField'
import { ImpactBadge } from '../../components/Badge'
import { useToast } from '../../components/Toast'
import type { ConsumerImpact, DecisionRecord, DecisionStatus, TargetStateSummary } from '../../types/catalog'

const STATUSES: DecisionStatus[] = ['parked', 'in_review', 'approved', 'superseded']
const IMPACT_RANK: Record<ConsumerImpact, number> = { none: 0, low: 1, medium: 2, high: 3 }

interface DecisionFormState {
  candidates_considered: string[]
  selected_target_state_id: string
  evaluation_notes: string
  rationale: string
  forcing_factor: string
  approver_name: string
  approver_role: string
  decision_date: string
  status: DecisionStatus
}

function toFormState(decision: DecisionRecord | null, targetStates: TargetStateSummary[]): DecisionFormState {
  const defaultCandidates = targetStates.filter((t) => t.status === 'active').map((t) => t.id)
  return {
    candidates_considered: decision?.candidates_considered ?? defaultCandidates,
    selected_target_state_id: decision?.selected_target_state_id ?? '',
    evaluation_notes: decision?.evaluation_notes ?? '',
    rationale: decision?.rationale ?? '',
    forcing_factor: decision?.forcing_factor ?? '',
    approver_name: decision?.approver_name ?? '',
    approver_role: decision?.approver_role ?? '',
    decision_date: decision?.decision_date ?? '',
    status: decision?.status ?? 'parked',
  }
}

interface DecisionFormProps {
  patternId: string
  patternName: string
  engagementId: string
  engagementName: string
  targetStates: TargetStateSummary[]
  decision: DecisionRecord | null
  onClose: () => void
  onSaved: () => void
}

export function DecisionForm({
  patternId,
  patternName,
  engagementId,
  engagementName,
  targetStates,
  decision,
  onClose,
  onSaved,
}: DecisionFormProps) {
  const { showToast } = useToast()
  const [form, setForm] = useState<DecisionFormState>(() => toFormState(decision, targetStates))
  const [dirty, setDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false)

  function update<K extends keyof DecisionFormState>(key: K, value: DecisionFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }))
    setDirty(true)
  }

  function toggleCandidate(targetStateId: string) {
    setForm((current) => {
      const isSelected = current.candidates_considered.includes(targetStateId)
      const candidates = isSelected
        ? current.candidates_considered.filter((id) => id !== targetStateId)
        : [...current.candidates_considered, targetStateId]
      const selected = candidates.includes(current.selected_target_state_id)
        ? current.selected_target_state_id
        : ''
      return { ...current, candidates_considered: candidates, selected_target_state_id: selected }
    })
    setDirty(true)
  }

  const candidateOptions = targetStates.filter((t) => form.candidates_considered.includes(t.id))
  const selectedOption = targetStates.find((t) => t.id === form.selected_target_state_id) ?? null
  const lowestCandidate =
    candidateOptions.length > 0
      ? candidateOptions.reduce((lowest, current) =>
          IMPACT_RANK[current.consumer_impact] < IMPACT_RANK[lowest.consumer_impact] ? current : lowest,
        )
      : null
  const forcingFactorRequired =
    !!selectedOption &&
    !!lowestCandidate &&
    IMPACT_RANK[selectedOption.consumer_impact] > IMPACT_RANK[lowestCandidate.consumer_impact]

  function requestClose() {
    if (dirty) setShowDiscardConfirm(true)
    else onClose()
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFieldErrors({})
    setFormError(null)

    const payload = {
      selected_target_state_id: form.selected_target_state_id || null,
      candidates_considered: form.candidates_considered,
      evaluation_notes: form.evaluation_notes || null,
      forcing_factor: form.forcing_factor || null,
      rationale: form.rationale || null,
      approver_name: form.approver_name || null,
      approver_role: form.approver_role || null,
      decision_date: form.decision_date || null,
      status: form.status,
    }

    try {
      await upsertEngagementPatternDecision(engagementId, patternId, payload)
      showToast('success', `Decision ${decision ? 'updated' : 'recorded'}.`)
      onSaved()
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.fieldErrors.length > 0) {
          const mapped: Record<string, string> = {}
          for (const fieldError of err.fieldErrors) mapped[fieldError.field] = fieldError.message
          setFieldErrors(mapped)
        } else {
          setFormError(err.message)
        }
        showToast('error', err.message)
      } else {
        showToast('error', 'Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <Drawer title={decision ? 'Edit decision' : 'Record a decision'} onRequestClose={requestClose}>
        <form onSubmit={handleSubmit} className="flex h-full flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto pb-4">
            {formError && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</p>}

            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-neutral-400">Pattern</p>
                <p className="text-neutral-700">{patternName}</p>
              </div>
              <div>
                <p className="text-xs text-neutral-400">Engagement</p>
                <p className="text-neutral-700">{engagementName}</p>
              </div>
            </div>

            <Field label="Candidates considered" error={fieldErrors.candidates_considered}>
              <div className="space-y-1.5 rounded border border-neutral-300 p-2">
                {targetStates.length === 0 && (
                  <p className="text-sm text-neutral-400">This pattern has no target state options yet.</p>
                )}
                {targetStates.map((option) => (
                  <label key={option.id} className="flex items-center gap-2 text-sm text-neutral-700">
                    <input
                      type="checkbox"
                      checked={form.candidates_considered.includes(option.id)}
                      onChange={() => toggleCandidate(option.id)}
                    />
                    <span className="flex-1">{option.name}</span>
                    <ImpactBadge impact={option.consumer_impact} />
                  </label>
                ))}
              </div>
            </Field>

            <Field label="Selected target state" error={fieldErrors.selected_target_state_id}>
              <select
                value={form.selected_target_state_id}
                onChange={(event) => update('selected_target_state_id', event.target.value)}
                className={inputClass(!!fieldErrors.selected_target_state_id)}
              >
                <option value="">— none —</option>
                {candidateOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Evaluation notes" error={fieldErrors.evaluation_notes}>
              <textarea
                value={form.evaluation_notes}
                onChange={(event) => update('evaluation_notes', event.target.value)}
                rows={3}
                className={inputClass(!!fieldErrors.evaluation_notes)}
              />
            </Field>

            <Field label="Rationale" error={fieldErrors.rationale}>
              <textarea
                value={form.rationale}
                onChange={(event) => update('rationale', event.target.value)}
                rows={2}
                className={inputClass(!!fieldErrors.rationale)}
              />
            </Field>

            {forcingFactorRequired && selectedOption && lowestCandidate && (
              <p className="rounded bg-amber-50 px-3 py-2 text-sm text-amber-800">
                {lowestCandidate.name} has lower consumer impact ({lowestCandidate.consumer_impact}) than
                your selection ({selectedOption.consumer_impact}). Record the forcing factor that
                justifies the higher-impact option.
              </p>
            )}

            <Field
              label={forcingFactorRequired ? 'Forcing factor (required)' : 'Forcing factor'}
              error={fieldErrors.forcing_factor}
            >
              <textarea
                value={form.forcing_factor}
                onChange={(event) => update('forcing_factor', event.target.value)}
                rows={2}
                className={inputClass(!!fieldErrors.forcing_factor || forcingFactorRequired)}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Approver name" error={fieldErrors.approver_name}>
                <input
                  type="text"
                  value={form.approver_name}
                  onChange={(event) => update('approver_name', event.target.value)}
                  className={inputClass(!!fieldErrors.approver_name)}
                />
              </Field>
              <Field label="Approver role" error={fieldErrors.approver_role}>
                <input
                  type="text"
                  value={form.approver_role}
                  onChange={(event) => update('approver_role', event.target.value)}
                  className={inputClass(!!fieldErrors.approver_role)}
                />
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Decision date" error={fieldErrors.decision_date}>
                <input
                  type="date"
                  value={form.decision_date}
                  onChange={(event) => update('decision_date', event.target.value)}
                  className={inputClass(!!fieldErrors.decision_date)}
                />
              </Field>
              <Field label="Status" error={fieldErrors.status}>
                <select
                  value={form.status}
                  onChange={(event) => update('status', event.target.value as DecisionStatus)}
                  className={inputClass(!!fieldErrors.status)}
                >
                  {STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {status.replace('_', ' ')}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </div>

          <div className="flex justify-end gap-2 border-t border-neutral-200 pt-4">
            <button
              type="button"
              onClick={requestClose}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {decision ? 'Save changes' : 'Record decision'}
            </button>
          </div>
        </form>
      </Drawer>

      <ConfirmDialog
        open={showDiscardConfirm}
        title="Discard changes?"
        message="You have unsaved changes. Closing now will discard them."
        confirmLabel="Discard"
        destructive
        onConfirm={() => {
          setShowDiscardConfirm(false)
          onClose()
        }}
        onCancel={() => setShowDiscardConfirm(false)}
      />
    </>
  )
}
