import { useEffect, useRef, useState } from 'react'
import { listRepositories } from '../../api/repositories'
import { getDashboardRepositories } from '../../api/dashboard'
import type { RepositorySummary } from '../../types/repositories'
import type { DashboardRepositoryRow } from '../../types/dashboard'
import { EmptyState } from '../../components/EmptyState'
import { CriticalityBadge, CloneUrlVerificationBadge, IngestStatusBadge, RetirementBadge } from '../../components/RepositoryBadges'
import { DiscoveryProgressBar } from '../../components/DiscoveryProgressBar'
import { RegisterRepositoryDrawer } from './RegisterRepositoryDrawer'

const INGEST_STATUS_OPTIONS = ['registered', 'scanned', 'scan_failed', 'path_missing']
const CRITICALITY_OPTIONS = ['low', 'medium', 'high', 'critical']
const RETIREMENT_OPTIONS = ['active', 'slated_for_retirement', 'decommissioned']

function formatSize(bytes: number | null): string {
  if (bytes === null) return '—'
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
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  const diffMinutes = Math.round((Date.now() - then) / 60_000)
  if (diffMinutes < 1) return 'just now'
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 24) return `${diffHours}h ago`
  return `${Math.round(diffHours / 24)}d ago`
}

interface RepositoryListProps {
  engagementId: string
  engagementName: string
  selectedRepositoryId: string | null
  onSelectRepository: (repositoryId: string) => void
  onNavigateToExecution: (executionId: string) => void
  refreshToken: number
  onChanged: () => void
}

