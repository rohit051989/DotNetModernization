import { useCallback, useEffect, useRef, useState } from 'react'
import { getDashboard, getDashboardRepositories } from '../api/dashboard'
import { getViewpointCoverage } from '../api/registration'
import { isExecutionTerminal, type DashboardRepositoryRow, type DashboardSummary } from '../types/dashboard'
import type { ViewpointCoverage } from '../types/registration'
import { EmptyState } from '../components/EmptyState'
import { DiscoveryProgressBar } from '../components/DiscoveryProgressBar'

const COVERAGE_LABEL_TONE: Record<string, string> = {
  strong: 'bg-emerald-100 text-emerald-700',
  partial: 'bg-amber-100 text-amber-700',
  thin: 'bg-orange-100 text-orange-700',
  none: 'bg-neutral-100 text-neutral-500',
}

/** 25-STANDARDS-AND-VIEWPOINTS.md Part A2 — a compact, honest-scoping strip.
 * Full detail (contributing steps, ran counts) lives in Workflow
 * Administration; this is the "what does this assessment actually cover"
 * glance for the engagement dashboard. */
function ViewpointCoverageStrip({ engagementId }: { engagementId: string }) {
  const [coverage, setCoverage] = useState<ViewpointCoverage | null>(null)

  useEffect(() => {
    let cancelled = false
    getViewpointCoverage(engagementId)
      .then((result) => {
        if (!cancelled) setCoverage(result)
      })
      .catch(() => {
        if (!cancelled) setCoverage(null)
      })
    return () => {
      cancelled = true
    }
  }, [engagementId])

  if (!coverage) return null

  return (
    <section className="rounded border border-neutral-200 bg-white p-4">
      <h2 className="mb-2 text-sm font-semibold text-neutral-900">Viewpoint coverage</h2>
      <div className="flex flex-wrap gap-1.5">
        {coverage.viewpoints.map((v) => (
          <span
            key={v.viewpoint}
            title={`${v.implemented_count} of ${v.total_contributing} contributing steps implemented; ${v.ran_count} ran for this engagement`}
            className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${COVERAGE_LABEL_TONE[v.coverage_label] ?? COVERAGE_LABEL_TONE.none}`}
          >
            {v.viewpoint.toLowerCase()} · {v.coverage_label}
          </span>
        ))}
      </div>
    </section>
  )
}

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

  // Gated on the capability flag as well as the payload: item detection is
  // only shown once the backend reports it implemented, so nothing renders
  // fabricated numbers before then.
  const items = summary.capabilities.item_detection ? summary.items : null

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
        {items ? (
          <SummaryCard title="Items found">
            <p className="text-2xl font-semibold text-neutral-900">{items.items_found}</p>
            <p className="text-xs text-neutral-400">
              {items.occurrences_found} occurrences · {items.projects_with_findings} of {items.projects_evaluated}{' '}
              projects with findings
            </p>
            {items.occurrences_possible > 0 && (
              <p className="text-xs text-neutral-400" title="Occurrences resting only on ambiguous evidence, such as a call an unchanged overload could equally take">
                + {items.occurrences_possible} possible, not counted
              </p>
            )}
            {items.projects_needing_rescan > 0 && (
              <p className="text-xs text-amber-600">{items.projects_needing_rescan} projects need a rescan</p>
            )}
          </SummaryCard>
        ) : (
          <UnavailableCard title="Items found" awaiting="item detection" />
        )}
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
        <div className="overflow-x-auto">
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
              <th className="px-3 py-2 font-medium">Items found</th>
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
                  {row.items_found !== null ? (
                    <td className="px-3 py-2 text-neutral-700">{row.items_found}</td>
                  ) : (
                    <td className="px-3 py-2 text-neutral-300" title="Awaiting item detection">
                      —
                    </td>
                  )}
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
        </div>
      </section>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <section className="rounded border border-neutral-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-semibold text-neutral-900">Item work list</h2>
          {items ? (
            <>
              <dl className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-4">
                <div>
                  <dt className="text-neutral-400">Projects with findings</dt>
                  <dd className="font-medium text-neutral-900">
                    {items.projects_with_findings} of {items.projects_evaluated}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-400">Items found</dt>
                  <dd className="font-medium text-neutral-900">{items.items_found}</dd>
                </div>
                <div>
                  <dt className="text-neutral-400">Occurrences found</dt>
                  <dd className="font-medium text-neutral-900">
                    {items.occurrences_found}
                    {items.occurrences_possible > 0 && <span className="ml-1 text-xs font-normal text-neutral-400">+ {items.occurrences_possible} possible</span>}
                  </dd>
                </div>
                <div>
                  <dt className="text-neutral-400">Needing rescan</dt>
                  <dd
                    className={
                      items.projects_needing_rescan > 0 ? 'font-medium text-amber-600' : 'font-medium text-neutral-900'
                    }
                  >
                    {items.projects_needing_rescan}
                  </dd>
                </div>
              </dl>
              {items.top_items.length > 0 ? (
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase tracking-wide text-neutral-400">
                    <tr>
                      <th className="py-1 font-medium">Item</th>
                      <th className="py-1 text-right font-medium">Projects</th>
                      <th className="py-1 text-right font-medium">Occurrences</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.top_items.map((item) => (
                      <tr key={item.item_id} className="border-t border-neutral-50">
                        <td className="py-1.5 text-neutral-700">{item.item_name}</td>
                        <td className="py-1.5 text-right font-medium text-neutral-900">{item.projects}</td>
                        <td className="py-1.5 text-right text-neutral-600">{item.occurrences}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-xs text-neutral-400">No catalog items found in the evaluated projects yet.</p>
              )}
            </>
          ) : (
            <p className="text-sm text-neutral-300">
              — <span className="text-xs text-neutral-400">Awaiting item detection.</span>
            </p>
          )}
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

      <ViewpointCoverageStrip engagementId={engagementId} />
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
