import { useState } from 'react'
import { ApiError } from '../../../api/client'
import { deleteStepPolicy, setStepPolicy } from '../../../api/policies'
import type { PolicyConflictDetail } from '../../../types/policy'

interface StepPolicyDialogProps {
  engagementId: string
  stepName: string
  displayName: string
  currentlyEnabled: boolean
  currentReason: string | null
  onClose: () => void
  onChanged: () => void
}

/** The toggle dialog from the flow card's policy state — 22-STEP-SEQUENCING-AND-POLICY.md
 * Part E: "On toggle off, a required-reason dialog. If the API returns
 * POLICY_ORPHANS_DEPENDENTS, show the dependent steps and offer an explicit
 * 'also disable these' confirmation which resubmits with cascade: true." The
 * re-enable direction mirrors this with POLICY_REVERT_ORPHANS_STEP and `force`. */
export function StepPolicyDialog({
  engagementId,
  stepName,
  displayName,
  currentlyEnabled,
  currentReason,
  onClose,
  onChanged,
}: StepPolicyDialogProps) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [conflict, setConflict] = useState<PolicyConflictDetail | null>(null)

  function conflictDetails(err: ApiError): PolicyConflictDetail | null {
    const detail = err.rawDetail[0] as PolicyConflictDetail | undefined
    return detail && typeof detail === 'object' && 'code' in detail ? detail : null
  }

  async function handleDisable(cascade: boolean) {
    setBusy(true)
    setFormError(null)
    try {
      await setStepPolicy(engagementId, { step_name: stepName, enabled: false, reason, cascade })
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
      setFormError(err instanceof ApiError ? err.message : 'Could not disable this step.')
    } finally {
      setBusy(false)
    }
  }

  async function handleReEnable(force: boolean) {
    setBusy(true)
    setFormError(null)
    try {
      await deleteStepPolicy(engagementId, stepName, force)
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
      setFormError(err instanceof ApiError ? err.message : 'Could not re-enable this step.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-neutral-900/30" onClick={onClose} aria-hidden="true" />
      <div className="relative w-full max-w-md rounded bg-white p-5 shadow-xl">
        <h3 className="text-sm font-semibold text-neutral-900">
          {currentlyEnabled ? `Disable ${displayName}` : `Re-enable ${displayName}`}
        </h3>

        {!currentlyEnabled && (
          <p className="mt-2 text-sm text-neutral-600">
            Currently disabled{currentReason ? `: ${currentReason}` : '.'} Reverting deletes this policy row —
            absence means enabled.
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
                  onClick={() => handleDisable(true)}
                  className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
                >
                  {busy ? 'Disabling…' : 'Also disable these'}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => handleReEnable(true)}
                  className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
                >
                  {busy ? 'Re-enabling…' : 'Re-enable anyway'}
                </button>
              )}
            </div>
          </div>
        ) : currentlyEnabled ? (
          <div className="mt-3 space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">Reason *</label>
              <textarea
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={3}
                className="w-full rounded border border-neutral-300 px-3 py-1.5 text-sm focus:border-violet-400 focus:outline-none"
                placeholder="Why is this step disabled for this engagement? Surfaces in the timeline and the policy summary strip."
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
                onClick={() => handleDisable(false)}
                className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {busy ? 'Disabling…' : 'Disable'}
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
                onClick={() => handleReEnable(false)}
                className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {busy ? 'Re-enabling…' : 'Re-enable'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