export function RepositoryList({
  engagementId,
  engagementName,
  selectedRepositoryId,
  onSelectRepository,
  onNavigateToExecution,
  refreshToken,
  onChanged,
}: RepositoryListProps) {
  const [repositories, setRepositories] = useState<RepositorySummary[]>([])
  const [progressByRepo, setProgressByRepo] = useState<Record<string, DashboardRepositoryRow>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [searchInput, setSearchInput] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [ingestStatusFilter, setIngestStatusFilter] = useState('')
  const [criticalityFilter, setCriticalityFilter] = useState('')
  const [retirementFilter, setRetirementFilter] = useState('')
  const [showDrawer, setShowDrawer] = useState(false)
  // Set right after registration/rescan so the new row's progress is polled
  // until its execution is terminal — 15-REPOSITORY-INGEST-UI.md Part F:
  // "poll GET /api/repositories/{id} every 3 seconds until the execution is
  // terminal."
  const [pendingRepositoryId, setPendingRepositoryId] = useState<string | null>(null)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchInput.trim()), 300)
    return () => clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    let cancelled = false

    async function fetchList() {
      try {
        const [repos, dashboardRows] = await Promise.all([
          listRepositories(engagementId, {
            q: debouncedSearch || undefined,
            ingestStatus: ingestStatusFilter || undefined,
            criticality: criticalityFilter || undefined,
            retirementStatus: retirementFilter || undefined,
          }),
          getDashboardRepositories(engagementId).catch(() => []),
        ])
        if (cancelled) return
        setRepositories(repos)
        const progressMap = Object.fromEntries(dashboardRows.map((row) => [row.repository_id, row]))
        setProgressByRepo(progressMap)

        if (pendingRepositoryId) {
          const pendingExecution = progressMap[pendingRepositoryId]?.latest_execution
          const terminal = !pendingExecution || ['COMPLETED', 'FAILED', 'STOPPED', 'ABANDONED'].includes(pendingExecution.batch_status)
          if (terminal) {
            setPendingRepositoryId(null)
          } else {
            pollTimer.current = setTimeout(fetchList, 3000)
          }
        }
      } catch {
        if (!cancelled) setError('Could not load repositories.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    setLoading(true)
    setError(null)
    fetchList()

    return () => {
      cancelled = true
      if (pollTimer.current) clearTimeout(pollTimer.current)
    }
  }, [engagementId, debouncedSearch, ingestStatusFilter, criticalityFilter, retirementFilter, refreshToken, pendingRepositoryId])

  return (
    <aside className="flex w-[46rem] flex-none flex-col border-r border-neutral-200 bg-white">
      <div className="flex items-center justify-between border-b border-neutral-100 px-4 py-3">
        <h2 className="text-sm font-semibold text-neutral-900">Repositories — {engagementName}</h2>
        <button
          type="button"
          onClick={() => setShowDrawer(true)}
          className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700"
        >
          + Register Repository
        </button>
      </div>

      <div className="flex flex-wrap gap-2 border-b border-neutral-100 px-4 py-3">
        <input
          type="text"
          value={searchInput}
          onChange={(event) => setSearchInput(event.target.value)}
          placeholder="Search name, folder, owner…"
          className="min-w-[160px] flex-1 rounded border border-neutral-300 px-2.5 py-1.5 text-sm focus:border-violet-400 focus:outline-none"
        />
        <select
          value={ingestStatusFilter}
          onChange={(event) => setIngestStatusFilter(event.target.value)}
          className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
        >
          <option value="">All statuses</option>
          {INGEST_STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {status.replace('_', ' ')}
            </option>
          ))}
        </select>
        <select
          value={criticalityFilter}
          onChange={(event) => setCriticalityFilter(event.target.value)}
          className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
        >
          <option value="">All criticality</option>
          {CRITICALITY_OPTIONS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
        <select
          value={retirementFilter}
          onChange={(event) => setRetirementFilter(event.target.value)}
          className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
        >
          <option value="">All retirement statuses</option>
          {RETIREMENT_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {status.replace(/_/g, ' ')}
            </option>
          ))}
        </select>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && <div className="p-4 text-sm text-neutral-400">Loading…</div>}
        {!loading && error && <EmptyState title="Could not load repositories" description={error} />}
        {!loading && !error && repositories.length === 0 && (
          <EmptyState
            title="No repositories registered yet"
            description="Register a local folder to launch discovery for it."
            action={{ label: 'Register a repository', onClick: () => setShowDrawer(true) }}
          />
        )}
        {!loading && !error && repositories.length > 0 && (
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-neutral-50 text-xs uppercase tracking-wide text-neutral-500">
              <tr>
                <th className="px-4 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Git</th>
                <th className="px-3 py-2 font-medium">Size</th>
                <th className="px-3 py-2 font-medium">Apps</th>
                <th className="px-3 py-2 font-medium">Patterns</th>
                <th className="px-3 py-2 font-medium">Discovery</th>
                <th className="px-3 py-2 font-medium">Last scanned</th>
              </tr>
            </thead>
            <tbody>
              {repositories.map((repo) => {
                const progress = progressByRepo[repo.id]
                const latest = progress?.latest_execution ?? null
                return (
                  <tr
                    key={repo.id}
                    onClick={() => onSelectRepository(repo.id)}
                    className={`cursor-pointer border-b border-neutral-100 hover:bg-neutral-50 ${
                      selectedRepositoryId === repo.id ? 'bg-violet-50' : ''
                    } ${repo.retirement_status !== 'active' ? 'opacity-60' : ''}`}
                  >
                    <td className="px-4 py-2">
                      <div className="font-medium text-neutral-900">{repo.name}</div>
                      <div className="flex items-center gap-1.5 text-xs text-neutral-400">
                        <span>{repo.root_folder_name}</span>
                        <CriticalityBadge criticality={repo.criticality} />
                        <RetirementBadge status={repo.retirement_status} />
                      </div>
                    </td>
                    <td className="px-3 py-2">
                      <IngestStatusBadge status={repo.ingest_status} />
                    </td>
                    <td className="px-3 py-2">
                      <CloneUrlVerificationBadge verification={repo.clone_url_verification} />
                    </td>
                    <td className="px-3 py-2 text-neutral-600">{formatSize(repo.size_bytes)}</td>
                    <td className="px-3 py-2 text-neutral-300" title="Awaiting application fingerprinting (step 3)">
                      —
                    </td>
                    <td className="px-3 py-2 text-neutral-300" title="Awaiting pattern classification (step 4)">
                      —
                    </td>
                    <td className="px-3 py-2" onClick={(event) => latest && event.stopPropagation()}>
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
                    <td className="px-3 py-2 whitespace-nowrap text-neutral-500">
                      {formatRelative(repo.last_scanned_at)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {showDrawer && (
        <RegisterRepositoryDrawer
          engagementId={engagementId}
          onClose={() => setShowDrawer(false)}
          onRegistered={(repositoryId) => {
            setShowDrawer(false)
            setPendingRepositoryId(repositoryId)
            onChanged()
          }}
        />
      )}
    </aside>
  )
}
