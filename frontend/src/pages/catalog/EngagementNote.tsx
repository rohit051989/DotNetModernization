import { useState } from 'react'
import { putResolutionNote, type ResolutionNote } from '../../api/engagementGuidance'
import { ApiError } from '../../api/client'
import { useToast } from '../../components/Toast'
import { fieldErrorMap } from './itemHelpers'

interface EngagementNoteProps {
  engagementId: string
  resolutionId: string
  note: ResolutionNote | undefined
  isAdmin: boolean
  onSaved: (note: ResolutionNote) => void
}

/** The engagement's note on a resolution, on the engagement's view of the catalog. It never replaces the master
 * guidance: a conversion's work item carries the master text, then "For this engagement:" and this note, which takes
 * precedence where the two conflict. Admins edit it; an edit made from a stale copy is refused. */
export function EngagementNote({ engagementId, resolutionId, note, isAdmin, onSaved }: EngagementNoteProps) {
  const { showToast } = useToast()
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState(note?.note ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const saved = await putResolutionNote(engagementId, resolutionId, text.trim() || null, note?.version ?? 0)
      setEditing(false)
      onSaved(saved)
      showToast('success', saved.note ? 'Engagement note saved.' : 'Engagement note cleared.')
    } catch (err) {
      if (err instanceof ApiError) {
        setError(fieldErrorMap(err).note ?? err.message)
      } else {
        setError('Could not save the engagement note.')
      }
    } finally {
      setBusy(false)
    }
  }

  if (!editing) {
    return (
      <div className="rounded border border-dashed border-sky-200 bg-sky-50/40 px-3 py-2 text-xs text-neutral-700" data-testid="engagement-note">
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium text-sky-800">For this engagement</span>
          {isAdmin && (
            <button type="button" onClick={() => { setText(note?.note ?? ''); setEditing(true) }}
              className="rounded border border-sky-200 px-2 py-0.5 text-xs text-sky-700 hover:bg-sky-100">
              {note?.note ? 'Edit note' : 'Add note'}
            </button>
          )}
        </div>
        {note?.note ? (
          <p className="mt-1 whitespace-pre-wrap">{note.note}</p>
        ) : (
          <p className="mt-1 text-neutral-400">No engagement note: conversions use the master guidance alone.</p>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-2 rounded border border-sky-300 bg-white px-3 py-2 text-xs">
      <label htmlFor={`note-${resolutionId}`} className="block font-medium text-sky-800">
        For this engagement
      </label>
      <textarea id={`note-${resolutionId}`} aria-label="Engagement note" rows={5} value={text}
        onChange={(e) => setText(e.target.value)}
        className={`w-full rounded border px-2 py-1 font-mono text-xs ${error ? 'border-red-400' : 'border-neutral-300'}`} />
      <p className="text-neutral-500">
        Added after the master guidance in this engagement's work items, and followed where the two disagree. Written for
        the conversion engine: no platform names or paths, no secret values.
      </p>
      {error && <p className="text-red-600" role="alert">{error}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={busy} onClick={save}
          className="rounded bg-sky-700 px-2 py-1 text-xs font-medium text-white hover:bg-sky-800 disabled:opacity-50">
          Save note
        </button>
        <button type="button" disabled={busy} onClick={() => { setEditing(false); setError(null) }}
          className="rounded border border-neutral-300 px-2 py-1 text-xs text-neutral-700 hover:bg-neutral-50">
          Cancel
        </button>
      </div>
    </div>
  )
}
