import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { deleteRepositoryHard, getRepositoryDeletionPlan } from '../../api/deletion'
import { HardDeleteDialog } from '../../components/HardDeleteDialog'
import {
  getRepository,
  listRepositoryExecutions,
  rescanRepository,
  restoreRepository,
  updateRepository,
  verifyRepositoryPath,
} from '../../api/repositories'
import type { Criticality, RepositoryDetail, RetirementStatus } from '../../types/repositories'
import type { JobExecution } from '../../types/workflow'
import { ApiError } from '../../api/client'
import { EmptyState } from '../../components/EmptyState'
import { LimitedList } from '../../components/LimitedList'
import { Field, inputClass } from '../../components/FormField'
import { TagInput } from '../../components/TagInput'
import { useToast } from '../../components/Toast'
import { CriticalityBadge, CloneUrlVerificationBadge, IngestStatusBadge, RetirementBadge } from '../../components/RepositoryBadges'
import { BatchStatusBadge, ExitStatusBadge } from '../../components/WorkflowBadges'
import { formatBytes } from '../workflow/artifacts/renderers'
import { StoredDependenciesView, StoredFingerprintView, StoredWorkListView } from './StoredResultViews'
import { RepositoryFiles, useAskForClone } from './SourceLink'
import { num, obj } from '../workflow/artifacts/adapters'
import { RepositoryStructureSection } from './RepositoryStructureSection'
import { RepositorySurfaceSection } from './RepositorySurfaceSection'
import { RepositoryImpactSection } from './RepositoryImpactSection'
import { RepositoryTestsSection } from './RepositoryTestsSection'
import { ConversionsPanel } from './ConversionsPanel'
import { RepositoryOwner } from './RepositoryOwner'
import { ADMIN_ONLY, useIsAdmin } from '../../auth/AuthContext'
import { StructureSection } from './structure/StructureSection'
import { useLatestArtifacts, type LatestArtifact } from './useLatestArtifacts'
import { RepositoryOverview } from './RepositoryOverview'
import { useRepositorySummary } from './useRepositorySummary'
import { workItemFigures, workItemsLine } from './workItemFigures'
import { parseRepositoryRoute, setRepositoryTabRoute } from '../../routing'
import {
  GROUPS,
  TABS,
  groupOf,
  initialTab,
  rememberScroll,
  rememberTab,
  rememberedScroll,
  tabsOf,
  type GroupKey,
  type TabSlug,
} from './repositoryTabs'

interface RepositoryDetailPageProps {
  repositoryId: string
  refreshToken: number
  onBack: () => void
  onChanged: () => void
  onDeleted: () => void
  onNavigateToExecution: (executionId: string) => void
  /** Opens a SOAP call's row in the Estate tab's SOAP compatibility report. */
  onOpenEstateSoap?: (invocationId: string) => void
}

