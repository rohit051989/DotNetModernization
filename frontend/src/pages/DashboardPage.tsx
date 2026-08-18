import { useCallback, useEffect, useRef, useState } from 'react'
import { getDashboard, getDashboardRepositories } from '../api/dashboard'
import { isExecutionTerminal, type DashboardRepositoryRow, type DashboardSummary } from '../types/dashboard'
import { EmptyState } from '../components/EmptyState'
import { DiscoveryProgressBar } from '../components/DiscoveryProgressBar'

const POLL_INTERVAL_MS = 5000

interface DashboardPageProps {
  engagementId: string
  onNavigateToRepositories: () => void
  onNavigateToExecution: (executionId: string) => void
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`
}

function formatRelative(iso: string | null): string {
  if (!iso) return '—'
  const diffMinutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return `${Math.round(diffHours / 24)}d ago`
}

function formatDuration(startIso: string | null, endIso: string | null): string {
  if (!startIso || !endIso) return '—'
  const seconds = Math.max(0, Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s`
  return `${Math.round(seconds / 60)}m`
}

export function DashboardPage({ engagementId, onNavigateToRepositories, onNavigateToExecution }: DashboardPageProps) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [rows, setRows] = useState<DashboardRepositoryRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const load = useCallback(
    async (isPoll: boolean) => {
      if (!isPoll) setLoading(true)
      setError(null)
      try {
        const [summaryResult, rowsResult] = await Promise.all([
          getDashboard(engagementId),
          getDashboardRepositories(engagementId),
        ])
        setSummary(summaryResult)
        setRows(rowsResult)

        const anyNonTerminal = rowsResult.some(
          (row) => row.latest_execution && !isExecutionTerminal(row.latest_execution.batch_status),
        )
        if (anyNonTerminal) {
          pollTimer.current = setTimeout(() => load(true), POLL_INTERVAL_MS)
        }
      } catch {
        setError('Could not load the dashboard.')
      } finally {
        setLoading(false)
      }
    },
    [engagementId],
  )

  useEffect(() => {
    load(false)
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current)
    }
  }, [load])

  if (loading) {
    return (
      <div className="grid grid-cols-3 gap-4 p-6">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-24 animate-pulse rounded border border-neutral-200 bg-neutral-100" />
        ))}
      </div>
    )
  }

  if (error || !summary) {
    return (
      <div className="p-10">
        <EmptyState
          title="Could not load the dashboard"
          description={error ?? undefined}
          action={{ label: 'Retry', onClick: () => load(false) }}
        />
      </div>
    )
  }

  if (rows.length === 0) {
    return (
      <div className="p-10">
        <EmptyState
          title="No repositories registered yet"
          description="Register a repository to see modernization status for this engagement."
          action={{ label: 'Register a repository', onClick: onNavigateToRepositories }}
        />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-[1440px] space-y-6 p-6">
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-6">
        <SummaryCard title="Repositories">
          <p className="text-2xl font-semibold text-neutral-900">{summary.repositories.total}</p>
          <p className="text-xs text-neutral-400">
            {summary.repositories.scanned} scanned · {summary.repositories.registered} registered ·{' '}
            {summary.repositories.scan_failed} failed
          </p>
        </SummaryCard>
        <SummaryCard title="Discovery">
          <p className="text-2xl font-semibold text-neutral-900">{summary.discovery.completed}</p>
          <p className="text-xs text-neutral-400">
            {summary.discovery.in_progress} in progress · {summary.discovery.failed} failed
          </p>
        </SummaryCard>
        <SummaryCard title="Solutions">
          <p className="text-2xl font-semibold text-neutral-900">{summary.structure.solution_count}</p>
          <p className="text-xs text-neutral-400">across {summary.structure.repositories_scanned} scanned repositories</p>
        </SummaryCard>
        <SummaryCard title="Projects">
          <p className="text-2xl font-semibold text-neutral-900">{summary.structure.project_file_count}</p>
          <p className="text-xs text-neutral-400">{summary.structure.standalone_project_count} standalone</p>
        </SummaryCard>
        <SummaryCard title="Unresolved references">
          <p className="text-2xl font-semibold text-neutral-900">{summary.structure.unresolved_reference_count}</p>
          <p className="text-xs text-neutral-400">solution and project references</p>
        </SummaryCard>
        <SummaryCard title="Legacy vs SDK">
          <p className="text-2xl font-semibold text-neutral-900">
            {summary.structure.legacy_project_count} / {summary.structure.sdk_project_count}
          </p>
          <p className="text-xs text-neutral-400">legacy_msbuild vs sdk_style</p>
        </SummaryCard>
        <UnavailableCard title="Applications" awaiting="application fingerprinting (step 3)" />
        <UnavailableCard title="Patterns identified" awaiting="pattern classification (step 4)" />
        <SummaryCard title="Target state decisions">
          <p className="text-2xl font-semibold text-neutral-900">{summary.decisions.approved}</p>
          <p className="text-xs text-neutral-400">
            {summary.decisions.in_review} in review · {summary.decisions.parked} parked
          </p>
        </SummaryCard>
        <UnavailableCard title="Waves" awaiting="wave planning (step 12)" />
      </div>

      <section className="rounded border border-neutral-200 bg-white">
        <h2 className="border-b border-neutral-100 px-4 py-3 text-sm font-semibold text-neutral-900">
          Repository status
        </h2>
        <table className="w-full text-left text-sm">
          <thead className="text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Source</th>
              <th className="px-3 py-2 font-medium">Ingest status</th>
              <th className="px-3 py-2 font-medium">Git</th>
              <th className="px-3 py-2 font-medium">Size</th>
              <th className="px-3 py-2 font-medium">Solutions</th>
              <th className="px-3 py-2 font-medium">Projects</th>
              <th className="px-3 py-2 font-medium">Standalone</th>
              <th className="px-3 py-2 font-medium">Frameworks</th>
              <th className="px-3 py-2 font-medium">Scan status</th>
              <th className="px-3 py-2 font-medium">Applications</th>
              <th className="px-3 py-2 font-medium">Patterns</th>
              <th className="px-3 py-2 font-medium">Discovery progress</th>
              <th className="px-3 py-2 font-medium">Last run</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const latest = row.latest_execution
              return (
                <tr key={row.repository_id} className="border-b border-neutral-100">
                  <td className="px-4 py-2 font-medium text-neutral-900">{row.name}</td>
                  <td className="px-3 py-2 text-neutral-500">{row.source_type}</td>
                  <td className="px-3 py-2 text-neutral-600">{row.ingest_status.replace('_', ' ')}</td>
                  <td className="px-3 py-2 text-neutral-500">{row.has_git_history ? '✓' : '—'}</td>
                  <td className="px-3 py-2 text-neutral-600">{row.size_bytes !== null ? formatBytes(row.size_bytes) : '—'}</td>
                  <td className="px-3 py-2 text-neutral-600">{row.structure?.solution_count ?? '—'}</td>
                  <td className="px-3 py-2 text-neutral-600">{row.structure?.project_file_count ?? '—'}</td>
                  <td className="px-3 py-2 text-neutral-600">{row.structure?.standalone_project_count ?? '—'}</td>
                  <td className="px-3 py-2 text-neutral-500">
                    {row.structure ? Object.keys(row.structure.framework_families).join(', ') || '—' : '—'}
                  </td>
                  <td className="px-3 py-2">
                    {row.structure ? (
                      <span
                        className={
                          row.structure.scan_status === 'complete'
                            ? 'rounded-full border border-teal-200 bg-teal-50 px-2 py-0.5 text-xs font-medium text-teal-700'
                            : row.structure.scan_status === 'partial'
                              ? 'rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-700'
                              : 'rounded-full border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700'
                        }
                      >
                        {row.structure.scan_status}
                      </span>
                    ) : (
                      <span className="text-xs text-neutral-300">not scanned</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-neutral-300" title="Awaiting application fingerprinting (step 3)">
                    —
                  </td>
                  <td className="px-3 py-2 text-neutral-300" title="Awaiting pattern classification (step 4)">
                    —
                  </td>
                  <td className="px-3 py-2">
                    {latest ? (
                      <DiscoveryProgressBar
                        steps={latest.steps}
                        stepsTotal={latest.steps_total}
                        onClick={() => onNavigateToExecution(latest.job_execution_id)}
                      />
                    ) : (
                      <span className="text-xs text-neutral-300">not started</span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap text-neutral-500">{formatRelative(row.last_ingested_at)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="rounded border border-neutral-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-neutral-900">Pattern distribution</h2>
          <p className="text-xs text-neutral-400">
            Awaiting pattern classification (step 4). {summary.decisions.total_patterns_in_scope} patterns currently
            in scope for this engagement.
          </p>
        </section>
        <section className="rounded border border-neutral-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-neutral-900">Recent activity</h2>
          <ul className="divide-y divide-neutral-100">
            {summary.recent_executions.slice(0, 10).map((execution) => (
              <li key={execution.job_execution_id}>
                <button
                  type="button"
                  onClick={() => onNavigateToExecution(execution.job_execution_id)}
                  className="flex w-full items-center justify-between py-2 text-left text-sm hover:bg-neutral-50"
                >
                  <div>
                    <p className="text-neutral-800">
                      {execution.job_name}
                      {execution.repository_slug ? ` · ${execution.repository_slug}` : ''}
                    </p>
                    <p className="text-xs text-neutral-400">{formatRelative(execution.started_at)}</p>
                  </div>
                  <div className="text-right text-xs">
                    <p
                      className={
                        execution.batch_status === 'COMPLETED'
                          ? 'font-medium text-emerald-600'
                          : execution.batch_status === 'FAILED'
                            ? 'font-medium text-red-600'
                            : 'font-medium text-amber-600'
                      }
                    >
                      {execution.batch_status}
                    </p>
                    <p className="text-neutral-400">{formatDuration(execution.started_at, execution.ended_at)}</p>
                  </div>
                </button>
              </li>
            ))}
            {summary.recent_executions.length === 0 && <p className="text-sm text-neutral-400">No executions yet.</p>}
          </ul>
        </section>
      </div>
    </div>
  )
}

function SummaryCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded border border-neutral-200 bg-white p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{title}</p>
      <div className="mt-1">{children}</div>
    </div>
  )
}

function UnavailableCard({ title, awaiting }: { title: string; awaiting: string }) {
  return (
    <div className="rounded border border-dashed border-neutral-200 bg-neutral-50 p-4 opacity-70">
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{title}</p>
      <p className="mt-1 text-sm text-neutral-400">Awaiting {awaiting}</p>
    </div>
  )
}
