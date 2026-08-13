import { useState, type FormEvent } from 'react'
import { createTargetState, updateTargetState } from '../../api/catalog'
import { ApiError } from '../../api/client'
import { Drawer } from '../../components/Drawer'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { Field, inputClass } from '../../components/FormField'
import { TagInput } from '../../components/TagInput'
import { useToast } from '../../components/Toast'
import type {
  ConsumerImpact,
  EffortLevel,
  EngineCoverage,
  EngineSupportInput,
  LifecycleStatus,
  TargetStateDetail,
} from '../../types/catalog'

const CONSUMER_IMPACT_OPTIONS: ConsumerImpact[] = ['none', 'low', 'medium', 'high']
const EFFORT_OPTIONS: EffortLevel[] = ['low', 'medium', 'high']
const COVERAGE_OPTIONS: EngineCoverage[] = ['none', 'partial', 'strong']
const STATUSES: LifecycleStatus[] = ['draft', 'active', 'deprecated']
const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/
const SLUG_HINT = "Must be lowercase, hyphenated (e.g. 'corewcf-net10')."

function emptyEngineSupport(): EngineSupportInput {
  return { engine: null, coverage: null, scenarios: [], skills: [], gaps: [], custom_skills_required: [] }
}

interface TargetStateFormState {
  id: string
  name: string
  summary: string
  target_stack: string
  consumer_impact: ConsumerImpact
  effort: EffortLevel
  linux_compatible: boolean
  container_ready: boolean
  is_lift_and_shift: boolean
  prerequisites: string
  known_limitations: string
  playbook_md: string
  status: LifecycleStatus
  engine_support: EngineSupportInput
}

function toFormState(option?: TargetStateDetail): TargetStateFormState {
  if (!option) {
    return {
      id: '',
      name: '',
      summary: '',
      target_stack: '',
      consumer_impact: 'none',
      effort: 'low',
      linux_compatible: true,
      container_ready: true,
      is_lift_and_shift: false,
      prerequisites: '',
      known_limitations: '',
      playbook_md: '',
      status: 'active',
      engine_support: emptyEngineSupport(),
    }
  }
  return {
    id: option.id,
    name: option.name,
    summary: option.summary,
    target_stack: option.target_stack,
    consumer_impact: option.consumer_impact,
    effort: option.effort,
    linux_compatible: option.linux_compatible,
    container_ready: option.container_ready,
    is_lift_and_shift: option.is_lift_and_shift,
    prerequisites: option.prerequisites ?? '',
    known_limitations: option.known_limitations ?? '',
    playbook_md: option.playbook_md ?? '',
    status: option.status,
    engine_support: option.engine_support ?? emptyEngineSupport(),
  }
}

interface TargetStateFormProps {
  mode: 'create' | 'edit'
  patternId: string
  option?: TargetStateDetail
  onClose: () => void
  onSaved: (targetStateId: string) => void
}

