import { useCallback, useEffect, useState } from 'react'
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
import type { WorkListDecisions } from '../../types/items'
import { getWorkListDecisions } from '../../api/items'
import { ApiError } from '../../api/client'
import { CollapsibleSection } from '../../components/CollapsibleSection'
import { EmptyState } from '../../components/EmptyState'
import { LimitedList } from '../../components/LimitedList'
import { Field, inputClass } from '../../components/FormField'
import { TagInput } from '../../components/TagInput'
import { useToast } from '../../components/Toast'
import { CriticalityBadge, CloneUrlVerificationBadge, IngestStatusBadge, RetirementBadge } from '../../components/RepositoryBadges'
import { BatchStatusBadge, ExitStatusBadge } from '../../components/WorkflowBadges'
import { DependenciesView, FingerprintView, ItemOccurrencesView, formatBytes } from '../workflow/artifacts/renderers'
import { num, obj } from '../workflow/artifacts/adapters'
import { RepositoryStructureSection } from './RepositoryStructureSection'
import { RepositorySurfaceSection } from './RepositorySurfaceSection'
import { RepositoryImpactSection } from './RepositoryImpactSection'
import { RepositoryTestsSection } from './RepositoryTestsSection'
import { ConversionsPanel } from './ConversionsPanel'
import { useLatestArtifacts, type LatestArtifact } from './useLatestArtifacts'

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

const SECTIONS = [
  { id: 'repo-overview', label: 'Overview' },
  { id: 'repo-surface', label: 'Surface' },
  { id: 'repo-structure', label: 'Structure & fingerprint' },
  { id: 'repo-dependencies', label: 'Dependencies' },
  { id: 'repo-worklist', label: 'Work list' },
  { id: 'repo-tests', label: 'Tests' },
  { id: 'repo-impact', label: 'Impact' },
  { id: 'repo-conversion', label: 'Conversion' },
  { id: 'repo-executions', label: 'Executions' },
  { id: 'repo-details', label: 'Details' },
]

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

