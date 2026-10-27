import { useEffect, useMemo, useState } from 'react'
import {
  deleteCatalogItem,
  deleteResolution,
  getCatalogItem,
  listCatalogSignals,
  listItemSignals,
  listResolutions,
  makeResolutionDefault,
  restoreCatalogItem,
  restoreResolution,
} from '../../api/items'
import { ApiError } from '../../api/client'
import type { Engagement } from '../../types/catalog'
import {
  CONSUMER_IMPACT_RANK,
  type CatalogItem,
  type CatalogSignal,
  type ItemResolution,
  type ItemSignal,
} from '../../types/items'
import {
  CategoryBadge,
  DeletedBadge,
  ReadinessBadge,
  ScopeBadge,
  SignalStateBadge,
  SignalUsageBadge,
  StatusBadge,
} from '../../components/Badge'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { LimitedList } from '../../components/LimitedList'
import { Markdown } from '../../components/Markdown'
import { useToast } from '../../components/Toast'
import { DetectionView } from './DetectionView'
import { ItemDecisionPanel } from './ItemDecisionPanel'
import { ItemForm } from './ItemForm'
import { ReadinessReason } from './ReadinessReason'
import { ResolutionCard } from './ResolutionCard'
import { ResolutionForm } from './ResolutionForm'
import { formatDate, lowestImpactResolution } from './itemHelpers'
import { useIsAdmin } from '../../auth/AuthContext'

interface ItemDetailProps {
  itemId: string
  /** null = master catalog view (editable); otherwise the client view for this engagement. */
  engagement: Engagement | null
  refreshToken: number
  onCatalogChanged: () => void
  /** Warnings returned by the last create/update of this item, if any. */
  saveWarnings: string[]
  onDismissSaveWarnings: () => void
  onItemSaved: (itemId: string, warnings: string[]) => void
  /** Opens this signal in the master Signals view. Omitted in the client
   * view, where signal names are not links. */
  onSelectSignal?: (name: string) => void
}

type ResolutionFormMode = { kind: 'create' } | { kind: 'edit'; resolution: ItemResolution } | null
type PendingConfirm =
  | { kind: 'delete-item' }
  | { kind: 'delete-resolution'; resolution: ItemResolution }
  | null

const secondaryButton =
  'rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:text-neutral-300'
const smallButton =
  'rounded border border-neutral-300 px-2 py-0.5 text-xs text-neutral-600 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40'

