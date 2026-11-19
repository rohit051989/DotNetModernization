import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { addArtifactory, getCredentialsStatus, listArtifactories, removeArtifactory, type EngagementArtifactory } from '../api/artifactory'
import { ApiError } from '../api/client'
import { Field, inputClass } from '../components/FormField'
import { LimitedList } from '../components/LimitedList'
import { useToast } from '../components/Toast'

/** The Artifactory repositories an engagement's scans ask, beside the ones a repository's NuGet.config declares
 * (docs/39-ARTIFACTORY.md). The list is shared by everyone on the database. No password is taken here: an artifactory's
 * login comes from NuGet.config, else from the environment of the machine that scans. */
export function ArtifactoryPage({ engagementId }: { engagementId: string }) {
  const { showToast } = useToast()
  const [artifactories, setArtifactories] = useState<EngagementArtifactory[] | null>(null)
  const [machineLogin, setMachineLogin] = useState<'token' | 'username and password' | 'none' | null>(null)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [errors, setErrors] = useState<{ url?: string; name?: string }>({})
  const [busy, setBusy] = useState(false)

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
      await addArtifactory(engagementId, { url: url.trim(), name: name.trim() || undefined })
      showToast('success', 'Artifactory added. Rescan a repository to use it.')
      setUrl('')
      setName('')
      reload()
    } catch (err) {
      if (err instanceof ApiError && err.fieldErrors.length) {
        const next: { url?: string; name?: string } = {}
        for (const f of err.fieldErrors) {
          if (f.field === 'url' || f.field === 'name') next[f.field] = f.message
        }
        setErrors(next)
      } else {
        showToast('error', err instanceof ApiError ? err.message : 'Could not add the artifactory.')
      }
    } finally {
      setBusy(false)
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
            placeholder="https://host/repository/nuget-private/index.json"
            aria-label="Artifactory URL"
          />
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
        <div className="sm:pt-5">
          <button
            type="submit"
            disabled={busy || !url.trim()}
            className="rounded bg-violet-600 px-4 py-1.5 text-sm text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            Add artifactory
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
                {visible.map((artifactory) => (
                  <li key={artifactory.id} className="flex items-center justify-between gap-3 border-b border-neutral-100 py-2 text-sm">
                    <div className="min-w-0">
                      <div className="font-medium">{artifactory.name}</div>
                      <div className="truncate text-xs text-neutral-500" title={artifactory.url}>{artifactory.url}</div>
                      {artifactory.created_by && <div className="text-xs text-neutral-400">added by {artifactory.created_by}</div>}
                    </div>
                    <button type="button" onClick={() => remove(artifactory)} className="rounded border border-red-300 px-2 py-1 text-xs text-red-600">
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </LimitedList>
        )}
      </section>
    </div>
  )
}
