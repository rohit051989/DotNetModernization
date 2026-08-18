import { useEffect, useState } from 'react'
import { Drawer } from '../../components/Drawer'
import { Field, inputClass } from '../../components/FormField'
import { useToast } from '../../components/Toast'
import { ApiError } from '../../api/client'
import { listRepositories } from '../../api/repositories'
import { getJobParameters, launchJob } from '../../api/workflow'
import type { RepositorySummary } from '../../types/repositories'
import type { JobExecution, JobParametersResponse } from '../../types/workflow'

interface LaunchJobDrawerProps {
  jobName: string
  engagementId: string
  onClose: () => void
  onLaunched: (execution: JobExecution) => void
}

export function LaunchJobDrawer({ jobName, engagementId, onClose, onLaunched }: LaunchJobDrawerProps) {
  const { showToast } = useToast()
  const [parameters, setParameters] = useState<JobParametersResponse | null>(null)
  const [repositories, setRepositories] = useState<RepositorySummary[]>([])
  const [values, setValues] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    let cancelled = false
    Promise.all([getJobParameters(jobName), listRepositories(engagementId)])
      .then(([paramResult, repoResult]) => {
        if (cancelled) return
        setParameters(paramResult)
        setRepositories(repoResult)
        const initial: Record<string, string> = {}
        for (const param of paramResult.parameters) {
          if (param.name === 'engagement_id') initial[param.name] = engagementId
          else if (param.name === 'ingest_token') initial[param.name] = crypto.randomUUID()
          else if (param.name === 'repository_id') initial[param.name] = repoResult[0]?.id ?? ''
          else if (typeof param.default === 'string') initial[param.name] = param.default
        }
        setValues(initial)
      })
      .catch(() => {
        if (!cancelled) setFormError('Could not load this job’s parameters.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [jobName, engagementId])

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setFormError(null)
    setFieldErrors({})
    setSubmitting(true)
    try {
      const execution = await launchJob(jobName, values)
      showToast('success', `Launched ${jobName} — tracking execution ${execution.id.slice(0, 8)}…`)
      onLaunched(execution)
    } catch (err) {
      if (err instanceof ApiError) {
        const byField: Record<string, string> = {}
        for (const fe of err.fieldErrors) {
          if (fe.field && fe.field !== '__root__') byField[fe.field] = fe.message
        }
        setFieldErrors(byField)
        setFormError(Object.keys(byField).length === 0 ? err.message : null)
      } else {
        setFormError('Could not launch this job.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Drawer title={`Launch ${jobName}`} onRequestClose={onClose}>
      {loading && <p className="text-sm text-neutral-400">Loading parameters…</p>}
      {!loading && !parameters && <p className="text-sm text-red-600">{formError ?? 'Could not load parameters.'}</p>}
      {!loading && parameters && (
        <form onSubmit={handleSubmit} className="space-y-4">
          {parameters.parameters.map((param) => {
            if (param.name === 'repository_id') {
              return (
                <Field key={param.name} label="Repository" error={fieldErrors[param.name]}>
                  <select
                    value={values[param.name] ?? ''}
                    onChange={(event) => setValues((v) => ({ ...v, [param.name]: event.target.value }))}
                    className={inputClass(!!fieldErrors[param.name])}
                  >
                    {repositories.length === 0 && <option value="">No repositories registered</option>}
                    {repositories.map((repo) => (
                      <option key={repo.id} value={repo.id}>
                        {repo.name} ({repo.root_folder_name})
                      </option>
                    ))}
                  </select>
                  {param.description && <p className="mt-1 text-xs text-neutral-400">{param.description}</p>}
                </Field>
              )
            }

            if (param.name === 'ingest_token') {
              return (
                <Field key={param.name} label="Ingest token">
                  <input readOnly value={values[param.name] ?? ''} className={`${inputClass(false)} bg-neutral-50 font-mono text-xs text-neutral-500`} />
                  <p className="mt-1 text-xs text-neutral-400">
                    Generated automatically — each launch is a distinct run, not a restart of a previous one.
                  </p>
                </Field>
              )
            }

            if (param.name === 'engagement_id') {
              return (
                <Field key={param.name} label="Engagement">
                  <input readOnly value={values[param.name] ?? ''} className={`${inputClass(false)} bg-neutral-50 text-neutral-500`} />
                </Field>
              )
            }

            return (
              <Field key={param.name} label={`${param.name}${param.required ? ' *' : ''}`} error={fieldErrors[param.name]}>
                <input
                  value={values[param.name] ?? ''}
                  onChange={(event) => setValues((v) => ({ ...v, [param.name]: event.target.value }))}
                  className={inputClass(!!fieldErrors[param.name])}
                />
                {param.description && <p className="mt-1 text-xs text-neutral-400">{param.description}</p>}
              </Field>
            )
          })}

          {formError && <p className="text-sm text-red-600">{formError}</p>}

          <div className="flex justify-end gap-2 border-t border-neutral-100 pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || repositories.length === 0}
              className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? 'Launching…' : 'Launch'}
            </button>
          </div>
        </form>
      )}
    </Drawer>
  )
}
