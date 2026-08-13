import { useState } from 'react'
import type { DetectionRulesInput } from '../../types/catalog'
import { TagInput } from '../../components/TagInput'

interface DetectionRulesEditorProps {
  value: DetectionRulesInput
  onChange: (value: DetectionRulesInput) => void
}

const ARRAY_FIELDS: { key: keyof DetectionRulesInput; label: string; placeholder: string }[] = [
  { key: 'target_frameworks', label: 'Target frameworks', placeholder: 'e.g. net472' },
  { key: 'required_namespaces', label: 'Required namespaces', placeholder: 'e.g. System.Web.Mvc' },
  { key: 'forbidden_namespaces', label: 'Forbidden namespaces', placeholder: 'e.g. System.ServiceModel' },
  { key: 'required_packages', label: 'Required packages', placeholder: 'e.g. Microsoft.AspNetCore.Mvc' },
  { key: 'file_globs', label: 'File globs', placeholder: 'e.g. **/*.aspx' },
  { key: 'forbidden_file_globs', label: 'Forbidden file globs', placeholder: 'e.g. **/*.svc' },
  { key: 'config_markers', label: 'Config markers', placeholder: 'e.g. system.web' },
]

function arrayOrEmpty(value: unknown): string[] {
  return Array.isArray(value) ? (value as string[]) : []
}

/** Structured editor for the 7 array fields, notes and confidence_weight, plus a
 * raw-JSON escape hatch. `project_properties` has no dedicated control here — it
 * is preserved untouched on every structured edit and only reachable via raw JSON,
 * so round-tripping through the structured editor never drops it. */
export function DetectionRulesEditor({ value, onChange }: DetectionRulesEditorProps) {
  const [rawMode, setRawMode] = useState(false)
  const [rawText, setRawText] = useState(() => JSON.stringify(value, null, 2))
  const [rawError, setRawError] = useState<string | null>(null)

  function toggleRawMode() {
    if (!rawMode) {
      setRawText(JSON.stringify(value, null, 2))
      setRawError(null)
    }
    setRawMode((current) => !current)
  }

  function handleRawBlur() {
    try {
      const parsed = JSON.parse(rawText)
      onChange(parsed)
      setRawError(null)
    } catch {
      setRawError('Invalid JSON — changes were not applied.')
    }
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-medium text-neutral-600">Detection rules</p>
        <button
          type="button"
          onClick={toggleRawMode}
          className="text-xs font-medium text-violet-600 hover:text-violet-700"
        >
          {rawMode ? 'Back to structured editor' : 'Edit raw JSON'}
        </button>
      </div>

      {rawMode ? (
        <div>
          <textarea
            value={rawText}
            onChange={(event) => setRawText(event.target.value)}
            onBlur={handleRawBlur}
            rows={16}
            spellCheck={false}
            className="w-full rounded border border-neutral-300 p-2 font-mono text-xs text-neutral-800 focus:border-violet-400 focus:outline-none"
          />
          {rawError && <p className="mt-1 text-xs text-red-600">{rawError}</p>}
        </div>
      ) : (
        <div className="space-y-3">
          {ARRAY_FIELDS.map(({ key, label, placeholder }) => (
            <TagInput
              key={key}
              label={label}
              values={arrayOrEmpty(value[key])}
              placeholder={placeholder}
              onChange={(values) => onChange({ ...value, [key]: values })}
            />
          ))}

          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-600">Notes</label>
            <textarea
              value={typeof value.notes === 'string' ? value.notes : ''}
              onChange={(event) => onChange({ ...value, notes: event.target.value || null })}
              rows={2}
              className="w-full rounded border border-neutral-300 p-2 text-sm focus:border-violet-400 focus:outline-none"
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-neutral-600">Confidence weight</label>
            <input
              type="number"
              step="0.1"
              value={value.confidence_weight}
              onChange={(event) => onChange({ ...value, confidence_weight: Number(event.target.value) })}
              className="w-24 rounded border border-neutral-300 px-2 py-1 text-sm focus:border-violet-400 focus:outline-none"
            />
          </div>
        </div>
      )}
    </div>
  )
}
