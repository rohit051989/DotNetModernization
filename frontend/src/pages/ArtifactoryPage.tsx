import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  addArtifactory,
  editArtifactory,
  getCredentialsStatus,
  listArtifactories,
  removeArtifactory,
  testArtifactoryConnection,
  type ConnectionResult,
  type EngagementArtifactory,
} from '../api/artifactory'
import { ApiError } from '../api/client'
import { ADMIN_ONLY, useIsAdmin } from '../auth/AuthContext'
import { Field, inputClass } from '../components/FormField'
import { LimitedList } from '../components/LimitedList'
import { useToast } from '../components/Toast'

type FieldErrors = { url?: string; name?: string }

function fieldErrors(err: unknown): FieldErrors | null {
  if (!(err instanceof ApiError) || !err.fieldErrors.length) return null
  const next: FieldErrors = {}
  for (const f of err.fieldErrors) {
    if (f.field === 'url' || f.field === 'name') next[f.field] = f.message
  }
  return next
}

/** What Test connection found: the answer, the login it was asked with, and from which machine. Never a value. */
export function ConnectionAnswer({ result }: { result: ConnectionResult | 'testing' | { error: string } }) {
  if (result === 'testing') return <p className="mt-1 text-xs text-neutral-500">Asking the artifactory from this machine…</p>
  if ('error' in result) return <p className="mt-1 text-xs text-red-700" data-testid="connection-answer">{result.error}</p>
  return (
    <p className={`mt-1 text-xs ${result.ok ? 'text-teal-700' : 'text-red-700'}`} data-testid="connection-answer">
      {result.ok ? 'Answered' : result.answer.charAt(0).toUpperCase() + result.answer.slice(1)} · login: {result.login} · asked from{' '}
      {result.machine}
    </p>
  )
}

/** The Artifactory repositories an engagement's scans ask, beside the ones a repository's NuGet.config declares
 * (docs/39-ARTIFACTORY.md). The list is shared by everyone on the database. No password is taken here: an artifactory's
 * login comes from NuGet.config, else from the environment of the machine that scans. Test connection asks from the
 * person's own backend, with that machine's login; an admin may change a saved artifactory's URL. */