export function ItemDetail({
  itemId,
  engagement,
  refreshToken,
  onCatalogChanged,
  saveWarnings,
  onDismissSaveWarnings,
  onItemSaved,
  onSelectSignal,
}: ItemDetailProps) {
  const isAdmin = useIsAdmin()
  const isMaster = engagement === null
  const { showToast } = useToast()
  const [item, setItem] = useState<CatalogItem | null>(null)
  const [resolutions, setResolutions] = useState<ItemResolution[]>([])
  const [signals, setSignals] = useState<CatalogSignal[] | null>(null)
  const [itemSignals, setItemSignals] = useState<ItemSignal[] | null>(null)
  const [itemSignalsError, setItemSignalsError] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showRawJson, setShowRawJson] = useState(false)
  const [showDeletedResolutions, setShowDeletedResolutions] = useState(false)
  const [showEditForm, setShowEditForm] = useState(false)
  const [resolutionForm, setResolutionForm] = useState<ResolutionFormMode>(null)
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm>(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)

  useEffect(() => {
    listCatalogSignals()
      .then(setSignals)
      .catch(() => setSignals(null))
  }, [refreshToken])

  useEffect(() => {
    let cancelled = false
    setItemSignalsError(false)
    listItemSignals(itemId)
      .then((result) => {
        if (!cancelled) setItemSignals(result)
      })
      .catch(() => {
        if (!cancelled) {
          setItemSignals(null)
          setItemSignalsError(true)
        }
      })
    return () => {
      cancelled = true
    }
  }, [itemId, refreshToken])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setActionError(null)
    Promise.all([getCatalogItem(itemId, isMaster), listResolutions(itemId, isMaster)])
      .then(([itemResult, resolutionResult]) => {
        if (cancelled) return
        setItem(itemResult)
        setResolutions(resolutionResult)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError && err.status === 404 ? 'Item not found.' : 'Could not load this item.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [itemId, isMaster, refreshToken])

  const signalsByName = useMemo(
    () => (signals ? new Map(signals.map((s) => [s.name, s])) : undefined),
    [signals],
  )

  const sortedResolutions = useMemo(
    () =>
      [...resolutions].sort(
        (a, b) =>
          CONSUMER_IMPACT_RANK[a.consumer_impact] - CONSUMER_IMPACT_RANK[b.consumer_impact] ||
          a.name.localeCompare(b.name),
      ),
    [resolutions],
  )
  const liveResolutions = sortedResolutions.filter((r) => r.deleted_at === null)
  const deletedResolutions = sortedResolutions.filter((r) => r.deleted_at !== null)
  const lowest = lowestImpactResolution(resolutions)
  const currentDefault = liveResolutions.find((r) => r.is_default) ?? null

  async function runAction(action: () => Promise<unknown>, success: string, failure: string) {
    setBusy(true)
    setActionError(null)
    try {
      await action()
      showToast('success', success)
      setPendingConfirm(null)
      onCatalogChanged()
    } catch (err) {
      const message = err instanceof ApiError ? err.message : failure
      setActionError(message)
      showToast('error', message)
      setPendingConfirm(null)
    } finally {
      setBusy(false)
    }
  }

  function handleDeleteItem() {
    return runAction(() => deleteCatalogItem(itemId), 'Item deleted. Restore it from "Show deleted".', 'Could not delete this item.')
  }

  function handleRestoreItem() {
    return runAction(
      () => restoreCatalogItem(itemId),
      'Item restored. Its resolutions stay deleted until restored one by one.',
      'Could not restore this item.',
    )
  }

  function handleDeleteResolution(resolution: ItemResolution) {
    return runAction(() => deleteResolution(itemId, resolution.id), 'Resolution deleted.', 'Could not delete this resolution.')
  }

  function handleRestoreResolution(resolution: ItemResolution) {
    return runAction(() => restoreResolution(itemId, resolution.id), 'Resolution restored.', 'Could not restore this resolution.')
  }

  async function handleMakeDefault(resolution: ItemResolution) {
    setBusy(true)
    setActionError(null)
    try {
      const live = await makeResolutionDefault(itemId, resolution.id)
      setResolutions((current) => [...live, ...current.filter((r) => r.deleted_at !== null)])
      showToast('success', `${resolution.name} is now the default.`)
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Could not change the default resolution.'
      setActionError(message)
      showToast('error', message)
    } finally {
      setBusy(false)
    }
  }

  if (loading && !item) {
    return (
      <div className="space-y-4 p-8">
        <div className="h-8 w-1/3 animate-pulse rounded bg-neutral-100" />
        <div className="h-24 animate-pulse rounded bg-neutral-100" />
        <div className="h-40 animate-pulse rounded bg-neutral-100" />
      </div>
    )
  }

  if (error || !item) {
    return <div className="p-8 text-sm text-red-600">{error ?? 'Item not found.'}</div>
  }

  const deleted = item.deleted_at !== null

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-neutral-900">{item.name}</h2>
          <p className="mt-0.5 font-mono text-xs text-neutral-400">{item.id}</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <ReadinessBadge state={item.state} />
            <ScopeBadge scope={item.scope} />
            <CategoryBadge category={item.category} />
            <StatusBadge status={item.status} />
            {deleted && <DeletedBadge />}
          </div>
        </div>
        {isMaster && !isAdmin && (
          <p className="shrink-0 text-xs text-neutral-500">Read-only: only an admin changes the master catalog.</p>
        )}
        {isMaster && isAdmin && (
          <div className="flex shrink-0 gap-2">
            {deleted ? (
              <button type="button" onClick={handleRestoreItem} disabled={busy} className={secondaryButton}>
                Restore
              </button>
            ) : (
              <>
                <button type="button" onClick={() => setShowEditForm(true)} className={secondaryButton}>
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => setPendingConfirm({ kind: 'delete-item' })}
                  className="rounded border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
                >
                  Delete
                </button>
              </>
            )}
          </div>
        )}
      </div>

      {!isMaster && (
        <p className="rounded bg-neutral-50 px-3 py-2 text-xs text-neutral-500">
          Master catalog data is read-only here. Switch to the Master Catalog to edit the item or its resolutions; this
          engagement's decision is captured below.
        </p>
      )}

      {saveWarnings.length > 0 && (
        <div className="flex items-start justify-between gap-3 rounded border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <div>
            <p className="font-medium">Saved with warnings</p>
            <LimitedList items={saveWarnings} name={(w) => w} noun="warnings">
              {(visible) =>
                visible.map((w, i) => (
                  <p key={i} className="mt-1">
                    {w}
                  </p>
                ))
              }
            </LimitedList>
          </div>
          <button type="button" onClick={onDismissSaveWarnings} aria-label="Dismiss" className="text-amber-500 hover:text-amber-700">
            ✕
          </button>
        </div>
      )}

      {actionError && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{actionError}</p>}

      {deleted && (
        <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">
          Soft-deleted {formatDate(item.deleted_at)}
          {item.deleted_by ? ` by ${item.deleted_by}` : ''}. Hidden from every normal view until restored.
        </p>
      )}

      <ReadinessReason item={item} onSelectSignal={onSelectSignal} />

      <section className="rounded border border-neutral-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500">Definition</h3>
        {item.description ? (
          <Markdown text={item.description} />
        ) : (
          <p className="text-sm text-neutral-400">No description.</p>
        )}
        <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-xs text-neutral-400">Scope</dt>
            <dd className="text-neutral-700">
              {item.scope === 'application' ? 'application — once per project' : 'occurrence — per file'}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-neutral-400">Category</dt>
            <dd className="text-neutral-700">{item.category}</dd>
          </div>
          <div>
            <dt className="text-xs text-neutral-400">Version</dt>
            <dd className="text-neutral-700">{item.version}</dd>
          </div>
          <div>
            <dt className="text-xs text-neutral-400">Owner team</dt>
            <dd className="text-neutral-700">{item.owner_team ?? '—'}</dd>
          </div>
          <div className="col-span-2 sm:col-span-4">
            <dt className="text-xs text-neutral-400">Excluded project roles</dt>
            <dd className="mt-0.5 flex flex-wrap gap-1.5">
              {item.excluded_roles.length === 0 ? (
                <span className="text-neutral-400">none — applies to every role</span>
              ) : (
                item.excluded_roles.map((role) => (
                  <span key={role} className="rounded bg-neutral-100 px-2 py-0.5 font-mono text-xs text-neutral-700">
                    {role}
                  </span>
                ))
              )}
            </dd>
          </div>
        </dl>
      </section>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">Detection</h3>
          <button
            type="button"
            onClick={() => setShowRawJson((value) => !value)}
            className="text-xs font-medium text-violet-600 hover:text-violet-700"
          >
            {showRawJson ? 'Show readable' : 'View raw JSON'}
          </button>
        </div>
        {showRawJson ? (
          <pre className="overflow-x-auto rounded bg-neutral-900 p-3 text-xs text-neutral-100">
            {JSON.stringify(item.detection, null, 2)}
          </pre>
        ) : (
          <>
            <DetectionView detection={item.detection} signals={signalsByName} onSelectSignal={onSelectSignal} />
            {signalsByName && (
              <p className="mt-3 text-[11px] text-neutral-400">
                Signal names: grey = ready · <span className="text-amber-700">amber = not ready</span> ·{' '}
                <span className="text-red-600">red = not registered</span>. Hover for details
                {onSelectSignal ? '; click one to see every item that uses it' : ''}.
              </p>
            )}
          </>
        )}
      </section>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
          Signals{' '}
          {itemSignals && <span className="font-normal normal-case text-neutral-400">· {itemSignals.length}</span>}
        </h3>
        <p className="mt-0.5 text-xs text-neutral-400">
          The signals this item's detection references, and which part uses each one.
          {onSelectSignal ? ' Click a signal to see every item that uses it.' : ''}
        </p>
        {itemSignalsError ? (
          <p className="mt-3 text-sm text-red-600">Could not load this item's signals.</p>
        ) : itemSignals === null ? (
          <div className="mt-3 h-16 animate-pulse rounded bg-neutral-100" />
        ) : itemSignals.length === 0 ? (
          <p className="mt-3 text-sm text-neutral-400">The detection references no signals yet.</p>
        ) : (
          <LimitedList items={itemSignals} name={(s) => s.name} noun="signals" className="mt-3">
            {(visible) => (
              <table className="w-full text-left text-xs">
                <thead className="text-neutral-400">
                  <tr className="border-b border-neutral-200">
                    <th className="py-1.5 pr-3 font-medium">Signal</th>
                    <th className="py-1.5 pr-3 font-medium">Used in</th>
                    <th className="py-1.5 pr-3 font-medium">State</th>
                    <th className="py-1.5 pr-3 font-medium">Type</th>
                    <th className="py-1.5 pr-3 font-medium">Category</th>
                    <th className="py-1.5 font-medium">Extractor</th>
                  </tr>
                </thead>
                <tbody>
                  {visible.map((signal) => (
                    <tr key={signal.name} className="border-b border-neutral-100 align-top">
                      <td className="py-1.5 pr-3">
                        {onSelectSignal ? (
                          <button
                            type="button"
                            onClick={() => onSelectSignal(signal.name)}
                            className={`font-mono hover:underline ${signal.registered ? 'text-violet-700' : 'text-red-700'}`}
                          >
                            {signal.name}
                          </button>
                        ) : (
                          <span className={`font-mono ${signal.registered ? 'text-neutral-800' : 'text-red-700'}`}>
                            {signal.name}
                          </span>
                        )}
                      </td>
                      <td className="py-1.5 pr-3">
                        <span className="flex flex-wrap gap-1">
                          {signal.usages.map((usage) => (
                            <SignalUsageBadge key={usage} usage={usage} />
                          ))}
                        </span>
                      </td>
                      <td className="py-1.5 pr-3">
                        <SignalStateBadge state={signal.registered ? signal.state : null} />
                      </td>
                      <td className="py-1.5 pr-3 font-mono text-neutral-600">{signal.type ?? '—'}</td>
                      <td className="py-1.5 pr-3 text-neutral-600">{signal.category ?? '—'}</td>
                      <td className="py-1.5 font-mono text-neutral-600">{signal.expected_extractor ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </LimitedList>
        )}
      </section>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-neutral-500">
            Resolutions <span className="font-normal normal-case text-neutral-400">· {liveResolutions.length}</span>
          </h3>
          {isMaster && deletedResolutions.length > 0 && (
            <button
              type="button"
              onClick={() => setShowDeletedResolutions((v) => !v)}
              className="text-xs font-medium text-violet-600 hover:text-violet-700"
            >
              {showDeletedResolutions ? 'Hide' : 'Show'} {deletedResolutions.length} deleted
            </button>
          )}
        </div>
        {liveResolutions.length === 0 && (
          <p className="text-sm text-neutral-400">
            No resolutions yet{isMaster ? ' — add the options an engagement can choose from.' : '.'}
          </p>
        )}
        <LimitedList
          items={[...liveResolutions, ...(showDeletedResolutions ? deletedResolutions : [])]}
          name={(r) => r.name}
          noun="resolutions"
        >
          {(visible) => (
            <div className="space-y-3">
              {visible.map((resolution) => {
                const resolutionDeleted = resolution.deleted_at !== null
                return (
                  <ResolutionCard
                    key={resolution.id}
                    resolution={resolution}
                    isLowestImpact={lowest?.consumer_impact === resolution.consumer_impact && resolution.status === 'active'}
                    actions={
                      isMaster && isAdmin && !deleted ? (
                        resolutionDeleted ? (
                          <button type="button" disabled={busy} onClick={() => handleRestoreResolution(resolution)} className={smallButton}>
                            Restore
                          </button>
                        ) : (
                          <>
                            <button type="button" onClick={() => setResolutionForm({ kind: 'edit', resolution })} className={smallButton}>
                              Edit
                            </button>
                            {!resolution.is_default && resolution.status === 'active' && (
                              <button type="button" disabled={busy} onClick={() => handleMakeDefault(resolution)} className={smallButton}>
                                Make default
                              </button>
                            )}
                            <button
                              type="button"
                              onClick={() => setPendingConfirm({ kind: 'delete-resolution', resolution })}
                              className="rounded border border-red-200 px-2 py-0.5 text-xs text-red-600 hover:bg-red-50"
                            >
                              Delete
                            </button>
                          </>
                        )
                      ) : undefined
                    }
                  />
                )
              })}
            </div>
          )}
        </LimitedList>
        {isMaster && isAdmin && !deleted && (
          <button
            type="button"
            onClick={() => setResolutionForm({ kind: 'create' })}
            className="mt-3 w-full rounded border border-dashed border-violet-300 py-2 text-sm font-medium text-violet-600 hover:border-violet-400 hover:bg-violet-50"
          >
            + Add resolution
          </button>
        )}
      </section>

      {engagement && !deleted && (
        <ItemDecisionPanel
          item={item}
          engagement={engagement}
          resolutions={resolutions}
          refreshToken={refreshToken}
          onDecisionChanged={onCatalogChanged}
        />
      )}

      {showEditForm && (
        <ItemForm
          mode="edit"
          item={item}
          onClose={() => setShowEditForm(false)}
          onSaved={(savedId, warnings) => {
            setShowEditForm(false)
            onItemSaved(savedId, warnings)
          }}
        />
      )}

      {resolutionForm && (
        <ResolutionForm
          mode={resolutionForm.kind}
          itemId={item.id}
          itemVersion={item.edit_version}
          resolution={resolutionForm.kind === 'edit' ? resolutionForm.resolution : undefined}
          existingDefault={currentDefault}
          onClose={() => setResolutionForm(null)}
          onSaved={() => {
            setResolutionForm(null)
            onCatalogChanged()
          }}
        />
      )}

      <ConfirmDialog
        open={pendingConfirm?.kind === 'delete-item'}
        title="Delete item"
        message="Soft-delete this item and all its resolutions? They disappear from every normal view (including engagements) until restored. Blocked while any engagement holds a live decision on it."
        confirmLabel={busy ? 'Deleting…' : 'Delete'}
        destructive
        onConfirm={handleDeleteItem}
        onCancel={() => setPendingConfirm(null)}
      />

      <ConfirmDialog
        open={pendingConfirm?.kind === 'delete-resolution'}
        title="Delete resolution"
        message={`Soft-delete "${pendingConfirm?.kind === 'delete-resolution' ? pendingConfirm.resolution.name : ''}"? Blocked while a live engagement decision selects it. It can be restored later.`}
        confirmLabel={busy ? 'Deleting…' : 'Delete'}
        destructive
        onConfirm={() => {
          if (pendingConfirm?.kind === 'delete-resolution') handleDeleteResolution(pendingConfirm.resolution)
        }}
        onCancel={() => setPendingConfirm(null)}
      />
    </div>
  )
}
