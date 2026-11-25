import { useEffect, useState } from 'react'
import { getConventions, putConventions, type EngagementConventions as Conventions } from '../../api/engagementGuidance'
import { ApiError } from '../../api/client'
import { useIsAdmin } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import { fieldErrorMap } from './itemHelpers'

/** The engagement's conventions (logging, naming, error format and the like), on the engagement's settings: carried in
 * the top-level instructions of every conversion of its repositories, for both engines. The design questions a
 * conversion asks never cover what they decide. Admins edit them; an edit from a stale copy is refused. */
export function EngagementConventions({ engagementId }: { engagementId: string }) {
  const isAdmin = useIsAdmin()
  const { showToast } = useToast()
  const [loaded, setLoaded] = useState<Conventions | null>(null)
  const [text, setText] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let live = true
    getConventions(engagementId)
      .then((c) => { if (live) { setLoaded(c); setText(c.conventions ?? '') } })
      .catch(() => { if (live) setError('Could not load the conventions.') })
    return () => { live = false }
  }, [engagementId])

  async function save() {
    if (!loaded) return
    setBusy(true)
    setError(null)
    try {
      const saved = await putConventions(engagementId, text.trim() || null, loaded.version)
      setLoaded(saved)
      setText(saved.conventions ?? '')
      showToast('success', 'Conventions saved: the next conversion prepared carries them.')
    } catch (err) {
      setError(err instanceof ApiError ? (fieldErrorMap(err).conventions ?? err.message) : 'Could not save the conventions.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="mx-auto max-w-3xl space-y-3 p-6">
      <div>
        <h2 className="text-lg font-semibold text-neutral-900">Conventions</h2>
        <p className="text-sm text-neutral-500">
          This engagement's conventions: logging, naming, the error format and the like. Every conversion of its
          repositories carries them in its top-level instructions, for both engines, and its design questions never ask
          about what they decide. Written for the conversion engine: no platform names or paths, no secret values.
        </p>
      </div>
      <textarea aria-label="Conventions" rows={14} value={text} disabled={!isAdmin || !loaded}
        onChange={(e) => setText(e.target.value)}
        className={`w-full rounded border px-3 py-2 font-mono text-sm ${error ? 'border-red-400' : 'border-neutral-300'}`}
        placeholder="- Log through ILogger, structured, to standard output.&#10;- Errors as RFC 7807 problem details." />
      {error && <p className="text-sm text-red-600" role="alert">{error}</p>}
      {isAdmin ? (
        <button type="button" disabled={busy || !loaded} onClick={save}
          className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50">
          Save conventions
        </button>
      ) : (
        <p className="text-xs text-neutral-500">Only an admin edits the conventions.</p>
      )}
    </section>
  )
}
