import { useCallback, useEffect, useState } from 'react'
import { listExecutions } from '../../api/workflow'
import { listRepositories } from '../../api/repositories'
import type { RepositorySummary } from '../../types/repositories'
import { isExecutionTerminal, type JobExecution } from '../../types/workflow'
import { BatchStatusBadge, ExitStatusBadge } from '../../components/WorkflowBadges'
import { EmptyState } from '../../components/EmptyState'
import { usePolling } from '../../hooks/usePolling'

const BATCH_STATUS_OPTIONS = ['STARTING', 'STARTED', 'COMPLETED', 'FAILED', 'STOPPING', 'STOPPED', 'ABANDONED']
const POLL_INTERVAL_MS = 5000

function formatRelative(iso: string | null): string {
  if (!iso) return '—'
  const diffMinutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return `${Math.round(diffHours / 24)}d ago`
}

function formatDuration(seconds: number | null): string {
  if (seconds === null) return '—'
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  return `${Math.round(seconds / 60)}m`
}

interface ExecutionsListProps {
  engagementId: string
  onSelectExecution: (executionId: string) => void
  onNavigateToRepositories: () => void
}

export function ExecutionsList({ engagementId, onSelectExecution, onNavigateToRepositories }: ExecutionsListProps) {
  const [executions, setExecutions] = useState<JobExecution[]>([])
  const [repositories, setRepositories] = useState<RepositorySummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [jobNameFilter, setJobNameFilter] = useState('')
  const [batchStatusFilter, setBatchStatusFilter] = useState('')
  const [repositoryFilter, setRepositoryFilter] = useState('')

  useEffect(() => {
    listRepositories(engagementId).then(setRepositories).catch(() => setRepositories([]))
  }, [engagementId])

  const load = useCallback(async () => {
    try {
      const result = await listExecutions({
        engagementId,
        jobName: jobNameFilter || undefined,
        batchStatus: batchStatusFilter || undefined,
        repositoryId: repositoryFilter || undefined,
        limit: 100,
      })
      setExecutions(result)
      setError(null)
    } catch {
      setError('Could not load executions.')
    } finally {
      setLoading(false)
    }
  }, [engagementId, jobNameFilter, batchStatusFilter, repositoryFilter])

  useEffect(() => {
    setLoading(true)
    load()
  }, [load])

  const anyNonTerminal = executions.some((e) => !isExecutionTerminal(e.batch_status))
  usePolling(load, POLL_INTERVAL_MS, anyNonTerminal)

  const repoNameById = Object.fromEntries(repositories.map((r) => [r.id, r.name]))

  return (
    <section className="rounded border border-neutral-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-neutral-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-neutral-900">Executions</h2>
        <div className="flex flex-wrap gap-2">
          <input
            type="text"
            value={jobNameFilter}
            onChange={(event) => setJobNameFilter(event.target.value)}
            placeholder="Job name…"
            className="rounded border border-neutral-300 px-2 py-1 text-xs focus:border-violet-400 focus:outline-none"
          />
          <select
            value={batchStatusFilter}
            onChange={(event) => setBatchStatusFilter(event.target.value)}
            className="rounded border border-neutral-300 px-2 py-1 text-xs"
          >
            <option value="">All statuses</option>
            {BATCH_STATUS_OPTIONS.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
          <select
            value={repositoryFilter}
            onChange={(event) => setRepositoryFilter(event.target.value)}
            className="rounded border border-neutral-300 px-2 py-1 text-xs"
          >
            <option value="">All repositories</option>
            {repositories.map((repo) => (
              <option key={repo.id} value={repo.id}>
                {repo.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loading && <p className="p-4 text-sm text-neutral-400">Loading…</p>}
      {!loading && error && <EmptyState title="Could not load executions" description={error} />}
      {!loading && !error && executions.length === 0 && (
        <EmptyState
          title="No executions for this engagement"
          description="Register a repository to launch discovery for it."
          action={{ label: 'Go to Repositories', onClick: onNavigateToRepositories }}
        />
      )}
      {!loading && !error && executions.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-4 py-2 font-medium">Job</th>
              <th className="px-3 py-2 font-medium">Repository</th>
              <th className="px-3 py-2 font-medium">Batch status</th>
              <th className="px-3 py-2 font-medium">Exit status</th>
              <th className="px-3 py-2 font-medium">Steps</th>
              <th className="px-3 py-2 font-medium">Duration</th>
              <th className="px-3 py-2 font-medium">Started</th>
              <th className="px-3 py-2 font-medium">Triggered by</th>
            </tr>
          </thead>
          <tbody>
            {executions.map((execution) => {
              const repositoryId = typeof execution.parameters.repository_id === 'string' ? execution.parameters.repository_id : null
              const repositoryName =
                execution.resolved_context.repository_name ?? (repositoryId ? repoNameById[repositoryId] : null)
              return (
                <tr
                  key={execution.id}
                  onClick={() => onSelectExecution(execution.id)}
                  className="cursor-pointer border-b border-neutral-100 hover:bg-neutral-50"
                >
                  <td className="px-4 py-2 font-medium text-neutral-900">{execution.job_name}</td>
                  <td className="px-3 py-2 text-neutral-600">{repositoryName ?? '—'}</td>
                  <td className="px-3 py-2">
                    <BatchStatusBadge status={execution.batch_status} />
                  </td>
                  <td className="px-3 py-2">
                    <ExitStatusBadge status={execution.exit_status} />
                  </td>
                  <td className="px-3 py-2 text-neutral-500">
                    {execution.step_summary.completed + execution.step_summary.not_implemented}/{execution.step_summary.total}
                  </td>
                  <td className="px-3 py-2 text-neutral-500">{formatDuration(execution.duration_seconds)}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-neutral-500">{formatRelative(execution.started_at)}</td>
                  <td className="px-3 py-2 text-neutral-500">{execution.triggered_by ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </section>
  )
}