export function ArtifactoryPage({ engagementId }: { engagementId: string }) {
  const { showToast } = useToast()
  const isAdmin = useIsAdmin()
  const [artifactories, setArtifactories] = useState<EngagementArtifactory[] | null>(null)
  const [machineLogin, setMachineLogin] = useState<'token' | 'username and password' | 'none' | null>(null)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [busy, setBusy] = useState(false)
  // Test connection's answer, by artifactory id ('new' for the URL being added).
  const [answers, setAnswers] = useState<Record<string, ConnectionResult | 'testing' | { error: string }>>({})
  const [editing, setEditing] = useState<{ id: string; url: string; name: string; errors: FieldErrors } | null>(null)

  const reload = useCallback(() => {
    listArtifactories(engagementId).then(setArtifactories, () => setArtifactories([]))
    getCredentialsStatus(engagementId).then(
      (s) => setMachineLogin(s.machine_login ? (s.method && s.method !== 'none' ? s.method : 'username and password') : 'none'),
      () => setMachineLogin(null),
    )
  }, [engagementId])

  useEffect(reload, [reload])

  async function add(event: FormEvent) {
    event.preventDefault()
    setErrors({})
    setBusy(true)
    try {
      const added = await addArtifactory(engagementId, { url: url.trim(), name: name.trim() || undefined })
      showToast('success', added.warning ? 'Artifactory added, with a warning: see it in the list.' : 'Artifactory added. Rescan a repository to use it.')
      setUrl('')
      setName('')
      setAnswers((a) => {
        const next = { ...a }
        delete next.new
        return next
      })
      reload()
    } catch (err) {
      const found = fieldErrors(err)
      if (found) setErrors(found)
      else showToast('error', err instanceof ApiError ? err.message : 'Could not add the artifactory.')
    } finally {
      setBusy(false)
    }
  }

  async function test(key: string, target: string) {
    setAnswers((a) => ({ ...a, [key]: 'testing' }))
    try {
      const result = await testArtifactoryConnection(engagementId, target.trim())
      setAnswers((a) => ({ ...a, [key]: result }))
    } catch (err) {
      setAnswers((a) => ({ ...a, [key]: { error: err instanceof ApiError ? err.message : 'Could not test the connection.' } }))
    }
  }

  async function saveEdit(artifactory: EngagementArtifactory) {
    if (!editing) return
    try {
      await editArtifactory(engagementId, artifactory, { url: editing.url.trim(), name: editing.name.trim() || undefined })
      showToast('success', `${editing.name.trim() || artifactory.name} saved. Rescan a repository to use it.`)
      setEditing(null)
      reload()
    } catch (err) {
      const found = fieldErrors(err)
      if (found) setEditing({ ...editing, errors: found })
      else showToast('error', err instanceof ApiError ? err.message : 'Could not save the artifactory.')
    }
  }

  async function remove(artifactory: EngagementArtifactory) {
    if (!window.confirm(`Remove ${artifactory.name}? Later scans stop asking it. You can add it again.`)) return
    try {
      await removeArtifactory(engagementId, artifactory.id)
      showToast('success', `${artifactory.name} removed.`)
      reload()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not remove the artifactory.')
    }
  }

  const button = 'rounded border px-2 py-1 text-xs disabled:cursor-not-allowed disabled:opacity-50'
  const newAnswer = answers.new

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      <div>
        <h2 className="text-lg font-semibold">Artifactory</h2>
        <p className="mt-1 text-sm text-neutral-600">
          Artifactory repositories this engagement&apos;s scans ask, beside the ones each repository&apos;s NuGet.config declares.
        </p>
        <p className="mt-2 text-xs text-neutral-500" data-testid="machine-login">
          {machineLogin === null
            ? ''
            : machineLogin === 'token'
              ? 'This machine has an artifactory login in its environment: a token (ARTIFACTORY_TOKEN).'
              : machineLogin === 'username and password'
                ? 'This machine has an artifactory login in its environment: a username and password.'
                : 'This machine has no ARTIFACTORY_TOKEN, and no ARTIFACTORY_USERNAME and ARTIFACTORY_PASSWORD: artifactories NuGet.config does not authenticate are asked anonymously.'}
        </p>
      </div>

      <form onSubmit={add} className="grid gap-3 rounded border border-neutral-200 p-4 sm:grid-cols-[2fr_1fr_auto] sm:items-start">
        <Field label="Artifactory URL" error={errors.url}>
          <input
            className={inputClass(!!errors.url)}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://host/artifactory/api/nuget/v3/<repository-key>/index.json"
            aria-label="Artifactory URL"
          />
          <p className="mt-1 text-xs text-neutral-500">
            The repository&apos;s NuGet v3 URL (its Set Me Up page shows it), not the Artifactory web page (…/ui/…).
          </p>
          {newAnswer && <ConnectionAnswer result={newAnswer} />}
          <p className="mt-2 rounded border border-amber-300 bg-amber-50 px-2 py-1.5 text-xs text-amber-800" data-testid="credentials-note">
            Set <strong>ARTIFACTORY_TOKEN</strong>, or <strong>ARTIFACTORY_USERNAME</strong> and <strong>ARTIFACTORY_PASSWORD</strong>, in
            this machine&apos;s environment or in <code>backend/.env</code> if the artifactory needs a login. A token wins over a
            username and password. If the artifactory is already in NuGet.config with its credentials,
            you can ignore this.
          </p>
        </Field>
        <Field label="Name (optional)" error={errors.name}>
          <input className={inputClass(!!errors.name)} value={name} onChange={(e) => setName(e.target.value)} aria-label="Name" />
        </Field>
        <div className="flex gap-2 sm:flex-col sm:pt-5">
          <button
            type="submit"
            disabled={busy || !url.trim()}
            className="rounded bg-violet-600 px-4 py-1.5 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add artifactory
          </button>
          <button
            type="button"
            disabled={!url.trim() || newAnswer === 'testing'}
            onClick={() => test('new', url)}
            className={`${button} border-neutral-300 text-neutral-700`}
          >
            Test connection
          </button>
        </div>
      </form>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-neutral-700">Artifactories ({artifactories?.length ?? 0})</h3>
        {artifactories === null ? (
          <p className="text-sm text-neutral-500">Loading…</p>
        ) : artifactories.length === 0 ? (
          <p className="text-sm text-neutral-500">No artifactories added yet. Scans use only what each repository&apos;s NuGet.config declares.</p>
        ) : (
          <LimitedList items={artifactories} name={(f) => [f.name, f.url]} noun="artifactories">
            {(visible) => (
              <ul>
                {visible.map((artifactory) => {
                  const answer = answers[artifactory.id]
                  const edit = editing?.id === artifactory.id ? editing : null
                  return (
                    <li key={artifactory.id} className="border-b border-neutral-100 py-2 text-sm">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0 flex-1">
                          {edit ? (
                            <div className="grid gap-2 sm:grid-cols-[2fr_1fr]">
                              <Field label="URL" error={edit.errors.url}>
                                <input
                                  className={inputClass(!!edit.errors.url)}
                                  value={edit.url}
                                  onChange={(e) => setEditing({ ...edit, url: e.target.value })}
                                  aria-label={`URL of ${artifactory.name}`}
                                />
                              </Field>
                              <Field label="Name" error={edit.errors.name}>
                                <input
                                  className={inputClass(!!edit.errors.name)}
                                  value={edit.name}
                                  onChange={(e) => setEditing({ ...edit, name: e.target.value })}
                                  aria-label={`Name of ${artifactory.name}`}
                                />
                              </Field>
                            </div>
                          ) : (
                            <>
                              <div className="font-medium">{artifactory.name}</div>
                              <div className="truncate text-xs text-neutral-500" title={artifactory.url}>{artifactory.url}</div>
                              {artifactory.created_by && <div className="text-xs text-neutral-400">added by {artifactory.created_by}</div>}
                              {artifactory.updated_by && <div className="text-xs text-neutral-400">changed by {artifactory.updated_by}</div>}
                            </>
                          )}
                          {artifactory.warning && !edit && (
                            <p className="mt-1 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-xs text-amber-800" data-testid="url-warning">
                              {artifactory.warning}
                            </p>
                          )}
                          {answer && <ConnectionAnswer result={answer} />}
                        </div>
                        <div className="flex shrink-0 gap-2">
                          {edit ? (
                            <>
                              <button type="button" onClick={() => saveEdit(artifactory)} className={`${button} border-violet-300 text-violet-700`}>
                                Save
                              </button>
                              <button type="button" onClick={() => setEditing(null)} className={`${button} border-neutral-300 text-neutral-700`}>
                                Cancel
                              </button>
                            </>
                          ) : (
                            <>
                              <button
                                type="button"
                                disabled={answer === 'testing'}
                                onClick={() => test(artifactory.id, artifactory.url)}
                                className={`${button} border-neutral-300 text-neutral-700`}
                              >
                                Test connection
                              </button>
                              <button
                                type="button"
                                disabled={!isAdmin}
                                title={isAdmin ? undefined : ADMIN_ONLY}
                                onClick={() => setEditing({ id: artifactory.id, url: artifactory.url, name: artifactory.name, errors: {} })}
                                className={`${button} border-neutral-300 text-neutral-700`}
                              >
                                Edit
                              </button>
                              <button type="button" onClick={() => remove(artifactory)} className={`${button} border-red-300 text-red-600`}>
                                Remove
                              </button>
                            </>
                          )}
                        </div>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </LimitedList>
        )}
      </section>
    </div>
  )
}
