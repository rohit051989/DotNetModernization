import { useEffect, useState } from 'react'
import { listExecutions, listJobDefinitions } from '../../api/workflow'
import type { JobDefinitionSummary, JobExecution } from '../../types/workflow'
import { BatchStatusBadge } from '../../components/WorkflowBadges'
import { LaunchJobDrawer } from './LaunchJobDrawer'

function formatRelative(iso: string | null): string {
  if (!iso) return '—'
  const diffMinutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return `${Math.round(diffHours / 24)}d ago`
}

const SCOPE_LABELS: Record<JobDefinitionSummary['scope'], string> = {
  per_repository: 'per repository',
  per_engagement: 'per engagement',
  other: '—',
}

interface JobsListProps {
  engagementId: string
  selectedJobName: string | null
  onSelectExecution: (executionId: string) => void
  onSelectJob: (jobName: string) => void
}

export function JobsList({ engagementId, selectedJobName, onSelectExecution, onSelectJob }: JobsListProps) {
  const [jobs, setJobs] = useState<JobDefinitionSummary[]>([])
  const [lastExecutions, setLastExecutions] = useState<Record<string, JobExecution | null>>({})
  const [loading, setLoading] = useState(true)
  const [launchingJob, setLaunchingJob] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listJobDefinitions()
      .then(async (jobList) => {
        if (cancelled) return
        setJobs(jobList)
        const entries = await Promise.all(
          jobList.map(async (job) => {
            const executions = await listExecutions({ jobName: job.job_name, engagementId, limit: 1 }).catch(() => [])
            return [job.job_name, executions[0] ?? null] as const
          }),
        )
        if (!cancelled) setLastExecutions(Object.fromEntries(entries))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [engagementId, refreshToken])

  return (
    <section className="rounded border border-neutral-200 bg-white">
      <h2 className="border-b border-neutral-100 px-4 py-3 text-sm font-semibold text-neutral-900">Jobs</h2>
      {loading && <p className="p-4 text-sm text-neutral-400">Loading…</p>}
      {!loading && jobs.length === 0 && <p className="p-4 text-sm text-neutral-400">No jobs registered.</p>}
      {!loading && jobs.length > 0 && (
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-4 py-2 font-medium">Job</th>
              <th className="px-3 py-2 font-medium">Version</th>
              <th className="px-3 py-2 font-medium">Scope</th>
              <th className="px-3 py-2 font-medium">Steps implemented</th>
              <th className="px-3 py-2 font-medium">Last execution</th>
              <th className="px-3 py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => {
              const last = lastExecutions[job.job_name]
              const isSelected = selectedJobName === job.job_name
              return (
                <tr key={job.job_name} className={`border-b border-neutral-100 ${isSelected ? 'bg-violet-50/60' : ''}`}>
                  <td className="px-4 py-2">
                    <button
                      type="button"
                      onClick={() => onSelectJob(job.job_name)}
                      className="text-left font-medium text-neutral-900 hover:text-violet-700 hover:underline"
                    >
                      {job.job_name}
                    </button>
                    {job.description && <div className="text-xs text-neutral-400">{job.description}</div>}
                  </td>
                  <td className="px-3 py-2 text-neutral-600">v{job.active_version}</td>
                  <td className="px-3 py-2 text-neutral-500">{SCOPE_LABELS[job.scope]}</td>
                  <td className="px-3 py-2 text-neutral-600">
                    {job.implemented_step_count} of {job.step_count} implemented
                  </td>
                  <td className="px-3 py-2">
                    {last ? (
                      <button
                        type="button"
                        onClick={() => onSelectExecution(last.id)}
                        className="flex items-center gap-2 hover:underline"
                      >
                        <BatchStatusBadge status={last.batch_status} />
                        <span className="text-xs text-neutral-400">{formatRelative(last.started_at ?? last.created_at)}</span>
                      </button>
                    ) : (
                      <span className="text-xs text-neutral-300">never run</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      type="button"
                      onClick={() => setLaunchingJob(job.job_name)}
                      className="rounded bg-violet-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-violet-700"
                    >
                      Launch
                    </button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {launchingJob && (
        <LaunchJobDrawer
          jobName={launchingJob}
          engagementId={engagementId}
          onClose={() => setLaunchingJob(null)}
          onLaunched={(execution) => {
            setLaunchingJob(null)
            setRefreshToken((t) => t + 1)
            onSelectExecution(execution.id)
          }}
        />
      )}
    </section>
  )
}
