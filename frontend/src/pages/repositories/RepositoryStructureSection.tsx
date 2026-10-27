import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { artifactsPage, projectsPage, solutionMembers, solutionsPage, structureWarnings } from '../../api/results'
import { getRepositoryStructure } from '../../api/structure'
import type { ParseWarning, ProjectSummary, RepositoryArtifact, RepositoryStructure, Solution, SolutionProjectMember } from '../../types/structure'
import { LimitedList } from '../../components/LimitedList'
import { PagedList } from '../../components/PagedList'

interface RepositoryStructureSectionProps {
  repositoryId: string
  refreshToken: number
}

function ScanStatusBadge({ status }: { status: RepositoryStructure['scan_status'] }) {
  const styles: Record<RepositoryStructure['scan_status'], string> = {
    complete: 'bg-teal-50 text-teal-700 border-teal-200',
    partial: 'bg-amber-50 text-amber-700 border-amber-200',
    failed: 'bg-red-50 text-red-700 border-red-200',
  }
  return (
    <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${styles[status]}`}>{status}</span>
  )
}

function StatCard({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded border border-neutral-200 bg-neutral-50 px-3 py-2">
      <p className="text-xs font-medium uppercase tracking-wide text-neutral-400">{label}</p>
      <p className="text-lg font-semibold text-neutral-900">{value ?? '—'}</p>
    </div>
  )
}

function FrameworkBars({ families }: { families: Record<string, number> }) {
  const entries = Object.entries(families).sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...entries.map(([, count]) => count))
  return (
    <LimitedList items={entries} name={([family]) => family} noun="frameworks" empty={<p className="text-sm text-neutral-400">No frameworks detected.</p>}>
      {(visible) => (
        <div className="space-y-1.5">
          {visible.map(([family, count]) => (
            <div key={family} className="flex items-center gap-2 text-xs">
              <span className="w-28 flex-none truncate text-neutral-600">{family}</span>
              <div className="h-2 flex-1 rounded bg-neutral-100">
                <div className="h-2 rounded bg-violet-500" style={{ width: `${(count / max) * 100}%` }} />
              </div>
              <span className="w-6 flex-none text-right text-neutral-500">{count}</span>
            </div>
          ))}
        </div>
      )}
    </LimitedList>
  )
}

function SolutionRow({ repositoryId, solution, refreshToken }: { repositoryId: string; solution: Solution; refreshToken: number }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="rounded border border-neutral-200">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-neutral-50"
      >
        <span className="min-w-0 break-all font-medium text-neutral-800">{solution.name}</span>
        <span className="flex shrink-0 items-center gap-2 text-xs text-neutral-400">
          {solution.resolved_project_count}/{solution.project_count} resolved
          {solution.missing_project_count ? (
            <span className="text-amber-600">{solution.missing_project_count} missing</span>
          ) : null}
          <span>{expanded ? '▲' : '▼'}</span>
        </span>
      </button>
      {expanded && (
        <div className="border-t border-neutral-100 px-3 py-2">
          <p className="mb-1 font-mono text-xs text-neutral-400">{solution.relative_path}</p>
          {solution.parse_error && <p className="mb-1 text-xs text-red-600">{solution.parse_error}</p>}
          <PagedList<SolutionProjectMember> load={solutionMembers(repositoryId, solution.id)} resetKey={`${repositoryId}|${refreshToken}|${solution.id}`} noun="projects">
            {(visible) => (
              <ul className="space-y-1">
                {visible.map((member) => (
                  <li key={member.raw_path} className="flex items-center justify-between gap-2 text-xs">
                    <span className="min-w-0 break-all font-mono text-neutral-700">{member.relative_path ?? member.raw_path}</span>
                    {member.resolution_status === 'unresolved' ? (
                      <span className="shrink-0 rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">missing</span>
                    ) : (
                      <span className="shrink-0 text-neutral-400">resolved</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </PagedList>
        </div>
      )}
    </div>
  )
}

/** The counts per category are the scan's own (artifact_counts); the paths come a page at a time. */
function ArtifactCounts({ repositoryId, counts, refreshToken }: { repositoryId: string; counts: Record<string, number>; refreshToken: number }) {
  const [expanded, setExpanded] = useState(false)
  const categories = Object.entries(counts).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1])

  if (categories.length === 0) return <p className="text-sm text-neutral-400">No supporting artifacts found.</p>

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {categories.map(([category, count]) => (
          <span key={category} className="rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs text-neutral-600">
            {category} · {count}
          </span>
        ))}
      </div>
      <button type="button" onClick={() => setExpanded((v) => !v)} className="mt-2 text-xs text-violet-600 hover:underline">
        {expanded ? 'Hide paths' : 'Show paths'}
      </button>
      {expanded && (
        <PagedList<RepositoryArtifact> load={artifactsPage(repositoryId)} resetKey={`${repositoryId}|${refreshToken}`} noun="artifacts" className="mt-2">
          {(visible) => (
            <ul className="max-h-40 space-y-0.5 overflow-y-auto break-all font-mono text-xs text-neutral-500">
              {visible.map((artifact) => (
                <li key={artifact.relative_path}>{artifact.relative_path}</li>
              ))}
            </ul>
          )}
        </PagedList>
      )}
    </div>
  )
}

export function RepositoryStructureSection({ repositoryId, refreshToken }: RepositoryStructureSectionProps) {
  const [structure, setStructure] = useState<RepositoryStructure | null>(null)
  const [notScanned, setNotScanned] = useState(false)
  const [loading, setLoading] = useState(true)
  const [warningsExpanded, setWarningsExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setNotScanned(false)

    // The summary without its warnings; the solutions, projects, artifacts and warnings come a page at a time.
    getRepositoryStructure(repositoryId, false)
      .then((result) => {
        if (!cancelled) setStructure(result)
      })
      .catch((err) => {
        if (cancelled) return
        if (err instanceof ApiError && err.status === 409) {
          setNotScanned(true)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  if (loading) return <p className="text-sm text-neutral-400">Loading structure…</p>

  if (notScanned || !structure) {
    return (
      <div className="rounded border border-dashed border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-500">
        Solution & project discovery (lifecycle step 2) hasn't run for this repository yet.
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-neutral-900">Structure</h3>
        <ScanStatusBadge status={structure.scan_status} />
      </div>

      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        <StatCard label="Solutions" value={structure.solution_count} />
        <StatCard label="Projects" value={structure.project_file_count} />
        <StatCard label="Standalone" value={structure.standalone_project_count} />
        <StatCard label="Shared" value={structure.shared_project_count} />
        <StatCard label="Unresolved" value={structure.unresolved_reference_count} />
        <StatCard label="Legacy" value={structure.legacy_project_count} />
        <StatCard label="SDK-style" value={structure.sdk_project_count} />
      </div>

      <div className="grid grid-cols-3 gap-2">
        <StatCard label="Out of scope" value={structure.out_of_scope_project_count} />
        <StatCard label="Unknown type" value={structure.unknown_project_count} />
        <StatCard label="Failed to parse" value={structure.failed_parse_count} />
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-400">Framework distribution</h4>
        <FrameworkBars families={structure.framework_families} />
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-400">Solutions</h4>
        <PagedList<Solution>
          load={solutionsPage(repositoryId)}
          resetKey={`${repositoryId}|${refreshToken}`}
          noun="solutions"
          empty={<p className="text-sm text-neutral-400">No .sln files found.</p>}
        >
          {(visible) => (
            <div className="space-y-1.5">
              {visible.map((solution) => (
                <SolutionRow key={solution.id} repositoryId={repositoryId} solution={solution} refreshToken={refreshToken} />
              ))}
            </div>
          )}
        </PagedList>
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-400">
          Standalone projects ({structure.standalone_project_count ?? 0})
        </h4>
        <PagedList<ProjectSummary>
          load={projectsPage(repositoryId, true)}
          resetKey={`${repositoryId}|${refreshToken}|standalone`}
          noun="projects"
          empty={<p className="text-sm text-neutral-400">Every project belongs to at least one solution.</p>}
        >
          {(visible) => (
            <ul className="space-y-0.5 break-all font-mono text-xs text-neutral-600">
              {visible.map((project) => (
                <li key={project.id}>{project.relative_path}</li>
              ))}
            </ul>
          )}
        </PagedList>
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-400">Supporting artifacts</h4>
        <ArtifactCounts repositoryId={repositoryId} counts={structure.artifact_counts} refreshToken={refreshToken} />
      </div>

      {structure.parse_warning_count > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setWarningsExpanded((v) => !v)}
            className="text-xs font-semibold uppercase tracking-wide text-amber-600 hover:underline"
          >
            Discovery warnings ({structure.parse_warning_count}) {warningsExpanded ? '▲' : '▼'}
          </button>
          {warningsExpanded && (
            <PagedList<ParseWarning> load={structureWarnings(repositoryId)} resetKey={`${repositoryId}|${refreshToken}`} noun="warnings" className="mt-2">
              {(visible) => (
                <ul className="space-y-1 text-xs text-neutral-600">
                  {visible.map((warning, index) => (
                    <li key={index}>
                      <span className="break-all font-mono text-neutral-400">{warning.path}</span> — {warning.warning}
                    </li>
                  ))}
                </ul>
              )}
            </PagedList>
          )}
        </div>
      )}
    </div>
  )
}
