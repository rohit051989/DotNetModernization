import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiError } from '../../api/client'
import { deleteJobDefinitionVersion, getJobDefinitionVersion, listAllJobDefinitions } from '../../api/workflow'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { CopyButton } from '../../components/CopyButton'
import { useToast } from '../../components/Toast'
import type { JobDefinitionAdmin, JobDefinitionFull } from '../../types/workflow'
import { JobDefinitionViewer } from '../workflow/definition/JobDefinitionViewer'

interface SelectedVersion {
  jobName: string
  version: number
  isActive: boolean
  validationStatus: 'valid' | 'invalid'
}

interface StaleActiveWarning {
  jobName: string
  activeVersion: number
  highestVersion: number
}

/** A definition can be stored without being activated — POST .../jobs never
 * requires `activate: true` — which leaves the engine silently running an
 * older version than what's on disk/in git. Surfacing that here means it
 * doesn't have to be noticed by manually comparing version numbers. */
function findStaleActiveWarnings(rows: JobDefinitionAdmin[]): StaleActiveWarning[] {
  const byJob = new Map<string, { highestVersion: number; activeVersion: number | null }>()
  for (const row of rows) {
    const entry = byJob.get(row.job_name) ?? { highestVersion: row.version, activeVersion: null }
    entry.highestVersion = Math.max(entry.highestVersion, row.version)
    if (row.is_active) entry.activeVersion = row.version
    byJob.set(row.job_name, entry)
  }
  return Array.from(byJob.entries())
    .filter(([, v]) => v.activeVersion !== null && v.activeVersion !== v.highestVersion)
    .map(([jobName, v]) => ({ jobName, activeVersion: v.activeVersion as number, highestVersion: v.highestVersion }))
}

/** 23-WORKFLOW-ADMINISTRATION.md Part C2 — every stored job definition
 * version, not just the active one. "A job that failed validation should
 * be visible here rather than only discoverable through an API call." */
