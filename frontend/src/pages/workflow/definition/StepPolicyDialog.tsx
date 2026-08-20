import { useState } from 'react'
import { ApiError } from '../../../api/client'
import {
  deleteGlobalStepPolicy,
  deleteStepPolicy,
  setGlobalStepPolicy,
  setStepPolicy,
} from '../../../api/policies'
import type { PolicyConflictDetail, StepPolicy } from '../../../types/policy'

export type PolicyScope = 'global' | { engagementId: string }

interface StepPolicyDialogProps {
  scope: PolicyScope
  stepName: string
  displayName: string
  /** The step's currently *effective* state — enabled/source/reason as
   * resolved across whichever layers apply. */
  effectiveEnabled: boolean
  /** This scope's own row, if one exists — determines whether the dialog's
   * action creates a new row (none exists yet) or reverts the existing one
   * (23-WORKFLOW-ADMINISTRATION.md Part A precedence: engagement beats
   * global beats default; the same "does a row exist at this scope" check
   * drives both the global editor and the engagement editor). */
  ownRow: StepPolicy | null
  onClose: () => void
  onChanged: () => void
}

/** The toggle dialog from a flow card or a policy table row —
 * 22-STEP-SEQUENCING-AND-POLICY.md Part E, extended across layers by
 * 23-WORKFLOW-ADMINISTRATION.md Part A. Two modes, uniform across scopes:
 *
 * - **create** (no row at this scope yet): the action always flips the
 *   current effective state. At default/global-enabled, that's "Disable".
 *   At engagement scope with a global disable in effect, that's "Override
 *   for this engagement" — an explicit enable, reason still required.
 * - **revert** (a row exists at this scope): the action deletes it,
 *   falling through to whatever the next layer down says. On the
 *   engagement layer that may fall back to a global disable, not to
 *   enabled — the dialog says so.
 *
 * On toggle off (create, disabling), a required-reason dialog. If the API
 * returns `POLICY_ORPHANS_DEPENDENTS`, show the dependent steps and offer an
 * explicit "also disable these" confirmation which resubmits with
 * `cascade: true`. The revert direction mirrors this with
 * `POLICY_REVERT_ORPHANS_STEP` and `force`. */
export function StepPolicyDialog({
  scope,
  stepName,
  displayName,
  effectiveEnabled,
  ownRow,
  onClose,
  onChanged,
}: StepPolicyDialogProps) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<PolicyConflictDetail | null>(null)

  const isGlobal = scope === 'global'
  const scopeLabel = isGlobal ? 'globally' : 'for this engagement'
  const mode: 'create' | 'revert' = ownRow ? 'revert' : 'create'
  const desiredEnabled = !effectiveEnabled

  function conflictDetails(err: ApiError): PolicyConflictDetail | null {
    const detail = err.rawDetail[0] as PolicyConflictDetail | undefined
    return detail && typeof detail === 'object' && 'code' in detail ? detail : null
  }

  async function handleCreate(cascade: boolean) {
    setBusy(true)
    setFormError(null)
    try {
      const payload = { step_name: stepName, enabled: desiredEnabled, reason, cascade }
      if (isGlobal) await setGlobalStepPolicy(payload)
      else await setStepPolicy(scope.engagementId, payload)
      onChanged()
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const detail = conflictDetails(err)
        if (detail) {
          setConflict(detail)
          return
        }
      }
      setFormError(err instanceof ApiError ? err.message : 'Could not save this policy.')
    } finally {
      setBusy(false)
    }
  }

  async function handleRevert(force: boolean) {
    setBusy(true)
    setFormError(null)
    try {
      if (isGlobal) await deleteGlobalStepPolicy(stepName, force)
      else await deleteStepPolicy(scope.engagementId, stepName, force)
      onChanged()
      onClose()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const detail = conflictDetails(err)
        if (detail) {
          setConflict(detail)
          return
        }
      }
      setFormError(err instanceof ApiError ? err.message : 'Could not revert this policy.')
    } finally {
      setBusy(false)
    }
  }

  const title =
    mode === 'create'
      ? desiredEnabled
        ? `Override ${displayName} for this engagement`
        : `Disable ${displayName} ${scopeLabel}`
      : ownRow?.enabled
        ? `Remove this ${isGlobal ? 'global' : 'engagement'} override`
        : `Re-enable ${displayName} ${scopeLabel}`

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-neutral-900/30" onClick={onClose} aria-hidden="true" />
      <div className="relative w-full max-w-md rounded bg-white p-5 shadow-xl">
        <h3 className="text-sm font-semibold text-neutral-900">{title}</h3>

        {mode === 'revert' && ownRow && (
          <p className="mt-2 text-sm text-neutral-600">
            Currently {ownRow.enabled ? 'enabled' : 'disabled'}
            {ownRow.reason ? `: ${ownRow.reason}` : '.'} Reverting deletes this policy row — the step falls back to{' '}
            {isGlobal ? 'enabled by default' : 'whatever the global layer (or default) says'}.
          </p>
        )}

        {conflict ? (
          <div className="mt-3 space-y-3">
            <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
              <p>{conflict.message}</p>
              <ul className="mt-2 list-inside list-disc font-medium">
                {(conflict.dependent_steps ?? conflict.blocking_steps ?? []).map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-amber-700">{conflict.resolution}</p>
            </div>
            {formError && <p className="text-sm text-red-600">{formError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                Cancel
              </button>
              {conflict.code === 'POLICY_ORPHANS_DEPENDENTS' ? (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleCreate(true)}
                  className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {busy ? 'Disabling…' : 'Also disable these'}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleRevert(true)}
                  className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
                >
                  {busy ? 'Re-enabling…' : 'Re-enable anyway'}
                </button>
              )}
            </div>
          </div>
        ) : mode === 'create' ? (
          <div className="mt-3 space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">Reason *</label>
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={3}
                className="w-full rounded border border-neutral-300 px-3 py-1.5 text-sm focus:border-violet-400 focus:outline-none"
                placeholder={
                  desiredEnabled
                    ? 'Why should this step run for this engagement despite the wider policy?'
                    : `Why should this step stop running ${scopeLabel}? Surfaces in the timeline and the policy summary strip.`
                }
              />
            </div>
            {formError && <p className="text-sm text-red-600">{formError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy || !reason.trim()}
                onClick={() => handleCreate(false)}
                className={`rounded px-3 py-1.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50 ${
                  desiredEnabled ? 'bg-violet-600 hover:bg-violet-700' : 'bg-red-600 hover:bg-red-700'
                }`}
              >
                {busy ? 'Saving…' : desiredEnabled ? 'Override' : 'Disable'}
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {formError && <p className="text-sm text-red-600">{formError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => handleRevert(false)}
                className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {busy ? 'Reverting…' : 'Revert'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
