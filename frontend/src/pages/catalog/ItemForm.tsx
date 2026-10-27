import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { createCatalogItem, listCatalogSignals, updateCatalogItem } from '../../api/items'
import { ApiError, type FieldError } from '../../api/client'
import { Drawer } from '../../components/Drawer'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Field, inputClass } from '../../components/FormField'
import { useToast } from '../../components/Toast'
import {
  ITEM_CATEGORIES,
  PROJECT_ROLES,
  type CatalogItem,
  type CatalogItemWriteInput,
  type CatalogSignal,
  type ItemCategory,
  type ItemDetection,
  type ItemMatch,
  type ItemScope,
  type ItemStatus,
  type OccurrenceGroupBy,
  type ProjectRole,
} from '../../types/items'
import { compactMatch, positiveSignalNames, slugify } from './itemHelpers'

const MATCH_KEYS = ['all', 'any', 'atLeast', 'none', 'metadata']
type HelperGroup = 'all' | 'any' | 'none'

interface ItemFormProps {
  mode: 'create' | 'edit'
  item?: CatalogItem
  onClose: () => void
  onSaved: (itemId: string, warnings: string[]) => void
}

interface FormState {
  id: string
  name: string
  description: string
  scope: ItemScope
  category: ItemCategory
  status: ItemStatus
  owner_team: string
  excluded_roles: ProjectRole[]
  matchText: string
  occurrenceSignal: string
  groupBy: OccurrenceGroupBy
}

function toFormState(item?: CatalogItem): FormState {
  return {
    id: item?.id ?? '',
    name: item?.name ?? '',
    description: item?.description ?? '',
    scope: item?.scope ?? 'occurrence',
    category: (item?.category as ItemCategory) ?? 'hosting',
    status: item?.status ?? 'active',
    owner_team: item?.owner_team ?? '',
    excluded_roles: (item?.excluded_roles ?? []) as ProjectRole[],
    matchText: JSON.stringify(compactMatch(item?.detection.match), null, 2),
    occurrenceSignal: item?.detection.occurrence_source?.signal ?? '',
    groupBy: item?.detection.occurrence_source?.group_by ?? 'source_path',
  }
}

type ParsedMatch = { ok: true; match: ItemMatch; unknownKeys: string[] } | { ok: false; error: string }

function parseMatch(text: string): ParsedMatch {
  if (text.trim() === '') return { ok: true, match: {}, unknownKeys: [] }
  try {
    const value: unknown = JSON.parse(text)
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
      return { ok: false, error: 'match must be a JSON object, e.g. { "all": [ … ] }.' }
    }
    const unknownKeys = Object.keys(value).filter((key) => !MATCH_KEYS.includes(key))
    return { ok: true, match: value as ItemMatch, unknownKeys }
  } catch (err) {
    return { ok: false, error: `Invalid JSON: ${err instanceof Error ? err.message : String(err)}` }
  }
}