export function JobDefinitionsAdminSection() {
  const { showToast } = useToast()
  const [rows, setRows] = useState<JobDefinitionAdmin[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selected, setSelected] = useState<SelectedVersion | null>(null)
  const [discardTarget, setDiscardTarget] = useState<JobDefinitionAdmin | null>(null)
  const [discarding, setDiscarding] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setLoadError(null)
    listAllJobDefinitions()
      .then((data) => {
        setRows(data)
        setSelected((current) => {
          // Keep the current selection if it's still there (e.g. after a
          // discard elsewhere in the list); otherwise fall back to the
          // first row, same as on initial load.
          if (current && data.some((r) => r.job_name === current.jobName && r.version === current.version)) {
            return current
          }
          if (data.length === 0) return null
          const first = data[0]
          return {
            jobName: first.job_name,
            version: first.version,
            isActive: first.is_active,
            validationStatus: first.validation_status,
          }
        })
      })
      .catch(() => setLoadError('Could not load job definitions.'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const staleActiveWarnings = useMemo(() => findStaleActiveWarnings(rows), [rows])
  const highestVersionByStaleJob = useMemo(
    () => new Map(staleActiveWarnings.map((w) => [w.jobName, w.highestVersion])),
    [staleActiveWarnings],
  )

  async function handleConfirmDiscard() {
    if (!discardTarget) return
    setDiscarding(true)
    try {
      await deleteJobDefinitionVersion(discardTarget.job_name, discardTarget.version)
      showToast('success', `Discarded ${discardTarget.job_name} v${discardTarget.version}.`)
      setDiscardTarget(null)
      load()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not discard this version.')
      setDiscardTarget(null)
    } finally {
      setDiscarding(false)
    }
  }

  if (loading) return <p className="p-4 text-sm text-neutral-400">Loading job definitions…</p>
  if (loadError) return <p className="p-4 text-sm text-red-600">{loadError}</p>

  return (
    <div className="space-y-3">
      {staleActiveWarnings.length > 0 && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          <p className="font-semibold">
            {staleActiveWarnings.length === 1
              ? 'A newer version is stored but not active'
              : `${staleActiveWarnings.length} jobs have a newer version stored but not active`}
          </p>
          <ul className="mt-1 space-y-0.5 text-xs">
            {staleActiveWarnings.map((w) => (
              <li key={w.jobName}>
                <span className="font-mono font-medium">{w.jobName}</span>: v{w.highestVersion} is the highest stored
                version, but v{w.activeVersion} is active. The engine is running v{w.activeVersion} until v
                {w.highestVersion} is explicitly activated.
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid grid-cols-[minmax(280px,360px)_1fr] gap-4">
        <section className="rounded border border-neutral-200 bg-white">
          <h3 className="border-b border-neutral-100 px-4 py-2 text-sm font-semibold text-neutral-900">
            Job definitions — every stored version
          </h3>
          <table className="w-full text-left text-xs">
            <thead className="uppercase tracking-wide text-neutral-400">
              <tr>
                <th className="px-3 py-2 font-medium">Job</th>
                <th className="px-3 py-2 font-medium">v</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Steps</th>
                <th className="px-3 py-2 font-medium" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const isSelected = selected?.jobName === row.job_name && selected.version === row.version
                return (
                  <tr
                    key={`${row.job_name}-${row.version}`}
                    onClick={() =>
                      setSelected({
                        jobName: row.job_name,
                        version: row.version,
                        isActive: row.is_active,
                        validationStatus: row.validation_status,
                      })
                    }
                    className={`cursor-pointer border-b border-neutral-100 ${isSelected ? 'bg-violet-50' : 'hover:bg-neutral-50'}`}
                  >
                    <td className="px-3 py-2 font-medium text-neutral-800">{row.job_name}</td>
                    <td className="px-3 py-2 font-mono text-neutral-500">v{row.version}</td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-1">
                        {row.is_active && (
                          <span className="rounded bg-teal-100 px-1.5 py-0.5 font-semibold tracking-wide text-teal-700">ACTIVE</span>
                        )}
                        {!row.is_active && (
                          <span className="rounded bg-neutral-200 px-1.5 py-0.5 font-semibold tracking-wide text-neutral-500">
                            INACTIVE
                          </span>
                        )}
                        {row.validation_status === 'invalid' && (
                          <span className="rounded bg-red-100 px-1.5 py-0.5 font-semibold tracking-wide text-red-700">INVALID</span>
                        )}
                        {!row.is_active && highestVersionByStaleJob.get(row.job_name) === row.version && (
                          <span
                            className="rounded bg-amber-100 px-1.5 py-0.5 font-semibold tracking-wide text-amber-700"
                            title="This is the highest stored version, but it is not the active one."
                          >
                            NEWER THAN ACTIVE
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-neutral-500">
                      {row.implemented_step_count} / {row.step_count}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {!row.is_active && !row.has_executions && (
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation()
                            setDiscardTarget(row)
                          }}
                          className="text-red-600 hover:underline"
                        >
                          Discard…
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>

        <section>
          {!selected ? (
            <p className="p-4 text-sm text-neutral-400">Select a job definition version to inspect it.</p>
          ) : selected.isActive && selected.validationStatus === 'valid' ? (
            <JobDefinitionViewer key={`${selected.jobName}-${selected.version}`} jobName={selected.jobName} engagementId={null} />
          ) : (
            <VersionDetail key={`${selected.jobName}-${selected.version}`} jobName={selected.jobName} version={selected.version} />
          )}
        </section>
      </div>

      <ConfirmDialog
        open={discardTarget !== null}
        title={discardTarget ? `Discard ${discardTarget.job_name} v${discardTarget.version}?` : ''}
        message={
          discardTarget
            ? `Version ${discardTarget.version} has never been activated. This permanently deletes the stored definition; it cannot be undone.`
            : ''
        }
        confirmLabel={discarding ? 'Discarding…' : 'Discard'}
        destructive
        onConfirm={handleConfirmDiscard}
        onCancel={() => setDiscardTarget(null)}
      />
    </div>
  )
}

/** For an inactive or invalid version — the flow/policy viewer only makes
 * sense for the currently-running definition, so this shows what actually
 * matters for a broken or superseded one: why it's invalid, and the exact
 * YAML that produced it. */
function VersionDetail({ jobName, version }: { jobName: string; version: number }) {
  const [detail, setDetail] = useState<JobDefinitionFull | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    setLoadError(null)
    getJobDefinitionVersion(jobName, version)
      .then(setDetail)
      .catch(() => setLoadError('Could not load this version.'))
      .finally(() => setLoading(false))
  }, [jobName, version])

  if (loading) return <p className="p-4 text-sm text-neutral-400">Loading…</p>
  if (loadError || !detail) return <p className="p-4 text-sm text-red-600">{loadError ?? 'Not found.'}</p>

  return (
    <div className="space-y-4 rounded border border-neutral-200 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-100 pb-3">
        <div>
          <h2 className="text-base font-semibold text-neutral-900">
            {detail.job_name} <span className="font-mono text-sm text-neutral-400">v{detail.version}</span>
          </h2>
          <div className="mt-1 flex gap-1 text-xs">
            <span className={`rounded px-1.5 py-0.5 font-semibold tracking-wide ${detail.is_active ? 'bg-teal-100 text-teal-700' : 'bg-neutral-200 text-neutral-500'}`}>
              {detail.is_active ? 'ACTIVE' : 'INACTIVE'}
            </span>
            <span
              className={`rounded px-1.5 py-0.5 font-semibold tracking-wide ${
                detail.validation_status === 'valid' ? 'bg-teal-100 text-teal-700' : 'bg-red-100 text-red-700'
              }`}
            >
              {detail.validation_status.toUpperCase()}
            </span>
          </div>
        </div>
        <span className="text-xs text-neutral-400">stored {new Date(detail.created_at).toLocaleString()}</span>
      </div>

      {detail.validation_errors && detail.validation_errors.length > 0 && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-xs">
          <p className="mb-1 font-semibold uppercase tracking-wide text-red-700">Validation errors</p>
          <ul className="space-y-2">
            {detail.validation_errors.map((err, i) => (
              <li key={i} className="text-red-800">
                <span className="font-mono font-semibold">{err.code}</span>
                {err.step && <span className="text-red-600"> ({err.step})</span>} — {err.detail}
                {err.affected_steps.length > 0 && (
                  <span className="text-red-600"> · affects: {err.affected_steps.join(', ')}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-neutral-400">Raw YAML</p>
        {detail.source_yaml ? (
          <div className="relative">
            <pre className="max-h-96 overflow-auto rounded bg-neutral-900 p-3 font-mono text-[11px] text-neutral-100">{detail.source_yaml}</pre>
            <div className="absolute right-2 top-2">
              <CopyButton value={detail.source_yaml} />
            </div>
          </div>
        ) : (
          <p className="text-xs text-neutral-400">Not recorded for this stored version.</p>
        )}
      </div>
    </div>
  )
}
