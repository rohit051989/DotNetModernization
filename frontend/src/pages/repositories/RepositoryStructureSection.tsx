import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import {
  getRepositoryStructure,
  listRepositoryArtifacts,
  listRepositoryProjects,
  listRepositorySolutions,
} from '../../api/structure'
import type { ProjectSummary, RepositoryArtifact, RepositoryStructure, Solution } from '../../types/structure'

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
  if (entries.length === 0) return <p className="text-sm text-neutral-400">No frameworks detected.</p>
  return (
    <div className="space-y-1.5">
      {entries.map(([family, count]) => (
        <div key={family} className="flex items-center gap-2 text-xs">
          <span className="w-28 flex-none truncate text-neutral-600">{family}</span>
          <div className="h-2 flex-1 rounded bg-neutral-100">
            <div className="h-2 rounded bg-violet-500" style={{ width: `${(count / max) * 100}%` }} />
          </div>
          <span className="w-6 flex-none text-right text-neutral-500">{count}</span>
        </div>
      ))}
    </div>
  )
}

function SolutionRow({ solution }: { solution: Solution }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="rounded border border-neutral-200">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-neutral-50"
      >
        <span className="font-medium text-neutral-800">{solution.name}</span>
        <span className="flex items-center gap-2 text-xs text-neutral-400">
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
          <ul className="space-y-1">
            {solution.projects.map((member) => (
              <li key={member.raw_path} className="flex items-center justify-between text-xs">
                <span className="font-mono text-neutral-700">{member.relative_path ?? member.raw_path}</span>
                {member.resolution_status === 'unresolved' ? (
                  <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-700">missing</span>
                ) : (
                  <span className="text-neutral-400">resolved</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function ArtifactCounts({ artifacts }: { artifacts: RepositoryArtifact[] }) {
  const [expanded, setExpanded] = useState(false)
  const byCategory = artifacts.reduce<Record<string, RepositoryArtifact[]>>((acc, artifact) => {
    ;(acc[artifact.category] ??= []).push(artifact)
    return acc
  }, {})
  const categories = Object.entries(byCategory).sort((a, b) => b[1].length - a[1].length)

  if (categories.length === 0) return <p className="text-sm text-neutral-400">No supporting artifacts found.</p>

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {categories.map(([category, items]) => (
          <span key={category} className="rounded border border-neutral-200 bg-neutral-50 px-2 py-1 text-xs text-neutral-600">
            {category} · {items.length}
          </span>
        ))}
      </div>
      <button type="button" onClick={() => setExpanded((v) => !v)} className="mt-2 text-xs text-violet-600 hover:underline">
        {expanded ? 'Hide paths' : 'Show paths'}
      </button>
      {expanded && (
        <ul className="mt-2 max-h-40 space-y-0.5 overflow-y-auto font-mono text-xs text-neutral-500">
          {artifacts.map((artifact) => (
            <li key={artifact.relative_path}>{artifact.relative_path}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function RepositoryStructureSection({ repositoryId, refreshToken }: RepositoryStructureSectionProps) {
  const [structure, setStructure] = useState<RepositoryStructure | null>(null)
  const [solutions, setSolutions] = useState<Solution[]>([])
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [artifacts, setArtifacts] = useState<RepositoryArtifact[]>([])
  const [notScanned, setNotScanned] = useState(false)
  const [loading, setLoading] = useState(true)
  const [warningsExpanded, setWarningsExpanded] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setNotScanned(false)

    getRepositoryStructure(repositoryId)
      .then(async (result) => {
        if (cancelled) return
        setStructure(result)
        const [solutionResult, projectResult, artifactResult] = await Promise.all([
          listRepositorySolutions(repositoryId),
          listRepositoryProjects(repositoryId),
          listRepositoryArtifacts(repositoryId),
        ])
        if (cancelled) return
        setSolutions(solutionResult)
        setProjects(projectResult)
        setArtifacts(artifactResult)
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

  const standaloneProjects = projects.filter((p) => p.is_standalone)

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
        {solutions.length === 0 ? (
          <p className="text-sm text-neutral-400">No .sln files found.</p>
        ) : (
          <div className="space-y-1.5">
            {solutions.map((solution) => (
              <SolutionRow key={solution.id} solution={solution} />
            ))}
          </div>
        )}
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-400">
          Standalone projects ({standaloneProjects.length})
        </h4>
        {standaloneProjects.length === 0 ? (
          <p className="text-sm text-neutral-400">Every project belongs to at least one solution.</p>
        ) : (
          <ul className="space-y-0.5 font-mono text-xs text-neutral-600">
            {standaloneProjects.map((project) => (
              <li key={project.id}>{project.relative_path}</li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-neutral-400">Supporting artifacts</h4>
        <ArtifactCounts artifacts={artifacts} />
      </div>

      {structure.parse_warnings.length > 0 && (
        <div>
          <button
            type="button"
            onClick={() => setWarningsExpanded((v) => !v)}
            className="text-xs font-semibold uppercase tracking-wide text-amber-600 hover:underline"
          >
            Discovery warnings ({structure.parse_warnings.length}) {warningsExpanded ? '▲' : '▼'}
          </button>
          {warningsExpanded && (
            <ul className="mt-2 space-y-1 text-xs text-neutral-600">
              {structure.parse_warnings.map((warning, index) => (
                <li key={index}>
                  <span className="font-mono text-neutral-400">{warning.path}</span> — {warning.warning}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
