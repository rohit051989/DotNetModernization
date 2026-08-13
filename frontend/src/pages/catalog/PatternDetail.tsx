import { useEffect, useState } from 'react'
import { deletePattern, deprecatePattern, getPattern, listTargetStates } from '../../api/catalog'
import { ApiError } from '../../api/client'
import type { DetectionRules, PatternDetail as PatternDetailModel, TargetStateDetail } from '../../types/catalog'
import { CategoryBadge, StatusBadge } from '../../components/Badge'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Markdown } from '../../components/Markdown'
import { useToast } from '../../components/Toast'
import { PatternForm } from './PatternForm'
import { TargetStateCard } from './TargetStateCard'
import { TargetStateForm } from './TargetStateForm'

interface PatternDetailProps {
  patternId: string
  refreshToken: number
  onCatalogChanged: () => void
  onDeleted: () => void
}

const DETECTION_RULE_LIST_FIELDS: { key: keyof DetectionRules; label: string }[] = [
  { key: 'target_frameworks', label: 'Target frameworks' },
  { key: 'required_namespaces', label: 'Required namespaces' },
  { key: 'forbidden_namespaces', label: 'Forbidden namespaces' },
  { key: 'required_packages', label: 'Required packages' },
  { key: 'file_globs', label: 'File globs' },
  { key: 'forbidden_file_globs', label: 'Forbidden file globs' },
  { key: 'config_markers', label: 'Config markers' },
]

type TargetStateFormMode = { kind: 'create' } | { kind: 'edit'; option: TargetStateDetail } | null

export function PatternDetail({ patternId, refreshToken, onCatalogChanged, onDeleted }: PatternDetailProps) {
  const { showToast } = useToast()
  const [pattern, setPattern] = useState<PatternDetailModel | null>(null)
  const [targetStates, setTargetStates] = useState<TargetStateDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showRawJson, setShowRawJson] = useState(false)

  const [showEditForm, setShowEditForm] = useState(false)
  const [showDeprecateConfirm, setShowDeprecateConfirm] = useState(false)
  const [deprecating, setDeprecating] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [targetStateForm, setTargetStateForm] = useState<TargetStateFormMode>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    setShowRawJson(false)

    Promise.all([getPattern(patternId), listTargetStates(patternId)])
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
  }, [patternId, refreshToken])

  async function handleDeprecate() {
    setDeprecating(true)
    try {
      const result = await deprecatePattern(patternId)
      showToast(
        'success',
        result.referenced_by_decisions > 0
          ? `Pattern deprecated. Referenced by ${result.referenced_by_decisions} decision record${
              result.referenced_by_decisions === 1 ? '' : 's'
            }.`
          : 'Pattern deprecated.',
      )
      setShowDeprecateConfirm(false)
      onCatalogChanged()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not deprecate this pattern.')
    } finally {
      setDeprecating(false)
    }
  }

  async function handleDelete() {
    // TODO: gate behind an admin role once auth exists. This action is currently
    // reachable by anyone, matching the rest of this build (no auth system yet),
    // but it is intended to become admin-only — see 04-FRONTEND-SPEC.md.
    setDeleting(true)
    try {
      await deletePattern(patternId)
      showToast('success', 'Pattern deleted.')
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

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-8">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold text-neutral-900">{pattern.name}</h2>
          <p className="mt-0.5 font-mono text-xs text-neutral-400">{pattern.id}</p>
          <div className="mt-2 flex items-center gap-2">
            <CategoryBadge category={pattern.category} />
            <StatusBadge status={pattern.status} />
          </div>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={() => setShowEditForm(true)}
            className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => setShowDeprecateConfirm(true)}
            disabled={pattern.status === 'deprecated'}
            className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:text-neutral-300"
          >
            Deprecate
          </button>
          <button
            type="button"
            onClick={() => setShowDeleteConfirm(true)}
            className="rounded border border-red-200 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </div>

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
          <div className="space-y-3">
            {DETECTION_RULE_LIST_FIELDS.map(({ key, label }) => {
              const values = pattern.detection_rules[key]
              if (!Array.isArray(values) || values.length === 0) return null
              return (
                <div key={key}>
                  <p className="text-xs font-medium text-neutral-500">{label}</p>
                  <ul className="mt-1 flex flex-wrap gap-1.5">
                    {values.map((value) => (
                      <li key={value} className="rounded bg-neutral-100 px-2 py-0.5 font-mono text-xs text-neutral-700">
                        {value}
                      </li>
                    ))}
                  </ul>
                </div>
              )
            })}
            {pattern.detection_rules.notes && (
              <p className="text-sm italic text-neutral-500">{pattern.detection_rules.notes}</p>
            )}
          </div>
        )}
      </section>

      <section className="rounded border border-neutral-200 bg-white p-5">
        <h3 className="mb-3 text-sm font-semibold uppercase tracking-wide text-neutral-500">
          Target state options
        </h3>
        <div className="space-y-3">
          {targetStates.map((option, index) => (
            <TargetStateCard
              key={option.id}
              option={option}
              isPresumptive={index === 0}
              onEdit={() => setTargetStateForm({ kind: 'edit', option })}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={() => setTargetStateForm({ kind: 'create' })}
          className="mt-3 w-full rounded border border-dashed border-violet-300 py-2 text-sm font-medium text-violet-600 hover:border-violet-400 hover:bg-violet-50"
        >
          + Add target state option
        </button>
      </section>

      {showEditForm && (
        <PatternForm
          mode="edit"
          pattern={pattern}
          onClose={() => setShowEditForm(false)}
          onSaved={() => {
            setShowEditForm(false)
            onCatalogChanged()
          }}
        />
      )}

      {targetStateForm && (
        <TargetStateForm
          mode={targetStateForm.kind}
          patternId={patternId}
          option={targetStateForm.kind === 'edit' ? targetStateForm.option : undefined}
          onClose={() => setTargetStateForm(null)}
          onSaved={() => {
            setTargetStateForm(null)
            onCatalogChanged()
          }}
        />
      )}

      <ConfirmDialog
        open={showDeprecateConfirm}
        title="Deprecate pattern"
        message="Deprecate this pattern? It stays in the catalog and existing decision records remain valid, but it will be hidden from the default list."
        confirmLabel={deprecating ? 'Deprecating…' : 'Deprecate'}
        destructive
        onConfirm={handleDeprecate}
        onCancel={() => setShowDeprecateConfirm(false)}
      />

      <ConfirmDialog
        open={showDeleteConfirm}
        title="Delete pattern"
        message="Delete this pattern? It will be removed from the catalog and can only be restored by an administrator."
        confirmLabel={deleting ? 'Deleting…' : 'Delete'}
        destructive
        onConfirm={handleDelete}
        onCancel={() => setShowDeleteConfirm(false)}
      />
    </div>
  )
}
