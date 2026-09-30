import { useState, type FormEvent } from 'react'
import { createResolution, updateResolution } from '../../api/items'
import { ApiError } from '../../api/client'
import { Drawer } from '../../components/Drawer'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Field, inputClass } from '../../components/FormField'
import { useToast } from '../../components/Toast'
import type { ConsumerImpact, EffortLevel } from '../../types/catalog'
import type { ItemResolution, ItemStatus, ResolutionWriteInput } from '../../types/items'
import { fieldErrorMap, slugify } from './itemHelpers'

const IMPACTS: ConsumerImpact[] = ['none', 'low', 'medium', 'high']
const EFFORTS: EffortLevel[] = ['low', 'medium', 'high']

interface ResolutionFormProps {
  mode: 'create' | 'edit'
  itemId: string
  resolution?: ItemResolution
  /** The item's current default, if another resolution holds it. */
  existingDefault: ItemResolution | null
  onClose: () => void
  onSaved: () => void
}

interface FormState {
  id: string
  name: string
  description: string
  target_description: string
  consumer_impact: ConsumerImpact
  effort: EffortLevel
  is_default: boolean
  linux_compatible: boolean
  container_ready: boolean
  notes: string
  status: ItemStatus
}

function toFormState(resolution?: ItemResolution): FormState {
  return {
    id: resolution?.id ?? '',
    name: resolution?.name ?? '',
    description: resolution?.description ?? '',
    target_description: resolution?.target_description ?? '',
    consumer_impact: resolution?.consumer_impact ?? 'low',
    effort: resolution?.effort ?? 'medium',
    is_default: resolution?.is_default ?? false,
    linux_compatible: resolution?.linux_compatible ?? true,
    container_ready: resolution?.container_ready ?? true,
    notes: resolution?.notes ?? '',
    status: resolution?.status ?? 'active',
  }
}

export function ResolutionForm({ mode, itemId, resolution, existingDefault, onClose, onSaved }: ResolutionFormProps) {
  const { showToast } = useToast()
  const [form, setForm] = useState<FormState>(() => toFormState(resolution))
  const [idTouched, setIdTouched] = useState(mode === 'edit')
  const [dirty, setDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false)

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => {
      const next = { ...current, [key]: value }
      // Resolution ids are global, so suggest `<item-id>-<slug>`.
      if (key === 'name' && mode === 'create' && !idTouched) {
        const slug = slugify(String(value))
        next.id = slug ? `${itemId}-${slug}` : ''
      }
      return next
    })
    setDirty(true)
  }

  function requestClose() {
    if (dirty) setShowDiscardConfirm(true)
    else onClose()
  }

  const otherDefault = existingDefault && existingDefault.id !== resolution?.id ? existingDefault : null

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    // TODO: gate behind an admin check once auth exists (04-FRONTEND-SPEC.md,
    // "Future: access control") — creating or editing a resolution is a
    // master-scoped mutation.
    setSubmitting(true)
    setFieldErrors({})
    const payload: ResolutionWriteInput = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      target_description: form.target_description.trim() || null,
      consumer_impact: form.consumer_impact,
      effort: form.effort,
      is_default: form.is_default,
      linux_compatible: form.linux_compatible,
      container_ready: form.container_ready,
      notes: form.notes.trim() || null,
      status: form.status,
    }
    try {
      if (mode === 'create') await createResolution(itemId, { id: form.id.trim(), ...payload })
      else await updateResolution(itemId, resolution!.id, payload)
      showToast('success', mode === 'create' ? 'Resolution added.' : 'Resolution saved.')
      onSaved()
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

  return (
    <>
      <Drawer title={mode === 'create' ? 'Add resolution' : `Edit ${resolution?.name ?? 'resolution'}`} onRequestClose={requestClose}>
        <form onSubmit={handleSubmit} className="flex h-full flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto pb-4">
            {fieldErrors.__root__ && (
              <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{fieldErrors.__root__}</p>
            )}

            <Field label="Name" error={fieldErrors.name}>
              <input
                type="text"
                value={form.name}
                onChange={(e) => update('name', e.target.value)}
                className={inputClass(!!fieldErrors.name)}
                required
              />
            </Field>

            {mode === 'create' ? (
              <Field label="Id (global slug — suggested as <item-id>-<name>)" error={fieldErrors.id}>
                <input
                  type="text"
                  value={form.id}
                  onChange={(e) => {
                    setIdTouched(true)
                    update('id', e.target.value)
                  }}
                  className={`${inputClass(!!fieldErrors.id)} font-mono`}
                  required
                />
              </Field>
            ) : (
              <p className="text-xs text-neutral-400">
                Id <span className="font-mono text-neutral-600">{resolution?.id}</span>
              </p>
            )}

            <Field label="Description" error={fieldErrors.description}>
              <textarea
                value={form.description}
                onChange={(e) => update('description', e.target.value)}
                rows={2}
                className={inputClass(!!fieldErrors.description)}
              />
            </Field>

            <Field label="Target description (what the result looks like)" error={fieldErrors.target_description}>
              <textarea
                value={form.target_description}
                onChange={(e) => update('target_description', e.target.value)}
                rows={2}
                className={inputClass(!!fieldErrors.target_description)}
              />
            </Field>

            <div className="grid grid-cols-3 gap-3">
              <Field label="Consumer impact" error={fieldErrors.consumer_impact}>
                <select
                  value={form.consumer_impact}
                  onChange={(e) => update('consumer_impact', e.target.value as ConsumerImpact)}
                  className={inputClass(!!fieldErrors.consumer_impact)}
                >
                  {IMPACTS.map((impact) => (
                    <option key={impact} value={impact}>
                      {impact}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Effort" error={fieldErrors.effort}>
                <select
                  value={form.effort}
                  onChange={(e) => update('effort', e.target.value as EffortLevel)}
                  className={inputClass(!!fieldErrors.effort)}
                >
                  {EFFORTS.map((effort) => (
                    <option key={effort} value={effort}>
                      {effort}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Status" error={fieldErrors.status}>
                <select
                  value={form.status}
                  onChange={(e) => update('status', e.target.value as ItemStatus)}
                  className={inputClass(!!fieldErrors.status)}
                >
                  <option value="active">active</option>
                  <option value="deprecated">deprecated</option>
                </select>
              </Field>
            </div>

            <div className="space-y-2 rounded border border-neutral-200 p-3 text-sm text-neutral-700">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.linux_compatible}
                  onChange={(e) => update('linux_compatible', e.target.checked)}
                />
                Linux-compatible
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.container_ready}
                  onChange={(e) => update('container_ready', e.target.checked)}
                />
                Container-ready
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={form.is_default} onChange={(e) => update('is_default', e.target.checked)} />
                Default resolution for this item
              </label>
              {form.is_default && otherDefault && (
                <p className="text-xs text-amber-700">
                  {otherDefault.name} is currently the default. At most one default per item — unset it first, or use
                  "Make default" on this resolution's card, which moves it for you.
                </p>
              )}
              {fieldErrors.is_default && <p className="text-xs text-red-600">{fieldErrors.is_default}</p>}
            </div>

            <Field label="Notes" error={fieldErrors.notes}>
              <textarea
                value={form.notes}
                onChange={(e) => update('notes', e.target.value)}
                rows={3}
                className={inputClass(!!fieldErrors.notes)}
              />
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
              {submitting ? 'Saving…' : mode === 'create' ? 'Add resolution' : 'Save changes'}
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
