import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { createEngagement } from '../api/catalog'
import type { Engagement } from '../types/catalog'
import { Drawer } from './Drawer'
import { Field, inputClass } from './FormField'

/** The id a name suggests, as the backend makes it (app/engagements/service.py id_from_name). */
function idFromName(name: string) {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)
    .replace(/-+$/, '')
}

interface NewEngagementDrawerProps {
  onClose: () => void
  onCreated: (engagement: Engagement) => void
}

/** Creates an engagement: its client name, id and the .NET target framework its estate moves to. */
export function NewEngagementDrawer({ onClose, onCreated }: NewEngagementDrawerProps) {
  const [name, setName] = useState('')
  const [id, setId] = useState('')
  const [idEdited, setIdEdited] = useState(false)
  const [targetFramework, setTargetFramework] = useState('net10.0')
  const [targetPlatform, setTargetPlatform] = useState('')
  const [description, setDescription] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)

  const effectiveId = idEdited ? id : idFromName(name)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      const created = await createEngagement({
        id: effectiveId,
        client_name: name,
        target_framework: targetFramework.trim(),
        target_platform: targetPlatform.trim() || null,
        description: description.trim() || null,
      })
      onCreated(created)
    } catch (e) {
      if (e instanceof ApiError && e.fieldErrors.length > 0) {
        setErrors(Object.fromEntries(e.fieldErrors.map((f) => [f.field, f.message])))
      } else {
        setErrors({ __root__: e instanceof Error ? e.message : 'Could not create the engagement.' })
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer title="New engagement" onRequestClose={onClose}>
      <form onSubmit={submit} className="space-y-4">
        <Field label="Client name" error={errors.client_name}>
          <input className={inputClass(!!errors.client_name)} value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Field>
        <Field label="Id" error={errors.id}>
          <input
            className={`${inputClass(!!errors.id)} font-mono`}
            value={effectiveId}
            onChange={(e) => {
              setIdEdited(true)
              setId(e.target.value)
            }}
          />
          <p className="mt-1 text-xs text-neutral-500">Lower-case letters, digits and hyphens. It cannot be changed later.</p>
        </Field>
        <Field label="Target framework" error={errors.target_framework}>
          <input
            className={`${inputClass(!!errors.target_framework)} font-mono`}
            value={targetFramework}
            onChange={(e) => setTargetFramework(e.target.value)}
            list="target-frameworks"
          />
          <datalist id="target-frameworks">
            <option value="net10.0" />
            <option value="net8.0" />
          </datalist>
          <p className="mt-1 text-xs text-neutral-500">The .NET version the estate moves to; every package is checked against it.</p>
        </Field>
        <Field label="Target platform (optional)">
          <input className={inputClass(false)} value={targetPlatform} onChange={(e) => setTargetPlatform(e.target.value)} placeholder="OpenShift 4" />
        </Field>
        <Field label="Description (optional)">
          <textarea className={inputClass(false)} rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>
        {errors.__root__ && <p className="text-sm text-red-600">{errors.__root__}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50">
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving || !name.trim()}
            className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
          >
            {saving ? 'Creating…' : 'Create engagement'}
          </button>
        </div>
      </form>
    </Drawer>
  )
}
