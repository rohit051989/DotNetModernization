import { useEffect, useState } from 'react'
import {
  deferEngagementPattern,
  deleteEngagementPattern,
  getEngagementPattern,
  listTargetStates,
  reactivateEngagementPattern,
} from '../../api/catalog'
import { ApiError } from '../../api/client'
import type { EngagementPatternView, TargetStateDetail } from '../../types/catalog'
import { CategoryBadge, DeferredBadge } from '../../components/Badge'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Drawer } from '../../components/Drawer'
import { Field, inputClass } from '../../components/FormField'
import { Markdown } from '../../components/Markdown'
import { useToast } from '../../components/Toast'
import { DecisionPanel } from './DecisionPanel'
import { TargetStateCard } from './TargetStateCard'

interface ClientPatternDetailProps {
  engagementId: string
  engagementName: string
  patternId: string
  refreshToken: number
  onCatalogChanged: () => void
  onDeleted: () => void
}

export function ClientPatternDetail({
  engagementId,
  engagementName,
  patternId,
  refreshToken,
  onCatalogChanged,
  onDeleted,
}: ClientPatternDetailProps) {
  const { showToast } = useToast()
  const [pattern, setPattern] = useState<EngagementPatternView | null>(null)
  const [targetStates, setTargetStates] = useState<TargetStateDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showRawJson, setShowRawJson] = useState(false)

  const [showDeferForm, setShowDeferForm] = useState(false)
  const [deferring, setDeferring] = useState(false)
  const [reactivating, setReactivating] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setShowRawJson(false)

    Promise.all([getEngagementPattern(engagementId, patternId), listTargetStates(patternId)])
      .then(([patternResult, targetStatesResult]) => {
        if (cancelled) return
        setPattern(patternResult)
        setTargetStates(targetStatesResult)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load this pattern.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [engagementId, patternId, refreshToken])

  async function handleReactivate() {
    setReactivating(true)
    try {
      await reactivateEngagementPattern(engagementId, patternId)
      showToast('success', 'Pattern reactivated for this engagement.')
      onCatalogChanged()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not reactivate this pattern.')
    } finally {
      setReactivating(false)
    }
  }

  async function handleDefer(reason: string) {
    setDeferring(true)
    try {
      await deferEngagementPattern(engagementId, patternId, { deferred_reason: reason || null })
      showToast('success', 'Pattern deferred for this engagement.')
      setShowDeferForm(false)
      onCatalogChanged()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not defer this pattern.')
    } finally {
      setDeferring(false)
    }
  }

  async function handleDelete() {
    // TODO: gate behind an admin check once auth exists (04-FRONTEND-SPEC.md,
    // "Future: access control"). Unlike master delete, client-scoped delete is not
    // planned to be admin-gated — but this marker stays so every mutation point
    // is visible until that design is settled.
    setDeleting(true)
    try {
      await deleteEngagementPattern(engagementId, patternId)
      showToast('success', `Pattern removed from ${engagementName}'s catalog.`)
      setShowDeleteConfirm(false)
      onDeleted()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not delete this pattern.')
    } finally {
      setDeleting(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4 p-8">
        <div className="h-8 w-1/3 animate-pulse rounded bg-neutral-100" />
        <div className="h-24 animate-pulse rounded bg-neutral-100" />
        <div className="h-40 animate-pulse rounded bg-neutral-100" />
      </div>
    )
  }

  if (error || !pattern) {
    return <div className="p-8 text-sm text-red-600">{error ?? 'Pattern not found.'}</div>
  }

  const isDeferred = pattern.scope_status === 'deferred'

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-8">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold text-neutral-900">{pattern.name}</h2>
          <p className="mt-0.5 font-mono text-xs text-neutral-400">{pattern.pattern_id}</p>
          <div className="mt-2 flex items-center gap-2">
            <CategoryBadge category={pattern.category} />
            {isDeferred && <DeferredBadge />}
          </div>
        </div>
        {/* TODO: gate Delete behind an admin check once auth exists
            (04-FRONTEND-SPEC.md, "Future: access control"). Defer/Reactivate are
            not planned to be gated — they're a normal engagement-team action. */}
        <div className="flex shrink-0 gap-2">
          {isDeferred ? (
            <button
              type="button"
              onClick={handleReactivate}
              disabled={reactivating}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50 disabled:opacity-50"
            >
              {reactivating ? 'Reactivating…' : 'Reactivate'}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setShowDeferForm(true)}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Defer
            </button>
          )}
          <button
            type="button"
            onClick={() => setShowDeleteConfirm(true)}
            className="rounded border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </div>

      {isDeferred && pattern.deferred_reason && (
        <p className="rounded bg-neutral-50 px-3 py-2 text-sm text-neutral-600">
          Deferred: {pattern.deferred_reason}
        </p>
      )}

      <p className="rounded bg-blue-50 px-3 py-2 text-sm text-blue-800">
        Managed in the master catalog. Definition, detection rules and target state options are
        read-only here.
      </p>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500">Definition</h3>
        <p className="text-sm text-neutral-700">{pattern.summary}</p>
        {pattern.description && (
          <div className="mt-3">
            <Markdown text={pattern.description} />
          </div>
        )}
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
          <div>
            <dt className="text-xs text-neutral-400">Legacy stack</dt>
            <dd className="text-neutral-700">{pattern.legacy_stack}</dd>
          </div>
          <div>
            <dt className="text-xs text-neutral-400">Version</dt>
            <dd className="text-neutral-700">{pattern.version}</dd>
          </div>
          {pattern.typical_indicators && (
            <div className="col-span-2">
              <dt className="text-xs text-neutral-400">Typical indicators</dt>
              <dd className="text-neutral-700">{pattern.typical_indicators}</dd>
            </div>
          )}
          {pattern.known_risks && (
            <div className="col-span-2">
              <dt className="text-xs text-neutral-400">Known risks</dt>
              <dd className="text-neutral-700">{pattern.known_risks}</dd>
            </div>
          )}
        </dl>
      </section>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">Detection rules</h3>
          <button
            type="button"
            onClick={() => setShowRawJson((value) => !value)}
            className="text-xs font-medium text-violet-600 hover:text-violet-700"
          >
            {showRawJson ? 'Hide raw JSON' : 'View raw JSON'}
          </button>
        </div>

        {showRawJson ? (
          <pre className="overflow-x-auto rounded bg-neutral-900 p-3 text-xs text-neutral-100">
            {JSON.stringify(pattern.detection_rules, null, 2)}
          </pre>
        ) : (
          <p className="text-xs text-neutral-400">
            {pattern.detection_rules.all.length} all · {pattern.detection_rules.any.length} any ·{' '}
            {pattern.detection_rules.atLeast.length} atLeast · {pattern.detection_rules.supporting.length} supporting ·{' '}
            {pattern.detection_rules.none.length} none · {pattern.detection_rules.metadata.length} metadata condition(s)
          </p>
        )}
      </section>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500">
          Target state options
        </h3>
        <div className="space-y-3">
          {targetStates.map((option, index) => (
            <TargetStateCard key={option.id} option={option} isPresumptive={index === 0} />
          ))}
        </div>
      </section>

      <DecisionPanel
        patternId={pattern.pattern_id}
        patternName={pattern.name}
        engagementId={engagementId}
        engagementName={engagementName}
        targetStates={targetStates}
      />

      {showDeferForm && (
        <DeferForm
          submitting={deferring}
          onClose={() => setShowDeferForm(false)}
          onSubmit={handleDefer}
        />
      )}

      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete pattern"
        message={`Delete this pattern from ${engagementName}'s catalog? It will be removed from this engagement's view and can only be restored by an administrator. The master catalog and other engagements are unaffected.`}
        confirmLabel={deleting ? 'Deleting…' : 'Delete'}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  )
}

function DeferForm({
  submitting,
  onClose,
  onSubmit,
}: {
  submitting: boolean
  onClose: () => void
  onSubmit: (reason: string) => void
}) {
  const [reason, setReason] = useState('')

  return (
    <Drawer title="Defer pattern" onRequestClose={onClose}>
      <form
        onSubmit={(event) => {
          event.preventDefault()
          onSubmit(reason)
        }}
        className="flex h-full flex-col"
      >
        <div className="flex-1 space-y-4">
          <Field label="Reason (optional)">
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={4}
              placeholder="Why isn't this engagement tackling this pattern right now?"
              className={inputClass(false)}
            />
          </Field>
        </div>
        <div className="flex justify-end gap-2 border-t border-neutral-200 pt-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
          >
            {submitting ? 'Deferring…' : 'Defer'}
          </button>
        </div>
      </form>
    </Drawer>
  )
}
