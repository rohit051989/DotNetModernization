import { useState, type FormEvent } from 'react'
import { createPattern, updatePattern } from '../../api/catalog'
import { ApiError } from '../../api/client'
import { Drawer } from '../../components/Drawer'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Field, inputClass } from '../../components/FormField'
import { useToast } from '../../components/Toast'
import type { DetectionRulesInput, LifecycleStatus, PatternDetail as PatternDetailModel } from '../../types/catalog'
import { DetectionRulesEditor } from './DetectionRulesEditor'

const CATEGORIES = ['web-api', 'web-ui', 'service', 'batch', 'library', 'data-etl']
const STATUSES: LifecycleStatus[] = ['draft', 'active', 'deprecated']
const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/
const SLUG_HINT = "Must be lowercase, hyphenated (e.g. 'wcf-iis-servicemodel')."

function emptyDetectionRules(): DetectionRulesInput {
  return {
    target_frameworks: [],
    required_namespaces: [],
    forbidden_namespaces: [],
    required_packages: [],
    file_globs: [],
    forbidden_file_globs: [],
    project_properties: {},
    config_markers: [],
    confidence_weight: 1,
    notes: null,
  }
}

interface PatternFormState {
  id: string
  name: string
  summary: string
  description: string
  legacy_stack: string
  category: string
  typical_indicators: string
  known_risks: string
  status: LifecycleStatus
  detection_rules: DetectionRulesInput
}

function toFormState(pattern?: PatternDetailModel): PatternFormState {
  if (!pattern) {
    return {
      id: '',
      name: '',
      summary: '',
      description: '',
      legacy_stack: '',
      category: CATEGORIES[0],
      typical_indicators: '',
      known_risks: '',
      status: 'active',
      detection_rules: emptyDetectionRules(),
    }
  }
  return {
    id: pattern.id,
    name: pattern.name,
    summary: pattern.summary,
    description: pattern.description ?? '',
    legacy_stack: pattern.legacy_stack,
    category: pattern.category,
    typical_indicators: pattern.typical_indicators ?? '',
    known_risks: pattern.known_risks ?? '',
    status: pattern.status,
    detection_rules: pattern.detection_rules,
  }
}

interface PatternFormProps {
  mode: 'create' | 'edit'
  pattern?: PatternDetailModel
  onClose: () => void
  onSaved: (patternId: string) => void
}

export function PatternForm({ mode, pattern, onClose, onSaved }: PatternFormProps) {
  const { showToast } = useToast()
  const [form, setForm] = useState<PatternFormState>(() => toFormState(pattern))
  const [dirty, setDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false)

  function update<K extends keyof PatternFormState>(key: K, value: PatternFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }))
    setDirty(true)
  }

  const idError = mode === 'create' && form.id !== '' && !SLUG_PATTERN.test(form.id) ? SLUG_HINT : undefined

  function requestClose() {
    if (dirty) setShowDiscardConfirm(true)
    else onClose()
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()

    if (mode === 'create' && (!form.id || !SLUG_PATTERN.test(form.id))) {
      setFieldErrors({ id: SLUG_HINT })
      return
    }

    setSubmitting(true)
    setFieldErrors({})
    setFormError(null)

    const payload = {
      name: form.name,
      summary: form.summary,
      description: form.description || null,
      legacy_stack: form.legacy_stack,
      category: form.category,
      detection_rules: form.detection_rules,
      typical_indicators: form.typical_indicators || null,
      known_risks: form.known_risks || null,
      status: form.status,
    }

    try {
      const saved =
        mode === 'create'
          ? await createPattern({ id: form.id, ...payload })
          : await updatePattern(pattern!.id, payload)
      showToast('success', `Pattern "${saved.name}" ${mode === 'create' ? 'created' : 'updated'}.`)
      onSaved(saved.id)
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
      <Drawer title={mode === 'create' ? 'New pattern' : `Edit ${pattern?.name}`} onRequestClose={requestClose}>
        <form onSubmit={handleSubmit} className="flex h-full flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto pb-4">
            {formError && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</p>}

            <Field label="ID (slug)" error={fieldErrors.id ?? idError}>
              <input
                type="text"
                value={form.id}
                disabled={mode === 'edit'}
                onChange={(event) => update('id', event.target.value)}
                placeholder="wcf-iis-servicemodel"
                className={`${inputClass(!!(fieldErrors.id ?? idError))} disabled:bg-neutral-50 disabled:text-neutral-500`}
              />
            </Field>

            <Field label="Name" error={fieldErrors.name}>
              <input
                type="text"
                value={form.name}
                onChange={(event) => update('name', event.target.value)}
                required
                className={inputClass(!!fieldErrors.name)}
              />
            </Field>

            <Field label="Summary" error={fieldErrors.summary}>
              <input
                type="text"
                value={form.summary}
                onChange={(event) => update('summary', event.target.value)}
                required
                className={inputClass(!!fieldErrors.summary)}
              />
            </Field>

            <Field label="Description" error={fieldErrors.description}>
              <textarea
                value={form.description}
                onChange={(event) => update('description', event.target.value)}
                rows={4}
                className={inputClass(!!fieldErrors.description)}
              />
            </Field>

            <Field label="Legacy stack" error={fieldErrors.legacy_stack}>
              <input
                type="text"
                value={form.legacy_stack}
                onChange={(event) => update('legacy_stack', event.target.value)}
                required
                className={inputClass(!!fieldErrors.legacy_stack)}
              />
            </Field>

            <Field label="Category" error={fieldErrors.category}>
              <select
                value={form.category}
                onChange={(event) => update('category', event.target.value)}
                className={inputClass(!!fieldErrors.category)}
              >
                {CATEGORIES.map((category) => (
                  <option key={category} value={category}>
                    {category}
                  </option>
                ))}
              </select>
            </Field>

            <Field label="Typical indicators" error={fieldErrors.typical_indicators}>
              <textarea
                value={form.typical_indicators}
                onChange={(event) => update('typical_indicators', event.target.value)}
                rows={2}
                className={inputClass(!!fieldErrors.typical_indicators)}
              />
            </Field>

            <Field label="Known risks" error={fieldErrors.known_risks}>
              <textarea
                value={form.known_risks}
                onChange={(event) => update('known_risks', event.target.value)}
                rows={2}
                className={inputClass(!!fieldErrors.known_risks)}
              />
            </Field>

            <Field label="Status" error={fieldErrors.status}>
              <select
                value={form.status}
                onChange={(event) => update('status', event.target.value as LifecycleStatus)}
                className={inputClass(!!fieldErrors.status)}
              >
                {STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </Field>

            <div className="border-t border-neutral-200 pt-4">
              <DetectionRulesEditor
                value={form.detection_rules}
                onChange={(value) => update('detection_rules', value)}
              />
              {fieldErrors.detection_rules && (
                <p className="mt-1 text-xs text-red-600">{fieldErrors.detection_rules}</p>
              )}
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
              {mode === 'create' ? 'Create pattern' : 'Save changes'}
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
