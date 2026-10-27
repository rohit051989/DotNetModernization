import { useState, type FormEvent } from 'react'
import { upsertItemDecision } from '../../api/items'
import { ApiError } from '../../api/client'
import { Drawer } from '../../components/Drawer'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Field, inputClass } from '../../components/FormField'
import { DefaultBadge, EffortBadge, FlagBadge, ImpactBadge } from '../../components/Badge'
import { useToast } from '../../components/Toast'
import type { Engagement, ForcingPerspective } from '../../types/catalog'
import {
  CONSUMER_IMPACT_RANK,
  FORCING_PERSPECTIVES,
  type CatalogItem,
  type EditableDecisionStatus,
  type EngagementDecision,
  type EngagementDecisionUpsertInput,
  type ItemResolution,
} from '../../types/items'
import { fieldErrorMap, liveResolutions, lowestImpactResolution, targetsLinux } from './itemHelpers'

const STATUSES: { value: EditableDecisionStatus; label: string }[] = [
  { value: 'pending', label: 'pending' },
  { value: 'in_review', label: 'in review' },
  { value: 'approved', label: 'approved' },
]

type TextField = 'rationale' | 'forcing_rationale' | 'evaluation_notes' | 'approver_name' | 'approver_role'
const TEXT_FIELDS: TextField[] = ['rationale', 'forcing_rationale', 'evaluation_notes', 'approver_name', 'approver_role']

interface FormState {
  resolution_id: string
  candidates_considered: string[]
  rationale: string
  forcing_perspective: ForcingPerspective | ''
  forcing_rationale: string
  evaluation_notes: string
  approver_name: string
  approver_role: string
  decision_date: string
  status: EditableDecisionStatus
}

function toFormState(decision: EngagementDecision | null, menu: ItemResolution[]): FormState {
  return {
    resolution_id: decision?.resolution_id ?? '',
    candidates_considered: decision?.candidates_considered ?? liveResolutions(menu).map((r) => r.id),
    rationale: decision?.rationale ?? '',
    forcing_perspective: decision?.forcing_perspective ?? '',
    forcing_rationale: decision?.forcing_rationale ?? '',
    evaluation_notes: decision?.evaluation_notes ?? '',
    approver_name: decision?.approver_name ?? '',
    approver_role: decision?.approver_role ?? '',
    decision_date: decision?.decision_date ?? '',
    status: decision && decision.status !== 'superseded' ? decision.status : 'pending',
  }
}

interface ItemDecisionFormProps {
  item: CatalogItem
  engagement: Engagement
  /** The item's non-deleted resolutions (active and deprecated). */
  resolutions: ItemResolution[]
  decision: EngagementDecision | null
  onClose: () => void
  onSaved: (saved: EngagementDecision) => void
}