function formatRelative(iso: string | null): string {
  if (!iso) return 'never'
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

function Tile({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: 'red' | 'amber' }) {
  const style = tone === 'red' ? 'border-red-200 bg-red-50' : tone === 'amber' ? 'border-amber-200 bg-amber-50' : 'border-neutral-200 bg-white'
  return (
    <div className={`min-w-0 rounded border px-3 py-2 ${style}`} title={hint}>
      <p className="truncate text-[11px] font-medium uppercase tracking-wide text-neutral-400">{label}</p>
      <p className="truncate text-lg font-semibold text-neutral-900">{value}</p>
    </div>
  )
}

/** Where a section drawn from an artifact came from. */
function Provenance({ artifact, onNavigateToExecution }: { artifact: LatestArtifact; onNavigateToExecution: (id: string) => void }) {
  return (
    <p className="text-[11px] text-neutral-400">
      From the scan of {new Date(artifact.createdAt).toLocaleString()} ·{' '}
      <button type="button" onClick={() => onNavigateToExecution(artifact.executionId)} className="text-violet-600 hover:underline">
        view execution
      </button>
    </p>
  )
}

/** A repository's own page — full width, opened in place of the list (like an execution). A slim header and two rows of
 * tabs in groups; only the selected tab is shown, each at its own address (release 7; 04-FRONTEND-SPEC.md). */
export function RepositoryDetailPage({
  repositoryId,
  refreshToken,
  onBack,
  onChanged,
  onDeleted,
  onNavigateToExecution,
  onOpenEstateSoap,
}: RepositoryDetailPageProps) {
  const { showToast } = useToast()
  const [repo, setRepo] = useState<RepositoryDetail | null>(null)
  const isAdmin = useIsAdmin()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [busy, setBusy] = useState(false)

  const [localRefresh, setLocalRefresh] = useState(0)
  // The newest stored result of each kind, without its lists: each view asks for its own, a page at a time.
  const { artifacts, results } = useLatestArtifacts(repositoryId, refreshToken + localRefresh)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getRepository(repositoryId)
      .then((result) => {
        if (!cancelled) setRepo(result)
      })
      .catch(() => {
        if (!cancelled) setError('Could not load this repository.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken, localRefresh])

  function refreshLocal() {
    setLocalRefresh((token) => token + 1)
  }

  // While git clones or fetches, follow its progress.
  const cloning = repo?.ingest_status === 'cloning'
  useEffect(() => {
    if (!cloning) return
    const timer = setTimeout(() => setLocalRefresh((token) => token + 1), 3000)
    return () => clearTimeout(timer)
  }, [cloning, localRefresh])

  async function handleRescan() {
    setBusy(true)
    try {
      await rescanRepository(repositoryId)
      showToast('success', 'Rescan launched.')
      refreshLocal()
      onChanged()
    } catch {
      showToast('error', 'Could not launch a rescan.')
    } finally {
      setBusy(false)
    }
  }

  async function handleVerifyPath() {
    setBusy(true)
    try {
      const result = await verifyRepositoryPath(repositoryId)
      showToast(result.exists ? 'success' : 'error', result.exists ? 'Path confirmed.' : 'Path is missing.')
      refreshLocal()
    } catch {
      showToast('error', 'Could not verify the path.')
    } finally {
      setBusy(false)
    }
  }

  const loadDeletionPlan = useCallback(() => getRepositoryDeletionPlan(repositoryId), [repositoryId])

  async function handleRestore() {
    setBusy(true)
    try {
      await restoreRepository(repositoryId)
      showToast('success', 'Repository restored.')
      refreshLocal()
      onChanged()
    } catch {
      showToast('error', 'Could not restore this repository.')
    } finally {
      setBusy(false)
    }
  }

  // ---------- tabs (release 7): only the selected tab is shown; each has its own address ----------

  const [tab, setTab] = useState<TabSlug>(() => {
    const route = parseRepositoryRoute()
    return initialTab(repositoryId, route?.repositoryId === repositoryId ? route.tab : null, window.location.hash)
  })
  // A tab's content is loaded the first time its tab is opened, and kept (hidden) after that.
  const [visited, setVisited] = useState<ReadonlySet<TabSlug>>(() => new Set([tab]))
  const rootRef = useRef<HTMLDivElement>(null)
  const tabRef = useRef(tab)
  tabRef.current = tab
  // Each group's last tab, so choosing a group reopens it.
  const lastInGroup = useRef<Partial<Record<GroupKey, TabSlug>>>({ [groupOf(tab)]: tab })

  const scroller = useCallback((): HTMLElement | null => {
    for (let node = rootRef.current?.parentElement ?? null; node; node = node.parentElement) {
      const overflow = getComputedStyle(node).overflowY
      if (overflow === 'auto' || overflow === 'scroll') return node
    }
    return (document.scrollingElement as HTMLElement | null) ?? null
  }, [])

  const show = useCallback(
    (next: TabSlug, push: boolean) => {
      const element = scroller()
      if (element) rememberScroll(repositoryId, tabRef.current, element.scrollTop)
      setTab(next)
      lastInGroup.current[groupOf(next)] = next
      setVisited((current) => (current.has(next) ? current : new Set([...current, next])))
      rememberTab(repositoryId, next)
      if (push) setRepositoryTabRoute(repositoryId, next, false)
    },
    [repositoryId, scroller],
  )

  // The address names the tab shown: a bare /repositories/<id>, or an old #repo-… link, is replaced, not added to.
  useEffect(() => {
    setRepositoryTabRoute(repositoryId, tabRef.current, true)
    rememberTab(repositoryId, tabRef.current)
  }, [repositoryId])

  // Back and Forward move between tabs.
  useEffect(() => {
    function onPopState() {
      const route = parseRepositoryRoute()
      if (route?.repositoryId !== repositoryId) return
      const next = initialTab(repositoryId, route.tab, window.location.hash)
      if (next !== tabRef.current) show(next, false)
      if (!route.tab) setRepositoryTabRoute(repositoryId, next, true)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [repositoryId, show])

  // Each tab's scroll position: restored when the tab is shown, kept as it scrolls.
  useLayoutEffect(() => {
    const element = scroller()
    if (element) element.scrollTop = rememberedScroll(repositoryId, tab)
  }, [repositoryId, tab, scroller, loading])
  useEffect(() => {
    const element = scroller()
    if (!element) return
    let frame = 0
    const onScroll = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => rememberScroll(repositoryId, tabRef.current, element.scrollTop))
    }
    element.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      element.removeEventListener('scroll', onScroll)
    }
  }, [repositoryId, scroller, loading])

  const summary = useRepositorySummary(repositoryId, artifacts, refreshToken + localRefresh)

  // The sticky header's height, as --repo-header, so a tab's own sticky bar (Surface's) sits just below it.
  const headerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const header = headerRef.current
    const root = rootRef.current
    if (!header || !root || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => root.style.setProperty('--repo-header', `${header.offsetHeight}px`))
    observer.observe(header)
    return () => observer.disconnect()
  }, [loading])

  const back = (
    <button type="button" onClick={onBack} className="text-sm text-violet-600 hover:underline">
      ← Back to repositories
    </button>
  )

  if (loading && !repo) return <div className="p-6 text-sm text-neutral-400">Loading…</div>
  if (error || !repo) {
    return (
      <div className="space-y-4 p-6">
        {back}
        <EmptyState title="Could not load repository" description={error ?? undefined} />
      </div>
    )
  }

  // Summary tiles: the repository row, plus the newest artifact of each kind.
  const structure = obj(artifacts['solution-project-inventory']?.data.summary)
  const inbound = obj(artifacts['entry-point-inventory']?.data.summary)
  const outbound = obj(artifacts['outbound-invocation-inventory']?.data.summary)
  const verdicts = obj(outbound.countByVerdict)
  const work = obj(artifacts['item-occurrences']?.data.summary)
  const workFigures = workItemFigures(work)
  const dependencies = artifacts['dependency-assessment']
  const dependencySummary = obj(dependencies?.data.summary)
  const dependencyOutcomes = obj(dependencySummary.countByOutcome)
  const dash = <span className="text-neutral-300">—</span>
  const topLanguage = repo.primary_languages?.[0]

  const fingerprint = artifacts['application-fingerprint']
  const occurrences = artifacts['item-occurrences']
  const fingerprintSummary = obj(fingerprint?.data.summary)

  // Tab labels carry a count or a state where it helps: "Work list · 28", "Conversion · ready".
  const badge: Partial<Record<TabSlug, string | number>> = {
    surface: summary.requestEntryPoints?.value,
    projects: summary.projects,
    dependencies: summary.dependenciesNeedingChange?.value,
    'work-list': summary.workItems?.value,
    conversion: summary.conversion?.value,
    executions: summary.executions,
  }
  const group = groupOf(tab)

  const content: Record<TabSlug, () => React.ReactNode> = {
    overview: () => (
      <RepositoryOverview
        repo={repo}
        summary={summary}
        tiles={
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-9">
            <Tile label="Size" value={repo.size_bytes !== null ? formatBytes(repo.size_bytes) : dash} />
            <Tile label="Files" value={repo.file_count ?? dash} />
            <Tile label="Main language" value={topLanguage ? `${topLanguage.language} ${topLanguage.percentage}%` : dash} />
            <Tile label="Projects" value={artifacts['solution-project-inventory'] ? num(structure.project_file_count) : dash} />
            <Tile
              label="Request entry points"
              value={artifacts['entry-point-inventory'] ? num(inbound.requestEntryPointCount) : dash}
              hint="Inbound: what can call this repository"
            />
            <Tile
              label="Linux incompatible"
              value={artifacts['outbound-invocation-inventory'] ? num(verdicts.incompatible) : dash}
              tone={num(verdicts.incompatible) > 0 ? 'red' : undefined}
              hint="Outbound invocations whose Linux verdict is incompatible"
            />
            <Tile
              label="Version drift"
              value={dependencies ? num(dependencySummary.versionDriftCount) : dash}
              tone={num(dependencySummary.versionDriftCount) > 0 ? 'amber' : undefined}
              hint="Packages referenced at more than one version across projects (dependency-assessment): consolidate before upgrading"
            />
            <Tile
              label="Item findings"
              value={occurrences ? num(work.found) - num(work.possible_only_found) : dash}
              hint="Catalog items found by item-detection, counted once per project (the repository list counts each item once). Findings resting only on ambiguous evidence (possible) are not counted."
            />
            <Tile label="Last scanned" value={formatRelative(repo.last_scanned_at)} />
          </div>
        }
        onOpenTab={(next) => show(next, true)}
      />
    ),
    surface: () => (
      <Panel
        summary={
          artifacts['entry-point-inventory'] || artifacts['outbound-invocation-inventory']
            ? `${num(inbound.requestEntryPointCount)} request entry points · ${num(outbound.invocationCount) - num(outbound.unusedCount)} outbound invocations${num(verdicts.incompatible) > 0 ? ` · ${num(verdicts.incompatible)} incompatible` : ''}`
            : 'inbound and outbound'
        }
        bare
      >
        <RepositorySurfaceSection repositoryId={repo.id} localPath={repo.local_path} refreshToken={localRefresh} onOpenEstateSoap={onOpenEstateSoap} />
      </Panel>
    ),
    projects: () => (
      <Panel
        summary={
          artifacts['solution-project-inventory']
            ? `${num(structure.solution_count)} solution(s) · ${num(structure.project_file_count)} project(s)${fingerprint ? ` · ${num(fingerprintSummary.totalSignals)} signals` : ''}`
            : undefined
        }
      >
        <div className="grid gap-6 xl:grid-cols-2">
          <div className="min-w-0">
            <RepositoryStructureSection repositoryId={repo.id} refreshToken={localRefresh} />
          </div>
          <div className="min-w-0 space-y-2">
            <h3 className="text-sm font-semibold text-neutral-900">Fingerprint</h3>
            {fingerprint ? (
              <>
                <Provenance artifact={fingerprint} onNavigateToExecution={onNavigateToExecution} />
                <StoredFingerprintView artifactId={fingerprint.artifactId} head={fingerprint.data} localPath={repo.local_path} />
              </>
            ) : (
              <p className="text-sm text-neutral-400">Application fingerprinting (application-fingerprinting) hasn't run for this repository yet.</p>
            )}
          </div>
        </div>
      </Panel>
    ),
    dependencies: () => (
      <Panel
        summary={
          dependencies
            ? `${num(dependencySummary.packageCount)} package references · ${num(dependencyOutcomes.no_compatible_version)} no compatible version · ${num(dependencyOutcomes.upgrade_breaking)} breaking · ${num(dependencySummary.vulnerableCount)} vulnerable · ${num(dependencySummary.versionDriftCount)} version drift`
            : undefined
        }
      >
        {dependencies ? (
          <div className="space-y-2">
            <Provenance artifact={dependencies} onNavigateToExecution={onNavigateToExecution} />
            <StoredDependenciesView artifactId={dependencies.artifactId} head={dependencies.data} localPath={repo.local_path} />
          </div>
        ) : (
          <p className="text-sm text-neutral-400">Dependency assessment (dependency-assessment) hasn't run for this repository yet.</p>
        )}
      </Panel>
    ),
    'dependency-graph': () => (
      <Panel summary="projects, packages and assembly references, from the roots down">
        <StructureSection repositoryId={repo.id} localPath={repo.local_path} refreshToken={localRefresh} assessmentId={dependencies?.artifactId ?? null} />
      </Panel>
    ),
    impact: () => (
      <Panel>
        <RepositoryImpactSection repositoryId={repo.id} localPath={repo.local_path} refreshToken={localRefresh} />
      </Panel>
    ),
    tests: () => (
      <Panel>
        <RepositoryTestsSection repositoryId={repo.id} localPath={repo.local_path} refreshToken={localRefresh} />
      </Panel>
    ),
    'work-list': () => (
      <Panel
        summary={
          occurrences
            ? `${workItemsLine(workFigures.workItems, workFigures.possible)} · ${num(work.not_checked)} not checked`
            : undefined
        }
      >
        {occurrences ? (
          <div className="space-y-2">
            <Provenance artifact={occurrences} onNavigateToExecution={onNavigateToExecution} />
            <StoredWorkListView artifactId={occurrences.artifactId} head={occurrences.data} localPath={repo.local_path} />
          </div>
        ) : (
          <p className="text-sm text-neutral-400">Item detection (item-detection) hasn't run for this repository yet.</p>
        )}
      </Panel>
    ),
    conversion: () => (
      <Panel>
        <div className="space-y-4">
          <ConversionsPanel repositoryId={repo.id} refreshToken={localRefresh} refusal={refusal} />
        </div>
      </Panel>
    ),
    executions: () => (
      <Panel summary="discovery runs of this repository, newest first">
        <ExecutionHistory repositoryId={repo.id} refreshToken={localRefresh} onNavigateToExecution={onNavigateToExecution} />
      </Panel>
    ),
    details: () => (
      <Panel summary={repo.technical_owner ? `owner ${repo.technical_owner}` : undefined}>
        {editing ? (
          <EditForm
            repo={repo}
            onCancel={() => setEditing(false)}
            onSaved={() => {
              setEditing(false)
              refreshLocal()
              onChanged()
            }}
          />
        ) : (
          <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-2 xl:grid-cols-3">
            <Metadata label="Root folder">{repo.root_folder_name}</Metadata>
            {/* The folder it was registered from: its owner's, on their machine. Each person's own is "your clone". */}
            <Metadata label={repo.registered_host ? `Registered folder (on ${repo.registered_host})` : 'Registered folder'}>
              <span className="break-all font-mono text-xs">{repo.local_path}</span>
            </Metadata>
            <Metadata label="Clone URL">
              {repo.clone_url ? <span className="break-all font-mono text-xs">{repo.clone_url}</span> : <span className="text-neutral-400">Not under source control</span>}
            </Metadata>
            <Metadata label="Detected remote">
              {repo.detected_clone_url ? <span className="break-all font-mono text-xs">{repo.detected_clone_url}</span> : '—'}
            </Metadata>
            <Metadata label="Provider">{repo.provider ?? '—'}</Metadata>
            <Metadata label="Organization">{repo.organization ?? '—'}</Metadata>
            <Metadata label="Default branch">{repo.default_branch ?? '—'}</Metadata>
            <Metadata label="Commit SHA">
              {repo.has_git_history ? <span className="font-mono text-xs">{repo.ingest_commit_sha?.slice(0, 12)}</span> : 'no git history'}
            </Metadata>
            <Metadata label="Last commit">{repo.last_commit_date ? new Date(repo.last_commit_date).toLocaleString() : '—'}</Metadata>
            <Metadata label="Primary languages">
              {repo.primary_languages && repo.primary_languages.length > 0
                ? repo.primary_languages.map((entry) => `${entry.language} (${entry.percentage}%)`).join(', ')
                : '—'}
            </Metadata>
            <Metadata label="Source status">{repo.source_status ?? '—'}</Metadata>
            <Metadata label="Technical owner">{repo.technical_owner ?? '—'}</Metadata>
            <Metadata label="Description">{repo.description ?? '—'}</Metadata>
            <Metadata label="Tags">{repo.tags.length ? repo.tags.join(', ') : '—'}</Metadata>
            <Metadata label="Notes">{repo.notes ?? '—'}</Metadata>
            <Metadata label="First registered">{repo.first_registered_at ? new Date(repo.first_registered_at).toLocaleString() : '—'}</Metadata>
            <Metadata label="Last scanned">{repo.last_scanned_at ? new Date(repo.last_scanned_at).toLocaleString() : 'never'}</Metadata>
            <Metadata label="Repository id">
              <span className="break-all font-mono text-xs">{repo.id}</span>
            </Metadata>
          </dl>
        )}
      </Panel>
    ),
  }

  const actionClass =
    'rounded border border-neutral-300 px-2.5 py-1 text-xs text-neutral-700 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50'
  // Read-only unless this person owns it (or is an admin), on the machine it was registered on: the backend's words.
  const refusal = repo.can_act === false ? (repo.cannot_act_reason ?? 'Only its owner or an admin may do this.') : null
  const ownerRefusal = repo.cannot_edit_reason ?? null

  return (
    <div ref={rootRef} className="space-y-3 px-4 pb-10 pt-3 sm:px-6">
      {back}

      {/* The slim header: name, status chips and actions, on every tab, above the tab rows. */}
      <div ref={headerRef} className="sticky top-0 z-20 -mx-4 border-b border-neutral-200 bg-white/95 px-4 pt-2 backdrop-blur sm:-mx-6 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <h2 className="truncate text-lg font-semibold text-neutral-900" title={repo.local_path}>
              {repo.name}
            </h2>
            <IngestStatusBadge status={repo.ingest_status} />
            <CriticalityBadge criticality={repo.criticality} />
            <CloneUrlVerificationBadge verification={repo.clone_url_verification} />
            <RetirementBadge status={repo.retirement_status} />
            <RepositoryOwner repo={repo} onChanged={refreshLocal} />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {repo.deleted_at ? (
              <button type="button" onClick={handleRestore} disabled={busy || !isAdmin} title={isAdmin ? undefined : ADMIN_ONLY} className={actionClass}>
                Restore
              </button>
            ) : (
              <>
                <button type="button" onClick={handleVerifyPath} disabled={busy || !!refusal} title={refusal ?? undefined} className={actionClass}>
                  Verify path
                </button>
                <button type="button" onClick={handleRescan} disabled={busy || !!refusal} title={refusal ?? undefined} className={actionClass}>
                  Rescan
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setEditing((value) => !value)
                    show('details', true)
                  }}
                  disabled={!!ownerRefusal}
                  title={ownerRefusal ?? undefined}
                  className={actionClass}
                >
                  {editing ? 'Cancel edit' : 'Edit'}
                </button>
                <button
                  type="button"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={busy || !!refusal}
                  title={refusal ?? undefined}
                  className="rounded border border-red-300 px-2.5 py-1 text-xs text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Delete
                </button>
              </>
            )}
          </div>
        </div>
        {refusal && !repo.deleted_at && (
          <p className="mt-1 text-xs text-neutral-500" data-testid="read-only-note">
            Read-only for you: {refusal}
          </p>
        )}
        <div>
        </div>

        <nav aria-label="Tab groups" className="mt-2 flex gap-1 overflow-x-auto" role="tablist">
          {GROUPS.map((g) => (
            <button
              key={g.key}
              type="button"
              role="tab"
              aria-selected={group === g.key}
              onClick={() => {
                if (g.key !== group) show(g.key === 'overview' ? 'overview' : lastTabIn(g.key), true)
              }}
              className={`shrink-0 whitespace-nowrap border-b-2 px-3 py-1.5 text-sm font-medium ${
                group === g.key ? 'border-violet-600 text-neutral-900' : 'border-transparent text-neutral-500 hover:text-neutral-800'
              }`}
            >
              {g.label}
            </button>
          ))}
        </nav>
        {group !== 'overview' && (
          <nav aria-label="Tabs" className="-mx-1 flex gap-1 overflow-x-auto border-t border-neutral-100 py-1.5" role="tablist">
            {tabsOf(group).map((t) => (
              <button
                key={t.slug}
                type="button"
                role="tab"
                aria-selected={tab === t.slug}
                aria-controls={`repo-panel-${t.slug}`}
                onClick={() => tab !== t.slug && show(t.slug, true)}
                className={`shrink-0 whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium ${
                  tab === t.slug ? 'bg-violet-100 text-violet-800' : 'text-neutral-600 hover:bg-violet-50 hover:text-violet-700'
                }`}
              >
                {t.label}
                {badge[t.slug] !== undefined && <span className="text-neutral-400"> · {badge[t.slug]}</span>}
              </button>
            ))}
          </nav>
        )}
      </div>

      {repo.deleted_at && (
        <p className="rounded bg-neutral-100 px-3 py-2 text-sm text-neutral-600">Soft-deleted at {new Date(repo.deleted_at).toLocaleString()}.</p>
      )}
      {repo.ingest_status === 'cloning' && (
        <p className="rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-800">
          git is working: <span className="font-mono text-xs">{repo.clone_progress ?? 'starting'}</span>
        </p>
      )}
      {repo.ingest_status === 'scan_failed' && repo.ingest_error && (
        <p className="whitespace-pre-wrap rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">{repo.ingest_error}</p>
      )}
      <LimitedList items={repo.warnings} name={(warning) => warning} noun="warnings">
        {(visible) => (
          <div className="space-y-2">
            {visible.map((warning) => (
              <p key={warning} className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                {warning}
              </p>
            ))}
          </div>
        )}
      </LimitedList>
      {repo.ingest_status === 'path_missing' && (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          The registered folder is currently missing at <code className="font-mono">{repo.local_path}</code>.
        </p>
      )}

      {results?.not_copied_note && (
        <p className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800" data-testid="not-copied-note">
          {results.not_copied_note}
        </p>
      )}
      <RepositoryFiles repository={repo} onRecorded={setRepo}>
        {repo.files_held_on && (
          <p className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs text-neutral-600" data-testid="files-held-on">
            Scanned {repo.files_held_on}: its results are read from the database. Its worktrees, logs and evidence stay there.
          </p>
        )}
        <YourClone path={repo.my_clone_path ?? null} />

        {TABS.filter((t) => visited.has(t.slug)).map((t) => (
          <div key={t.slug} id={`repo-panel-${t.slug}`} role="tabpanel" aria-label={t.label} hidden={t.slug !== tab}>
            {content[t.slug]()}
          </div>
        ))}
      </RepositoryFiles>

      {showDeleteConfirm && (
        <HardDeleteDialog
          title={`Delete repository ${repo.name}`}
          loadPlan={loadDeletionPlan}
          onDelete={(typed) => deleteRepositoryHard(repositoryId, typed)}
          onClose={() => setShowDeleteConfirm(false)}
          onDeleted={() => {
            showToast('success', `${repo.name} deleted.`)
            setShowDeleteConfirm(false)
            onDeleted()
          }}
        />
      )}
    </div>
  )

  /** A group's tab to open: the last one shown in it, else its first. */
  function lastTabIn(key: GroupKey): TabSlug {
    return lastInGroup.current[key] ?? tabsOf(key)[0].slug
  }
}

