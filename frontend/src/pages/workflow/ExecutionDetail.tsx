import { useCallback, useEffect, useState } from 'react'
import { getExecution, listExecutionArtifacts, resumeExecution } from '../../api/workflow'
import { ApiError } from '../../api/client'
import type { ArtifactSummary, JobExecutionDetail as JobExecutionDetailType } from '../../types/workflow'
import { isExecutionTerminal } from '../../types/workflow'
import { BatchStatusBadge, ExitStatusBadge } from '../../components/WorkflowBadges'
import { CopyButton } from '../../components/CopyButton'
import { EmptyState } from '../../components/EmptyState'
import { useToast } from '../../components/Toast'
import { usePolling } from '../../hooks/usePolling'
import { StepTimeline } from './StepTimeline'
import { ArtifactViewerDrawer } from './ArtifactViewerDrawer'

const POLL_INTERVAL_MS = 2000

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${seconds.toFixed(2)}s`
  return `${Math.round(seconds / 60)}m`
}

interface ExecutionDetailProps {
  executionId: string
  onBack: () => void
}

export function ExecutionDetail({ executionId, onBack }: ExecutionDetailProps) {
  const { showToast } = useToast()
  const [execution, setExecution] = useState<JobExecutionDetailType | null>(null)
  const [artifacts, setArtifacts] = useState<ArtifactSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [busy, setBusy] = useState(false)
  const [viewingArtifactId, setViewingArtifactId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [executionResult, artifactResult] = await Promise.all([
        getExecution(executionId),
        listExecutionArtifacts(executionId),
      ])
      setExecution(executionResult)
      setArtifacts(artifactResult)
      setNotFound(false)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setNotFound(true)
    } finally {
      setLoading(false)
    }
  }, [executionId])

  useEffect(() => {
    setLoading(true)
    setExecution(null)
    load()
  }, [load])

  const isRunning = execution ? !isExecutionTerminal(execution.batch_status) : false
  usePolling(load, POLL_INTERVAL_MS, isRunning)

  async function handleResumeOrRestart() {
    setBusy(true)
    try {
      await resumeExecution(executionId)
      showToast('success', 'Execution resumed.')
      await load()
    } catch {
      showToast('error', 'Could not resume this execution.')
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="p-6 text-sm text-neutral-400">Loading execution…</p>

  if (notFound || !execution) {
    return (
      <div className="p-10">
        <EmptyState
          title="Execution not found"
          description="This execution may have been removed, or the id is wrong."
          action={{ label: 'Back to executions', onClick: onBack }}
        />
      </div>
    )
  }

  const artifactsByStep = artifacts.reduce<Record<string, ArtifactSummary[]>>((acc, artifact) => {
    ;(acc[artifact.step_name] ??= []).push(artifact)
    return acc
  }, {})

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <button type="button" onClick={onBack} className="text-sm text-violet-600 hover:underline">
        ← Back to executions
      </button>

      <section className="space-y-3 rounded border border-neutral-200 bg-white p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-neutral-900">{execution.job_name}</h2>
            <p className="text-sm text-neutral-500">
              {execution.resolved_context.repository_name ?? execution.resolved_context.engagement_name ?? '—'}
            </p>
          </div>
          <div className="flex gap-2">
            {execution.can_restart && (
              <button
                type="button"
                onClick={handleResumeOrRestart}
                disabled={busy}
                className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {busy ? 'Restarting…' : 'Restart'}
              </button>
            )}
            {execution.can_resume && (
              <button
                type="button"
                onClick={handleResumeOrRestart}
                disabled={busy}
                className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
              >
                {busy ? 'Resuming…' : 'Resume'}
              </button>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <BatchStatusBadge status={execution.batch_status} />
          <ExitStatusBadge status={execution.exit_status} />
          <span className="text-xs text-neutral-400">execution #{execution.execution_number}</span>
          <span className="text-xs text-neutral-400">duration {formatDuration(execution.duration_seconds)}</span>
          <span className="text-xs text-neutral-400">engine {execution.engine_version}</span>
          <span className="text-xs text-neutral-400">triggered by {execution.triggered_by ?? '—'}</span>
        </div>
        {execution.exit_message && <p className="text-sm text-red-600">{execution.exit_message}</p>}

        <dl className="grid grid-cols-2 gap-x-6 gap-y-1 border-t border-neutral-100 pt-3 text-xs sm:grid-cols-3">
          <div>
            <dt className="text-neutral-400">Started</dt>
            <dd className="text-neutral-700">{execution.started_at ? new Date(execution.started_at).toLocaleString() : '—'}</dd>
          </div>
          <div>
            <dt className="text-neutral-400">Ended</dt>
            <dd className="text-neutral-700">{execution.ended_at ? new Date(execution.ended_at).toLocaleString() : '—'}</dd>
          </div>
          <div>
            <dt className="text-neutral-400">Definition version</dt>
            <dd className="text-neutral-700">v{execution.job_definition_version}</dd>
          </div>
          {Object.entries(execution.parameters).map(([key, value]) => (
            <div key={key}>
              <dt className="text-neutral-400">{key}</dt>
              <dd className="flex items-center gap-1.5">
                <span className="truncate font-mono text-neutral-600">{String(value)}</span>
                <CopyButton value={String(value)} />
              </dd>
            </div>
          ))}
        </dl>
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-neutral-900">Steps</h3>
        <StepTimeline steps={execution.steps} onViewArtifact={setViewingArtifactId} />
      </section>

      <section>
        <h3 className="mb-2 text-sm font-semibold text-neutral-900">Artifacts</h3>
        {artifacts.length === 0 ? (
          <p className="text-sm text-neutral-400">No artifacts produced yet.</p>
        ) : (
          <div className="space-y-3">
            {Object.entries(artifactsByStep).map(([stepName, stepArtifacts]) => (
              <div key={stepName} className="rounded border border-neutral-200 bg-white">
                <p className="border-b border-neutral-100 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-neutral-500">
                  {stepName}
                </p>
                <ul className="divide-y divide-neutral-100">
                  {stepArtifacts.map((artifact) => (
                    <li key={artifact.id} className="flex items-center justify-between px-3 py-2 text-sm">
                      <div>
                        <p className="font-medium text-neutral-800">
                          {artifact.artifact_type}@{artifact.artifact_version}
                        </p>
                        <p className="text-xs text-neutral-400">
                          {artifact.size_bytes !== null ? `${(artifact.size_bytes / 1024).toFixed(1)} KB` : '—'} ·{' '}
                          {artifact.checksum.slice(0, 19)}… · {new Date(artifact.created_at).toLocaleString()}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => setViewingArtifactId(artifact.id)}
                        className="rounded border border-neutral-300 px-2 py-1 text-xs text-neutral-600 hover:bg-neutral-50"
                      >
                        View
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </section>

      {viewingArtifactId && <ArtifactViewerDrawer artifactId={viewingArtifactId} onClose={() => setViewingArtifactId(null)} />}
    </div>
  )
}