export function TargetStateForm({ mode, patternId, option, onClose, onSaved }: TargetStateFormProps) {
  const { showToast } = useToast()
  const [form, setForm] = useState<TargetStateFormState>(() => toFormState(option))
  const [dirty, setDirty] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false)

  function update<K extends keyof TargetStateFormState>(key: K, value: TargetStateFormState[K]) {
    setForm((current) => ({ ...current, [key]: value }))
    setDirty(true)
  }

  function updateEngineSupport<K extends keyof EngineSupportInput>(key: K, value: EngineSupportInput[K]) {
    setForm((current) => ({ ...current, engine_support: { ...current.engine_support, [key]: value } }))
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

    const engineSupportHasContent =
      form.engine_support.engine ||
      form.engine_support.coverage ||
      form.engine_support.scenarios.length > 0 ||
      form.engine_support.skills.length > 0 ||
      form.engine_support.gaps.length > 0 ||
      form.engine_support.custom_skills_required.length > 0

    const payload = {
      name: form.name,
      summary: form.summary,
      target_stack: form.target_stack,
      consumer_impact: form.consumer_impact,
      effort: form.effort,
      linux_compatible: form.linux_compatible,
      container_ready: form.container_ready,
      is_lift_and_shift: form.is_lift_and_shift,
      engine_support: engineSupportHasContent ? form.engine_support : null,
      playbook_md: form.playbook_md || null,
      prerequisites: form.prerequisites || null,
      known_limitations: form.known_limitations || null,
      status: form.status,
    }

    try {
      const saved =
        mode === 'create'
          ? await createTargetState(patternId, { id: form.id, ...payload })
          : await updateTargetState(option!.id, payload)
      showToast('success', `Target state option "${saved.name}" ${mode === 'create' ? 'created' : 'updated'}.`)
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
      <Drawer
        title={mode === 'create' ? 'New target state option' : `Edit ${option?.name}`}
        onRequestClose={requestClose}
      >
        <form onSubmit={handleSubmit} className="flex h-full flex-col">
          <div className="flex-1 space-y-4 overflow-y-auto pb-4">
            {formError && <p className="rounded bg-red-50 px-3 py-2 text-sm text-red-700">{formError}</p>}

            <Field label="ID (slug)" error={fieldErrors.id ?? idError}>
              <input
                type="text"
                value={form.id}
                disabled={mode === 'edit'}
                onChange={(event) => update('id', event.target.value)}
                placeholder="corewcf-net10"
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

            <Field label="Target stack" error={fieldErrors.target_stack}>
              <input
                type="text"
                value={form.target_stack}
                onChange={(event) => update('target_stack', event.target.value)}
                required
                className={inputClass(!!fieldErrors.target_stack)}
              />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="Consumer impact" error={fieldErrors.consumer_impact}>
                <select
                  value={form.consumer_impact}
                  onChange={(event) => update('consumer_impact', event.target.value as ConsumerImpact)}
                  className={inputClass(!!fieldErrors.consumer_impact)}
                >
                  {CONSUMER_IMPACT_OPTIONS.map((impact) => (
                    <option key={impact} value={impact}>
                      {impact}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Effort" error={fieldErrors.effort}>
                <select
                  value={form.effort}
                  onChange={(event) => update('effort', event.target.value as EffortLevel)}
                  className={inputClass(!!fieldErrors.effort)}
                >
                  {EFFORT_OPTIONS.map((effort) => (
                    <option key={effort} value={effort}>
                      {effort}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="flex flex-wrap gap-4">
              <Toggle
                label="Linux compatible"
                checked={form.linux_compatible}
                onChange={(checked) => update('linux_compatible', checked)}
              />
              <Toggle
                label="Container ready"
                checked={form.container_ready}
                onChange={(checked) => update('container_ready', checked)}
              />
              <Toggle
                label="Lift & shift"
                checked={form.is_lift_and_shift}
                onChange={(checked) => update('is_lift_and_shift', checked)}
              />
            </div>

            <Field label="Prerequisites" error={fieldErrors.prerequisites}>
              <textarea
                value={form.prerequisites}
                onChange={(event) => update('prerequisites', event.target.value)}
                rows={2}
                className={inputClass(!!fieldErrors.prerequisites)}
              />
            </Field>

            <Field label="Known limitations" error={fieldErrors.known_limitations}>
              <textarea
                value={form.known_limitations}
                onChange={(event) => update('known_limitations', event.target.value)}
                rows={2}
                className={inputClass(!!fieldErrors.known_limitations)}
              />
            </Field>

            <Field label="Playbook (markdown)" error={fieldErrors.playbook_md}>
              <textarea
                value={form.playbook_md}
                onChange={(event) => update('playbook_md', event.target.value)}
                rows={8}
                className={`${inputClass(!!fieldErrors.playbook_md)} font-mono`}
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

            <div className="space-y-3 border-t border-neutral-200 pt-4">
              <p className="text-xs font-medium text-neutral-600">Engine support</p>

              <Field label="Engine">
                <input
                  type="text"
                  value={form.engine_support.engine ?? ''}
                  onChange={(event) => updateEngineSupport('engine', event.target.value || null)}
                  className={inputClass(false)}
                />
              </Field>

              <Field label="Coverage">
                <select
                  value={form.engine_support.coverage ?? ''}
                  onChange={(event) =>
                    updateEngineSupport('coverage', (event.target.value || null) as EngineCoverage | null)
                  }
                  className={inputClass(false)}
                >
                  <option value="">—</option>
                  {COVERAGE_OPTIONS.map((coverage) => (
                    <option key={coverage} value={coverage}>
                      {coverage}
                    </option>
                  ))}
                </select>
              </Field>

              <TagInput
                label="Scenarios"
                values={form.engine_support.scenarios}
                onChange={(values) => updateEngineSupport('scenarios', values)}
              />
              <TagInput
                label="Skills"
                values={form.engine_support.skills}
                onChange={(values) => updateEngineSupport('skills', values)}
              />
              <TagInput
                label="Gaps"
                values={form.engine_support.gaps}
                onChange={(values) => updateEngineSupport('gaps', values)}
              />
              <TagInput
                label="Custom skills required"
                values={form.engine_support.custom_skills_required}
                onChange={(values) => updateEngineSupport('custom_skills_required', values)}
              />
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
              {mode === 'create' ? 'Create target state' : 'Save changes'}
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

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (checked: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-neutral-700">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  )
}