export function ItemForm({ mode, item, onClose, onSaved }: ItemFormProps) {
  const { showToast } = useToast()
  const [form, setForm] = useState<FormState>(() => toFormState(item))
  const [idTouched, setIdTouched] = useState(mode === 'edit')
  const [dirty, setDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<FieldError[]>([])
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false)
  const [signals, setSignals] = useState<CatalogSignal[]>([])
  const [helperSignal, setHelperSignal] = useState('')
  const [helperGroup, setHelperGroup] = useState<HelperGroup>('all')

  useEffect(() => {
    listCatalogSignals()
      .then(setSignals)
      .catch(() => setSignals([]))
  }, [])

  const signalsByName = useMemo(() => new Map(signals.map((s) => [s.name, s])), [signals])
  const parsed = useMemo(() => parseMatch(form.matchText), [form.matchText])
  const positiveNames = parsed.ok ? positiveSignalNames(parsed.match) : []

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => {
      const next = { ...current, [key]: value }
      if (key === 'name' && mode === 'create' && !idTouched) next.id = slugify(String(value))
      return next
    })
    setDirty(true)
  }

  function toggleRole(role: ProjectRole) {
    update(
      'excluded_roles',
      form.excluded_roles.includes(role) ? form.excluded_roles.filter((r) => r !== role) : [...form.excluded_roles, role],
    )
  }

  function addHelperCondition() {
    const name = helperSignal.trim()
    if (!name || !parsed.ok) return
    const match: ItemMatch = { ...parsed.match }
    const group = [...(match[helperGroup] ?? [])]
    const existingIds = new Set<string>()
    for (const key of ['all', 'any', 'none'] as const) for (const c of match[key] ?? []) if (c.id) existingIds.add(c.id)
    let id = `${helperGroup === 'none' ? 'no' : 'has'}-${slugify(name)}`
    for (let n = 2; existingIds.has(id); n++) id = `${helperGroup === 'none' ? 'no' : 'has'}-${slugify(name)}-${n}`
    group.push({ id, signal: { name } })
    match[helperGroup] = group
    update('matchText', JSON.stringify(match, null, 2))
    if (form.scope === 'occurrence' && !form.occurrenceSignal && helperGroup !== 'none') {
      update('occurrenceSignal', name)
    }
    setHelperSignal('')
  }

  function requestClose() {
    if (dirty) setShowDiscardConfirm(true)
    else onClose()
  }

  const errorsFor = (prefix: string) =>
    fieldErrors.filter((e) => e.field === prefix || e.field.startsWith(`${prefix}.`))
  const firstError = (field: string) =>
    errorsFor(field)
      .map((e) => e.message)
      .join(' ') || undefined
  const occurrenceErrors = errorsFor('detection.occurrence_source')
  const matchErrors = errorsFor('detection').filter((e) => !e.field.startsWith('detection.occurrence_source'))
  const knownPrefixes = ['id', 'name', 'description', 'scope', 'category', 'status', 'owner_team', 'excluded_roles', 'detection']
  const otherErrors = fieldErrors.filter(
    (e) => !knownPrefixes.some((prefix) => e.field === prefix || e.field.startsWith(`${prefix}.`)),
  )

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!parsed.ok) {
      setFieldErrors([{ field: 'detection.match', message: parsed.error }])
      return
    }
    // Admins only (app.auth.policy): the form opens for admins only.
    setSubmitting(true)
    setFieldErrors([])
    const detection: ItemDetection = { match: parsed.match }
    if (form.scope === 'occurrence' && form.occurrenceSignal) {
      detection.occurrence_source = { signal: form.occurrenceSignal, group_by: form.groupBy }
    }
    const payload: CatalogItemWriteInput = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      scope: form.scope,
      category: form.category,
      detection,
      excluded_roles: form.excluded_roles,
      owner_team: form.owner_team.trim() || null,
      status: form.status,
    }
    try {
      const result =
        mode === 'create'
          ? await createCatalogItem({ id: form.id.trim(), ...payload })
          : await updateCatalogItem(item!.id, payload, item!.edit_version)
      showToast('success', mode === 'create' ? 'Item created.' : 'Item saved.')
      onSaved(result.item.id, result.warnings)
    } catch (err) {
      if (err instanceof ApiError) {
        setFieldErrors(err.fieldErrors.length > 0 ? err.fieldErrors : [{ field: '__root__', message: err.message }])
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
      <Drawer
        title={mode === 'create' ? 'New catalog item' : `Edit ${item?.name ?? 'item'}`}
        onRequestClose={requestClose}
        wide
      >
        <form onSubmit={handleSubmit} className="flex h-full flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto pb-4">
            {otherErrors.length > 0 && (
              <div className="space-y-1 rounded bg-red-50 px-3 py-2 text-sm text-red-700">
                {otherErrors.map((e, i) => (
                  <p key={i}>{e.message}</p>
                ))}
              </div>
            )}

            <Field label="Name" error={firstError('name')}>
              <input
                type="text"
                value={form.name}
                onChange={(e) => update('name', e.target.value)}
                className={inputClass(!!firstError('name'))}
                required
              />
            </Field>

            {mode === 'create' ? (
              <Field label="Id (slug — cannot be changed later)" error={firstError('id')}>
                <input
                  type="text"
                  value={form.id}
                  onChange={(e) => {
                    setIdTouched(true)
                    update('id', e.target.value)
                  }}
                  placeholder="e.g. serilog-file-sink"
                  className={`${inputClass(!!firstError('id'))} font-mono`}
                  required
                />
              </Field>
            ) : (
              <p className="text-xs text-neutral-400">
                Id <span className="font-mono text-neutral-600">{item?.id}</span> · version {item?.version} (bumped when
                detection or scope changes)
              </p>
            )}

            <Field label="Description" error={firstError('description')}>
              <textarea
                value={form.description}
                onChange={(e) => update('description', e.target.value)}
                rows={3}
                className={inputClass(!!firstError('description'))}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Scope" error={firstError('scope')}>
                <select
                  value={form.scope}
                  onChange={(e) => update('scope', e.target.value as ItemScope)}
                  className={inputClass(!!firstError('scope'))}
                >
                  <option value="application">application — once per project</option>
                  <option value="occurrence">occurrence — per file</option>
                </select>
              </Field>
              <Field label="Category" error={firstError('category')}>
                <select
                  value={form.category}
                  onChange={(e) => update('category', e.target.value as ItemCategory)}
                  className={inputClass(!!firstError('category'))}
                >
                  {ITEM_CATEGORIES.map((category) => (
                    <option key={category} value={category}>
                      {category}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Owner team" error={firstError('owner_team')}>
                <input
                  type="text"
                  value={form.owner_team}
                  onChange={(e) => update('owner_team', e.target.value)}
                  className={inputClass(!!firstError('owner_team'))}
                />
              </Field>
              <Field label="Lifecycle status" error={firstError('status')}>
                <select
                  value={form.status}
                  onChange={(e) => update('status', e.target.value as ItemStatus)}
                  className={inputClass(!!firstError('status'))}
                >
                  <option value="active">active</option>
                  <option value="deprecated">deprecated</option>
                </select>
              </Field>
            </div>
            {form.status === 'deprecated' && item?.status !== 'deprecated' && (
              <p className="text-xs text-neutral-500">
                Deprecating retires the item for every engagement but keeps it visible and its decisions resolvable. It
                is not the same as delete.
              </p>
            )}

            <Field label="Excluded project roles (the item never applies to these)" error={firstError('excluded_roles')}>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 rounded border border-neutral-300 p-2">
                {PROJECT_ROLES.map((role) => (
                  <label key={role} className="flex items-center gap-1.5 text-xs text-neutral-700">
                    <input
                      type="checkbox"
                      checked={form.excluded_roles.includes(role)}
                      onChange={() => toggleRole(role)}
                    />
                    <span className="font-mono">{role}</span>
                  </label>
                ))}
              </div>
            </Field>

            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-600">Detection — match (JSON)</label>
              <div className="mb-2 flex flex-wrap items-center gap-2 rounded bg-neutral-50 p-2">
                <input
                  type="text"
                  list="catalog-signal-names"
                  value={helperSignal}
                  onChange={(e) => setHelperSignal(e.target.value)}
                  placeholder="Signal name…"
                  className="min-w-[180px] flex-1 rounded border border-neutral-300 px-2 py-1 font-mono text-xs focus:border-violet-400 focus:outline-none"
                />
                <datalist id="catalog-signal-names">
                  {signals.map((s) => (
                    <option key={s.name} value={s.name}>
                      {`${s.category} · ${s.state === 'ready' ? 'ready' : 'not ready'} · ${s.expected_extractor}`}
                    </option>
                  ))}
                </datalist>
                <select
                  value={helperGroup}
                  onChange={(e) => setHelperGroup(e.target.value as HelperGroup)}
                  className="rounded border border-neutral-300 px-2 py-1 text-xs"
                  aria-label="Group"
                >
                  <option value="all">all</option>
                  <option value="any">any</option>
                  <option value="none">none</option>
                </select>
                <button
                  type="button"
                  onClick={addHelperCondition}
                  disabled={!helperSignal.trim() || !parsed.ok}
                  className="rounded border border-violet-300 px-2 py-1 text-xs font-medium text-violet-600 hover:bg-violet-50 disabled:opacity-40"
                >
                  Add condition
                </button>
                {helperSignal.trim() && signals.length > 0 && !signalsByName.has(helperSignal.trim()) && (
                  <p className="w-full text-[11px] text-amber-700">
                    Not a registered signal — the item will be accepted but stay not ready (signal_not_registered).
                  </p>
                )}
                {helperSignal.trim() && signalsByName.get(helperSignal.trim())?.description && (
                  <p className="w-full text-[11px] text-neutral-500">{signalsByName.get(helperSignal.trim())?.description}</p>
                )}
              </div>
              <textarea
                value={form.matchText}
                onChange={(e) => update('matchText', e.target.value)}
                rows={12}
                spellCheck={false}
                className={`${inputClass(!parsed.ok || matchErrors.length > 0)} font-mono text-xs`}
              />
              {!parsed.ok && <p className="mt-1 text-xs text-red-600">{parsed.error}</p>}
              {parsed.ok && parsed.unknownKeys.length > 0 && (
                <p className="mt-1 text-xs text-amber-700">
                  Unknown group(s): {parsed.unknownKeys.join(', ')}. Only all, any, atLeast, none and metadata are allowed —
                  there is no supporting group and no weights.
                </p>
              )}
              {matchErrors.map((e, i) => (
                <p key={i} className="mt-1 text-xs text-red-600">
                  <span className="font-mono">{e.field}</span>: {e.message}
                </p>
              ))}
              <p className="mt-1 text-[11px] leading-snug text-neutral-400">
                Groups: <code>all</code>, <code>any</code>, <code>none</code> take{' '}
                <code>{'{ "id": "…", "signal": { "name": "…", "value": { "equals" | "in" | "startsWith" | "contains" | "regex": … }, "minimumOccurrences": n } }'}</code>
                ; <code>atLeast</code> takes <code>{'{ "id", "count", "of": [ … ] }'}</code>; <code>metadata</code> takes{' '}
                <code>{'{ "id", "field", "equals" | "in" | "notEquals" | "notIn" | … }'}</code>.
              </p>
            </div>

            {form.scope === 'occurrence' ? (
              <div className="rounded border border-neutral-200 p-3">
                <p className="mb-2 text-xs font-medium text-neutral-600">
                  Occurrence source (required for occurrence scope)
                </p>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Signal (from all / any / atLeast)" error={firstError('detection.occurrence_source.signal')}>
                    <select
                      value={form.occurrenceSignal}
                      onChange={(e) => update('occurrenceSignal', e.target.value)}
                      className={`${inputClass(occurrenceErrors.length > 0)} font-mono text-xs`}
                    >
                      <option value="">— choose —</option>
                      {positiveNames.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                      {form.occurrenceSignal && !positiveNames.includes(form.occurrenceSignal) && (
                        <option value={form.occurrenceSignal}>{form.occurrenceSignal} (not in a positive group)</option>
                      )}
                    </select>
                  </Field>
                  <Field label="Group by" error={firstError('detection.occurrence_source.group_by')}>
                    <select
                      value={form.groupBy}
                      onChange={(e) => update('groupBy', e.target.value as OccurrenceGroupBy)}
                      className={inputClass(false)}
                    >
                      <option value="source_path">source_path — one per file</option>
                      <option value="source_path_and_value">source_path_and_value — one per value per file</option>
                    </select>
                  </Field>
                </div>
                {occurrenceErrors
                  .filter((e) => e.field === 'detection.occurrence_source')
                  .map((e, i) => (
                    <p key={i} className="mt-1 text-xs text-red-600">
                      {e.message}
                    </p>
                  ))}
                {!form.occurrenceSignal && (
                  <p className="mt-2 text-xs text-amber-700">
                    Choose which signal's evidence defines the item's locations. It must be named in match.all, match.any
                    or match.atLeast — not match.none.
                  </p>
                )}
                {form.occurrenceSignal && !positiveNames.includes(form.occurrenceSignal) && (
                  <p className="mt-2 text-xs text-amber-700">
                    {form.occurrenceSignal} no longer appears in a positive group; the API will reject this.
                  </p>
                )}
                {form.occurrenceSignal && signalsByName.get(form.occurrenceSignal)?.evidence_kind === 'NONE' && (
                  <p className="mt-2 text-xs text-amber-700">
                    This signal has evidence_kind NONE — its evidence carries no location; the API will reject it.
                  </p>
                )}
              </div>
            ) : (
              <>
                <p className="text-xs text-neutral-400">
                  Application scope has no occurrence projection — the project is the unit.
                </p>
                {occurrenceErrors.map((e, i) => (
                  <p key={i} className="text-xs text-red-600">
                    {e.message}
                  </p>
                ))}
              </>
            )}
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
              {submitting ? 'Saving…' : mode === 'create' ? 'Create item' : 'Save changes'}
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