/** A repository's own page — full width, opened in place of the list (like
 * an execution), with a sticky section bar and collapsible sections. */
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
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [busy, setBusy] = useState(false)

  const [localRefresh, setLocalRefresh] = useState(0)
  const { artifacts } = useLatestArtifacts(repositoryId, refreshToken + localRefresh)
  // Part S: the decision behind each work-list item, derived or manual.
  const [workListDecisions, setWorkListDecisions] = useState<WorkListDecisions | null>(null)
  useEffect(() => {
    let cancelled = false
    getWorkListDecisions(repositoryId)
      .then((result) => {
        if (!cancelled) setWorkListDecisions(result)
      })
      .catch(() => {
        if (!cancelled) setWorkListDecisions(null)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken, localRefresh])

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

  function jumpTo(sectionId: string) {
    document.getElementById(sectionId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

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
  const dependencies = artifacts['dependency-assessment']
  const dependencySummary = obj(dependencies?.data.summary)
  const dependencyOutcomes = obj(dependencySummary.countByOutcome)
  const dash = <span className="text-neutral-300">—</span>
  const topLanguage = repo.primary_languages?.[0]

  const fingerprint = artifacts['application-fingerprint']
  const occurrences = artifacts['item-occurrences']
  const fingerprintSummary = obj(fingerprint?.data.summary)

  return (
    <div className="space-y-4 px-4 pb-10 pt-4 sm:px-6">
      {back}

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-xl font-semibold text-neutral-900">{repo.name}</h2>
          <p className="break-all font-mono text-xs text-neutral-400">{repo.local_path}</p>
          {repo.source_type === 'git_clone' && repo.clone_url && (
            <p className="break-all text-xs text-neutral-400">
              Cloned from <span className="font-mono">{repo.clone_url}</span>
              {repo.default_branch && <> ({repo.default_branch})</>}; Rescan fetches and fast-forwards it first.
            </p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <IngestStatusBadge status={repo.ingest_status} />
            <CriticalityBadge criticality={repo.criticality} />
            <CloneUrlVerificationBadge verification={repo.clone_url_verification} />
            <RetirementBadge status={repo.retirement_status} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {repo.deleted_at ? (
            <button
              type="button"
              onClick={handleRestore}
              disabled={busy}
              className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
            >
              Restore
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={handleVerifyPath}
                disabled={busy}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                Verify path
              </button>
              <button
                type="button"
                onClick={handleRescan}
                disabled={busy}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                Rescan
              </button>
              <button
                type="button"
                onClick={() => {
                  setEditing((value) => !value)
                  jumpTo('repo-details')
                }}
                className="rounded border border-neutral-300 px-3 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
              >
                {editing ? 'Cancel edit' : 'Edit'}
              </button>
              <button
                type="button"
                onClick={() => setShowDeleteConfirm(true)}
                disabled={busy}
                className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50"
              >
                Delete
              </button>
            </>
          )}
        </div>
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
        <p className="whitespace-pre-wrap rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {repo.ingest_error}
        </p>
      )}
      <LimitedList items={repo.warnings} name={(warning) => warning} noun="warnings">
        {(visible) => (
          <div className="space-y-4">
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

      <nav
        aria-label="Sections"
        className="sticky top-0 z-20 -mx-4 flex gap-1 overflow-x-auto border-y border-neutral-200 bg-white/95 px-4 py-1.5 backdrop-blur sm:-mx-6 sm:px-6"
      >
        {SECTIONS.map((section) => (
          <button
            key={section.id}
            type="button"
            onClick={() => jumpTo(section.id)}
            className="whitespace-nowrap rounded px-2.5 py-1 text-xs font-medium text-neutral-600 hover:bg-violet-50 hover:text-violet-700"
          >
            {section.label}
          </button>
        ))}
      </nav>

      <section id="repo-overview" className="scroll-mt-14">
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
            hint="Packages referenced at more than one version across projects (step 6): consolidate before upgrading"
          />
          <Tile
            label="Items found"
            value={occurrences ? num(work.found) - num(work.possible_only_found) : dash}
            hint="Catalog items found by step 7, per project. Findings resting only on ambiguous evidence (possible) are not counted."
          />
          <Tile label="Last scanned" value={formatRelative(repo.last_scanned_at)} />
        </div>
      </section>

      {!editing && (
        <CollapsibleSection
          id="repo:surface"
          anchorId="repo-surface"
          title="Surface"
          summary={
            artifacts['entry-point-inventory'] || artifacts['outbound-invocation-inventory']
              ? `${num(inbound.requestEntryPointCount)} request entry points · ${num(outbound.invocationCount) - num(outbound.unusedCount)} outbound invocations${num(verdicts.incompatible) > 0 ? ` · ${num(verdicts.incompatible)} incompatible` : ''}`
              : 'inbound and outbound'
          }
        >
          <RepositorySurfaceSection repositoryId={repo.id} localPath={repo.local_path} refreshToken={localRefresh} onOpenEstateSoap={onOpenEstateSoap} />
        </CollapsibleSection>
      )}

      {!editing && (
        <CollapsibleSection
          id="repo:structure"
          anchorId="repo-structure"
          title="Structure & fingerprint"
          summary={
            artifacts['solution-project-inventory']
              ? `${num(structure.solution_count)} solution(s) · ${num(structure.project_file_count)} project(s)${fingerprint ? ` · ${num(fingerprintSummary.totalSignals)} signals` : ''}`
              : undefined
          }
        >
          <div className="grid gap-6 p-4 xl:grid-cols-2">
            <div className="min-w-0">
              <RepositoryStructureSection repositoryId={repo.id} refreshToken={localRefresh} />
            </div>
            <div className="min-w-0 space-y-2">
              <h3 className="text-sm font-semibold text-neutral-900">Fingerprint</h3>
              {fingerprint ? (
                <>
                  <Provenance artifact={fingerprint} onNavigateToExecution={onNavigateToExecution} />
                  <FingerprintView data={fingerprint.data} localPath={repo.local_path} />
                </>
              ) : (
                <p className="text-sm text-neutral-400">Application fingerprinting (lifecycle step 3) hasn't run for this repository yet.</p>
              )}
            </div>
          </div>
        </CollapsibleSection>
      )}

      {!editing && (
        <CollapsibleSection
          id="repo:dependencies"
          anchorId="repo-dependencies"
          title="Dependencies"
          summary={
            dependencies
              ? `${num(dependencySummary.packageCount)} package references · ${num(dependencyOutcomes.no_compatible_version)} no compatible version · ${num(dependencyOutcomes.upgrade_breaking)} breaking · ${num(dependencySummary.vulnerableCount)} vulnerable · ${num(dependencySummary.versionDriftCount)} version drift`
              : undefined
          }
        >
          <div className="space-y-2 p-4">
            {dependencies ? (
              <>
                <Provenance artifact={dependencies} onNavigateToExecution={onNavigateToExecution} />
                <DependenciesView data={dependencies.data} localPath={repo.local_path} />
              </>
            ) : (
              <p className="text-sm text-neutral-400">Dependency assessment (lifecycle step 6) hasn't run for this repository yet.</p>
            )}
          </div>
        </CollapsibleSection>
      )}

      {!editing && (
        <CollapsibleSection
          id="repo:worklist"
          anchorId="repo-worklist"
          title="Work list"
          summary={
            occurrences
              ? `${num(work.found) - num(work.possible_only_found)} found · ${num(work.not_checked)} not checked${num(work.possible_occurrence_rows) > 0 ? ` · ${num(work.possible_occurrence_rows)} possible (not counted)` : ''}`
              : undefined
          }
        >
          <div className="space-y-2 p-4">
            {occurrences ? (
              <>
                <Provenance artifact={occurrences} onNavigateToExecution={onNavigateToExecution} />
                <ItemOccurrencesView data={occurrences.data} localPath={repo.local_path} decisions={workListDecisions} />
              </>
            ) : (
              <p className="text-sm text-neutral-400">Item detection (lifecycle step 7) hasn't run for this repository yet.</p>
            )}
          </div>
        </CollapsibleSection>
      )}

      {!editing && (
        <CollapsibleSection id="repo:tests" anchorId="repo-tests" title="Tests">
          <div className="p-4">
            <RepositoryTestsSection repositoryId={repo.id} localPath={repo.local_path} refreshToken={localRefresh} />
          </div>
        </CollapsibleSection>
      )}

      {!editing && (
        <CollapsibleSection id="repo:impact" anchorId="repo-impact" title="Impact">
          <div className="p-4">
            <RepositoryImpactSection repositoryId={repo.id} localPath={repo.local_path} refreshToken={localRefresh} />
          </div>
        </CollapsibleSection>
      )}

      {!editing && (
        <CollapsibleSection id="repo:conversion" anchorId="repo-conversion" title="Conversion">
          <div className="space-y-4 p-4">
            <ConversionsPanel repositoryId={repo.id} refreshToken={localRefresh} />
          </div>
        </CollapsibleSection>
      )}

      <CollapsibleSection id="repo:executions" anchorId="repo-executions" title="Discovery execution history">
        <div className="p-4">
          <ExecutionHistory repositoryId={repo.id} refreshToken={localRefresh} onNavigateToExecution={onNavigateToExecution} />
        </div>
      </CollapsibleSection>

      <CollapsibleSection id="repo:details" anchorId="repo-details" title="Details" summary={repo.technical_owner ? `owner ${repo.technical_owner}` : undefined}>
        <div className="p-4">
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
              <Metadata label="Local path">
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
        </div>
      </CollapsibleSection>

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