/** One tab's content, with its one-line summary. `bare`: content that draws its own sections (Surface). */
function Panel({ summary, bare = false, children }: { summary?: string; bare?: boolean; children: React.ReactNode }) {
  return (
    <section className={bare ? 'min-w-0 space-y-2' : 'min-w-0 space-y-3 rounded border border-neutral-200 bg-white p-4'}>
      {summary && <p className="text-xs text-neutral-500">{summary}</p>}
      {children}
    </section>
  )
}

function ExecutionHistory({
  repositoryId,
  refreshToken,
  onNavigateToExecution,
}: {
  repositoryId: string
  refreshToken: number
  onNavigateToExecution: (executionId: string) => void
}) {
  const [executions, setExecutions] = useState<JobExecution[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listRepositoryExecutions(repositoryId)
      .then((result) => {
        if (!cancelled) setExecutions(result)
      })
      .catch(() => {
        if (!cancelled) setExecutions([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  if (loading) return <p className="text-sm text-neutral-400">Loading…</p>
  if (executions.length === 0) return <p className="text-sm text-neutral-400">Discovery has not run yet.</p>

  return (
    <LimitedList
      items={executions}
      name={(execution) => [execution.batch_status, execution.exit_status, execution.triggered_by]}
      noun="executions"
    >
      {(visible) => (
    <div className="overflow-x-auto">
    <table className="w-full min-w-[560px] text-left text-sm">
      <thead className="text-xs uppercase tracking-wide text-neutral-500">
        <tr>
          <th className="py-1.5 pr-3 font-medium">Batch status</th>
          <th className="py-1.5 pr-3 font-medium">Exit status</th>
          <th className="py-1.5 pr-3 font-medium">Steps</th>
          <th className="py-1.5 pr-3 font-medium">Started</th>
          <th className="py-1.5 font-medium">Triggered by</th>
        </tr>
      </thead>
      <tbody>
        {visible.map((execution) => (
          <tr
            key={execution.id}
            onClick={() => onNavigateToExecution(execution.id)}
            className="cursor-pointer border-t border-neutral-100 hover:bg-neutral-50"
          >
            <td className="py-1.5 pr-3">
              <BatchStatusBadge status={execution.batch_status} />
            </td>
            <td className="py-1.5 pr-3">
              <ExitStatusBadge status={execution.exit_status} />
            </td>
            <td className="py-1.5 pr-3 text-neutral-500">
              {execution.step_summary.completed + execution.step_summary.not_implemented}/{execution.step_summary.total}
            </td>
            <td className="py-1.5 pr-3 whitespace-nowrap text-neutral-500">
              {execution.started_at ? new Date(execution.started_at).toLocaleString() : '—'}
            </td>
            <td className="py-1.5 text-neutral-500">{execution.triggered_by ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
      )}
    </LimitedList>
  )
}

function Metadata({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</dt>
      <dd className="mt-0.5 text-neutral-800">{children}</dd>
    </div>
  )
}

function EditForm({
  repo,
  onCancel,
  onSaved,
}: {
  repo: RepositoryDetail
  onCancel: () => void
  onSaved: () => void
}) {
  const { showToast } = useToast()
  const [name, setName] = useState(repo.name)
  const [description, setDescription] = useState(repo.description ?? '')
  const [technicalOwner, setTechnicalOwner] = useState(repo.technical_owner ?? '')
  const [criticality, setCriticality] = useState<Criticality>(repo.criticality)
  const [retirementStatus, setRetirementStatus] = useState<RetirementStatus>(repo.retirement_status)
  const [defaultBranch, setDefaultBranch] = useState(repo.default_branch ?? '')
  const [tags, setTags] = useState<string[]>(repo.tags)
  const [notes, setNotes] = useState(repo.notes ?? '')
  const [saving, setSaving] = useState(false)

  async function handleSubmit() {
    setSaving(true)
    try {
      await updateRepository(repo.id, {
        name,
        description: description.trim() || null,
        technical_owner: technicalOwner.trim() || null,
        criticality,
        retirement_status: retirementStatus,
        tags,
        notes: notes.trim() || null,
        default_branch: defaultBranch.trim() || null,
      })
      showToast('success', 'Repository updated.')
      onSaved()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not update this repository.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 rounded border border-neutral-200 p-4">
      <Field label="Name">
        <input value={name} onChange={(event) => setName(event.target.value)} className={inputClass(false)} />
      </Field>
      <Field label="Description">
        <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={2} className={inputClass(false)} />
      </Field>
      <Field label="Technical owner">
        <input value={technicalOwner} onChange={(event) => setTechnicalOwner(event.target.value)} className={inputClass(false)} />
      </Field>
      <Field label="Criticality">
        <select value={criticality} onChange={(event) => setCriticality(event.target.value as Criticality)} className={inputClass(false)}>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="critical">Critical</option>
        </select>
      </Field>
      <Field label="Retirement status">
        <select
          value={retirementStatus}
          onChange={(event) => setRetirementStatus(event.target.value as RetirementStatus)}
          className={inputClass(false)}
        >
          <option value="active">Active</option>
          <option value="slated_for_retirement">Slated for retirement</option>
          <option value="decommissioned">Decommissioned</option>
        </select>
      </Field>
      <Field label="Default branch">
        <input value={defaultBranch} onChange={(event) => setDefaultBranch(event.target.value)} className={inputClass(false)} />
      </Field>
      <TagInput label="Tags" values={tags} onChange={setTags} />
      <Field label="Notes">
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={2} className={inputClass(false)} />
      </Field>
      <div className="flex justify-end gap-2 pt-2">
        <button type="button" onClick={onCancel} className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50">
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={saving}
          className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
    </div>
  )
}

/** Where this person's file links open from: their own clone on this machine, or an offer to record one. */
function YourClone({ path }: { path: string | null }) {
  const askForClone = useAskForClone()
  return (
    <p className="text-xs text-neutral-500" data-testid="your-clone">
      {path ? (
        <>
          File links open from your clone: <span className="font-mono text-neutral-700">{path}</span>{' '}
        </>
      ) : (
        <>No clone of yours is recorded on this machine: file links offer to record one, or copy the relative path. </>
      )}
      {askForClone && (
        <button type="button" onClick={askForClone} className="text-violet-700 hover:underline">
          {path ? 'Change' : 'Record your clone'}
        </button>
      )}
    </p>
  )
}