export function ItemDecisionForm({ item, engagement, resolutions, decision, onClose, onSaved }: ItemDecisionFormProps) {
  const { showToast } = useToast()
  const menu = resolutions.filter((r) => r.deleted_at === null)
  const [form, setForm] = useState<FormState>(() => toFormState(decision, menu))
  const [dirty, setDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false)

  // Selectable: active resolutions, plus the current choice even if it has
  // since been deprecated, so an existing decision still renders.
  const selectable = menu.filter((r) => r.status === 'active' || r.id === decision?.resolution_id)
  const selected = menu.find((r) => r.id === form.resolution_id) ?? null
  const lowest = lowestImpactResolution(menu)
  const forcingRequired =
    !!selected && !!lowest && CONSUMER_IMPACT_RANK[selected.consumer_impact] > CONSUMER_IMPACT_RANK[lowest.consumer_impact]
  const linuxTargeted = targetsLinux(engagement.target_platform)
  const linuxWarning = !!selected && !selected.linux_compatible && linuxTargeted
  const approving = form.status === 'approved'
  // Back on (or level with) the lowest-impact option: a forcing justification
  // is no longer needed, so offer to shed it.
  const forcingUnneeded =
    !!selected &&
    !!lowest &&
    !forcingRequired &&
    (form.forcing_perspective !== '' || form.forcing_rationale.trim() !== '')

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }))
    setDirty(true)
  }

  function selectResolution(resolutionId: string) {
    setForm((current) => ({
      ...current,
      resolution_id: resolutionId,
      candidates_considered:
        resolutionId && !current.candidates_considered.includes(resolutionId)
          ? [...current.candidates_considered, resolutionId]
          : current.candidates_considered,
    }))
    setDirty(true)
  }

  function toggleCandidate(resolutionId: string) {
    update(
      'candidates_considered',
      form.candidates_considered.includes(resolutionId)
        ? form.candidates_considered.filter((id) => id !== resolutionId)
        : [...form.candidates_considered, resolutionId],
    )
  }

  function requestClose() {
    if (dirty) setShowDiscardConfirm(true)
    else onClose()
  }

  function buildPayload(): EngagementDecisionUpsertInput {
    // The API keeps an OMITTED field and clears one sent as explicit null.
    // So: on create, send only what is set; on update, send only what changed
    // from the saved decision — a cleared value goes as null. `status` is
    // always sent and never null.
    const payload: EngagementDecisionUpsertInput = { status: form.status }
    const orNull = (value: string) => (value.trim() === '' ? null : value.trim())
    const changed = (next: unknown, saved: unknown) => (decision ? next !== (saved ?? null) : next !== null)

    const resolutionId = form.resolution_id || null
    if (changed(resolutionId, decision?.resolution_id)) payload.resolution_id = resolutionId

    const perspective = form.forcing_perspective || null
    if (changed(perspective, decision?.forcing_perspective)) payload.forcing_perspective = perspective

    const decisionDate = form.decision_date || null
    if (changed(decisionDate, decision?.decision_date)) payload.decision_date = decisionDate

    for (const field of TEXT_FIELDS) {
      const value = orNull(form[field])
      if (changed(value, decision?.[field])) payload[field] = value
    }

    // An empty candidate list is stored as "not recorded" (null).
    const candidates = form.candidates_considered.length > 0 ? form.candidates_considered : null
    const savedCandidates = decision?.candidates_considered ?? null
    const sameCandidates =
      candidates !== null &&
      savedCandidates !== null &&
      candidates.length === savedCandidates.length &&
      candidates.every((id) => savedCandidates.includes(id))
    if (decision ? !sameCandidates && candidates !== savedCandidates : candidates !== null) {
      payload.candidates_considered = candidates
    }
    return payload
  }

  function clearForcing() {
    setForm((current) => ({ ...current, forcing_perspective: '', forcing_rationale: '' }))
    setDirty(true)
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmitting(true)
    setFieldErrors({})
    try {
      const saved = await upsertItemDecision(engagement.id, item.id, buildPayload(), decision?.version ?? 0)
      showToast(
        saved.warnings.length > 0 ? 'error' : 'success',
        saved.warnings.length > 0 ? `Decision saved with a warning: ${saved.warnings[0]}` : `Decision ${decision ? 'updated' : 'recorded'}.`,
      )
      onSaved(saved)
    } catch (err) {
      if (err instanceof ApiError) {
        setFieldErrors(fieldErrorMap(err))
        showToast('error', err.message)
      } else {
        showToast('error', 'Something went wrong. Please try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const requiredMark = (required: boolean) => (required ? ' (required to approve)' : '')
  const missing = (value: string) => approving && !value.trim()

  return (
    <>
      <Drawer title={decision ? 'Edit decision' : 'Record a decision'} onRequestClose={requestClose} wide>
        <form onSubmit={handleSubmit} className="flex h-full flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto pb-4">
            {fieldErrors.__root__ && (
              <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{fieldErrors.__root__}</p>
            )}

            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-neutral-400">Item</p>
                <p className="text-neutral-700">{item.name}</p>
              </div>
              <div>
                <p className="text-xs text-neutral-400">Engagement</p>
                <p className="text-neutral-700">
                  {engagement.client_name}
                  {engagement.target_platform && (
                    <span className="text-neutral-400"> · targets {engagement.target_platform}</span>
                  )}
                </p>
              </div>
            </div>

            <Field label={`Chosen resolution${requiredMark(approving)}`} error={fieldErrors.resolution_id}>
              <div
                className={`space-y-1.5 rounded border p-2 ${
                  fieldErrors.resolution_id || (approving && !form.resolution_id) ? 'border-red-300' : 'border-neutral-300'
                }`}
              >
                {selectable.length === 0 && (
                  <p className="text-sm text-neutral-400">
                    This item has no resolutions yet. Add them in the Master Catalog first.
                  </p>
                )}
                {selectable.map((r) => (
                  <label
                    key={r.id}
                    className={`flex cursor-pointer items-start gap-2 rounded p-2 text-sm ${
                      form.resolution_id === r.id ? 'bg-violet-50 ring-1 ring-violet-300' : 'hover:bg-neutral-50'
                    }`}
                  >
                    <input
                      type="radio"
                      name="resolution"
                      className="mt-1"
                      checked={form.resolution_id === r.id}
                      onChange={() => selectResolution(r.id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium text-neutral-800">
                        {r.name}
                        {r.status === 'deprecated' && <span className="ml-1 text-xs text-neutral-400">(deprecated)</span>}
                      </span>
                      {r.target_description && <span className="block text-xs text-neutral-500">{r.target_description}</span>}
                      <span className="mt-1 flex flex-wrap gap-1.5">
                        <ImpactBadge impact={r.consumer_impact} />
                        <EffortBadge effort={r.effort} />
                        <FlagBadge label="Linux" value={r.linux_compatible} />
                        <FlagBadge label="container" value={r.container_ready} />
                        {r.is_default && <DefaultBadge />}
                        {lowest && r.status === 'active' && r.consumer_impact === lowest.consumer_impact && (
                          <span className="text-[11px] font-medium text-emerald-700">lowest impact</span>
                        )}
                      </span>
                    </span>
                  </label>
                ))}
                {form.resolution_id && (
                  <button
                    type="button"
                    onClick={() => selectResolution('')}
                    className="text-xs text-neutral-500 hover:text-neutral-700"
                  >
                    Clear selection
                  </button>
                )}
              </div>
            </Field>

            {linuxWarning && selected && (
              <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-800">
                <p className="font-medium">Not Linux-compatible</p>
                <p className="mt-0.5">
                  {selected.name} is not Linux-compatible, but this engagement targets "{engagement.target_platform}". The
                  decision can still be saved; the server records the warning.
                </p>
              </div>
            )}

            {forcingRequired && selected && lowest && (
              <div className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                <p className="font-medium">Forcing factor needed</p>
                <p className="mt-0.5">
                  {lowest.name} has lower consumer impact ({lowest.consumer_impact}) than your selection (
                  {selected.consumer_impact}). The lowest-impact option is presumptive, so approval requires both a
                  forcing perspective and a forcing rationale.
                </p>
              </div>
            )}

            {forcingUnneeded && selected && lowest && (
              <div className="flex items-start justify-between gap-3 rounded border border-sky-300 bg-sky-50 px-3 py-2 text-sm text-sky-800">
                <div>
                  <p className="font-medium">Forcing factor no longer needed</p>
                  <p className="mt-0.5">
                    {selected.name} is not higher-impact than {lowest.name} ({lowest.consumer_impact}), so this decision
                    needs no forcing perspective or rationale. Clear them so the decision does not carry a justification
                    it no longer uses.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={clearForcing}
                  className="shrink-0 rounded border border-sky-300 bg-white px-2 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100"
                >
                  Clear both
                </button>
              </div>
            )}

            <Field label="Candidates considered (presented at decision time)" error={fieldErrors.candidates_considered}>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 rounded border border-neutral-300 p-2">
                {menu.length === 0 && <span className="text-sm text-neutral-400">No resolutions.</span>}
                {menu.map((r) => (
                  <label key={r.id} className="flex items-center gap-1.5 text-xs text-neutral-700">
                    <input
                      type="checkbox"
                      checked={form.candidates_considered.includes(r.id)}
                      onChange={() => toggleCandidate(r.id)}
                    />
                    {r.name}
                  </label>
                ))}
              </div>
            </Field>

            <Field label={`Rationale${requiredMark(approving)}`} error={fieldErrors.rationale}>
              <textarea
                value={form.rationale}
                onChange={(e) => update('rationale', e.target.value)}
                rows={3}
                className={inputClass(!!fieldErrors.rationale || missing(form.rationale))}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field
                label={forcingRequired ? 'Forcing perspective (required)' : 'Forcing perspective'}
                error={fieldErrors.forcing_perspective}
              >
                <select
                  value={form.forcing_perspective}
                  onChange={(e) => update('forcing_perspective', e.target.value as ForcingPerspective | '')}
                  className={inputClass(!!fieldErrors.forcing_perspective || (forcingRequired && !form.forcing_perspective))}
                >
                  <option value="">— none —</option>
                  {FORCING_PERSPECTIVES.map((p) => (
                    <option key={p} value={p}>
                      {p.replaceAll('_', ' ').toLowerCase()}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Decision date" error={fieldErrors.decision_date}>
                <input
                  type="date"
                  value={form.decision_date}
                  onChange={(e) => update('decision_date', e.target.value)}
                  className={inputClass(!!fieldErrors.decision_date || missing(form.decision_date))}
                />
                <div className="mt-1 flex items-center gap-2 text-[11px]">
                  {approving && <span className="text-neutral-400">Required to approve.</span>}
                  {form.decision_date && (
                    <button
                      type="button"
                      onClick={() => update('decision_date', '')}
                      className="text-neutral-500 hover:text-neutral-700"
                    >
                      Clear date
                    </button>
                  )}
                </div>
              </Field>
            </div>

            <Field
              label={forcingRequired ? 'Forcing rationale (required)' : 'Forcing rationale'}
              error={fieldErrors.forcing_rationale}
            >
              <textarea
                value={form.forcing_rationale}
                onChange={(e) => update('forcing_rationale', e.target.value)}
                rows={2}
                placeholder="Why this perspective overrides the lowest-impact option"
                className={inputClass(!!fieldErrors.forcing_rationale || (forcingRequired && !form.forcing_rationale.trim()))}
              />
            </Field>

            <Field label="Evaluation notes" error={fieldErrors.evaluation_notes}>
              <textarea
                value={form.evaluation_notes}
                onChange={(e) => update('evaluation_notes', e.target.value)}
                rows={3}
                className={inputClass(!!fieldErrors.evaluation_notes)}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label={`Approver name${requiredMark(approving)}`} error={fieldErrors.approver_name}>
                <input
                  type="text"
                  value={form.approver_name}
                  onChange={(e) => update('approver_name', e.target.value)}
                  className={inputClass(!!fieldErrors.approver_name || missing(form.approver_name))}
                />
              </Field>
              <Field label="Approver role" error={fieldErrors.approver_role}>
                <input
                  type="text"
                  value={form.approver_role}
                  onChange={(e) => update('approver_role', e.target.value)}
                  className={inputClass(!!fieldErrors.approver_role)}
                />
              </Field>
            </div>

            <Field label="Status" error={fieldErrors.status}>
              <div className="flex gap-2">
                {STATUSES.map((s) => (
                  <button
                    key={s.value}
                    type="button"
                    onClick={() => update('status', s.value)}
                    className={`rounded-full border px-3 py-1 text-xs font-medium ${
                      form.status === s.value
                        ? 'border-violet-600 bg-violet-600 text-white'
                        : 'border-neutral-300 text-neutral-600 hover:border-neutral-400'
                    }`}
                  >
                    {s.label}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-[11px] text-neutral-400">
                To replace an approved decision, supersede it from the decision panel; that keeps it in history.
              </p>
            </Field>
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
              {submitting ? 'Saving…' : decision ? 'Save decision' : 'Record decision'}
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
