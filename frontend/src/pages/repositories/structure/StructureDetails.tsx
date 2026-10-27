import { useEffect, useState } from 'react'
import { getHierarchyNode } from '../../../api/hierarchy'
import { dependencyUses, getDependencyProject } from '../../../api/results'
import { PagedList } from '../../../components/PagedList'
import type { HierarchyNodeDetail, HierarchyView } from '../../../types/hierarchy'
import { SourceLink } from '../SourceLink'
import { NodeBadges } from './NodeBadges'
import { EDGE_STYLES, LOOKS, lookOf } from './nodeStyle'

interface DetailsProps {
  repositoryId: string
  localPath: string | null
  nodeId: string
  view: HierarchyView
  /** The stored dependency-assessment (backend app.results), whose word on the node is read when it is shown: a
   * project's status and reason, or each declared package's outcome and reason. Null when it has not run. */
  assessmentId: string | null
  onSelect: (nodeId: string) => void
  onClose: () => void
}

type Rec = Record<string, unknown>
const rec = (v: unknown): Rec => (v && typeof v === 'object' ? (v as Rec) : {})
const str = (v: unknown): string | null => (typeof v === 'string' ? v : null)

/** A node's details: its path with the editor link, framework, origin, parents, work items, and its
 * dependency-assessment status with the reason. */
export function StructureDetails({ repositoryId, localPath, nodeId, view, assessmentId, onSelect, onClose }: DetailsProps) {
  const [detail, setDetail] = useState<HierarchyNodeDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    setDetail(null)
    setError(null)
    getHierarchyNode(repositoryId, nodeId, view)
      .then((d) => live && setDetail(d))
      .catch((err) => live && setError(err instanceof Error ? err.message : 'The node could not be loaded.'))
    return () => {
      live = false
    }
  }, [repositoryId, nodeId, view])

  return (
    <aside className="min-w-0 space-y-3 rounded border border-neutral-200 bg-white p-3 text-xs" aria-label="Node details">
      <div className="flex items-start justify-between gap-2">
        <h4 className="min-w-0 break-words text-sm font-semibold text-neutral-900">{detail?.node.name ?? nodeId}</h4>
        <button type="button" onClick={onClose} aria-label="Close details" className="rounded px-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-700">
          ✕
        </button>
      </div>
      {error && <p className="text-red-600">{error}</p>}
      {!detail && !error && <p className="text-neutral-400">Loading…</p>}
      {detail && <Body detail={detail} localPath={localPath} assessmentId={assessmentId} onSelect={onSelect} />}
    </aside>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="mt-0.5 text-neutral-800">{children}</div>
    </div>
  )
}

function Body({ detail, localPath, assessmentId, onSelect }: { detail: HierarchyNodeDetail; localPath: string | null; assessmentId: string | null; onSelect: (id: string) => void }) {
  const { node } = detail
  const d = rec(detail.detail)
  const project = rec(d.project)
  const pkg = rec(d.package)
  const assembly = rec(d.assembly)
  const look = LOOKS[lookOf(node)]
  const declaredBy = detail.parents.filter((p) => p.edge.declared_file)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`rounded px-1.5 text-[10px] font-semibold ${look.tag}`}>{look.label}</span>
        <NodeBadges node={node} />
      </div>
      {node.status === 'not_checked' && <p className="rounded bg-neutral-100 px-2 py-1 text-neutral-700">Not checked: {node.not_checked_reason}</p>}

      {node.type === 'project' && (
        <>
          <Field label="Path">
            <SourceLink localPath={localPath} filePath={str(project.path) ?? ''} line={1} className="break-all font-mono text-violet-700">
              {str(project.path)}
            </SourceLink>
          </Field>
          <Field label="Target framework">{node.target_frameworks.join(', ') || '—'}</Field>
          <Field label="Project">
            {str(project.projectFormat) === 'legacy_msbuild' ? 'Legacy (non-SDK-style)' : str(project.projectFormat) === 'sdk_style' ? 'SDK-style' : 'Unknown format'}
            {' · '}packages: {str(project.packageManagement)}
            <div className="text-neutral-500">{look.label}: {str(project.kindBasis)}</div>
          </Field>
        </>
      )}

      {node.type === 'package' && (
        <>
          <Field label="Version">{node.version ?? 'unknown'}</Field>
          <Field label="Origin">
            {node.origin}: {str(pkg.originBasis)}
            {str(pkg.feedName) && <div className="text-neutral-500">feed {str(pkg.feedName)}</div>}
            {pkg.producer != null && (
              <div className="text-neutral-500">
                produced by repository {str(rec(pkg.producer).repositoryName)} ({str(rec(pkg.producer).projectPath)})
              </div>
            )}
          </Field>
          <Field label="Its dependencies">
            {str(pkg.dependenciesNotCheckedReason) ?? (str(pkg.dependenciesResolution) === 'assets_file'
              ? 'from the project’s restored assets file: what restore chose'
              : str(pkg.dependenciesResolution) === 'feed_metadata'
                ? 'from the feed’s metadata for the project’s framework: the lowest version each range allows'
                : '—')}
          </Field>
        </>
      )}

      {node.type === 'assembly' && (
        <Field label="Location">
          {str(assembly.location)}
          {str(assembly.path) && (
            <div>
              {str(assembly.location) === 'repository' ? (
                <SourceLink localPath={localPath} filePath={str(assembly.path)!} line={1} className="break-all font-mono text-violet-700">
                  {str(assembly.path)}
                </SourceLink>
              ) : (
                <span className="break-all font-mono">{str(assembly.path)}</span>
              )}
            </div>
          )}
        </Field>
      )}

      {declaredBy.length > 0 && (
        <Field label="Declared in">
          <ul className="space-y-0.5">
            {declaredBy.map((p) => (
              <li key={`${p.edge.from_node}|${p.edge.kind}`}>
                <SourceLink localPath={localPath} filePath={p.edge.declared_file!} line={p.edge.declared_line ?? 1} className="break-all font-mono text-violet-700">
                  {p.edge.declared_file}
                  {p.edge.declared_line ? `:${p.edge.declared_line}` : ''}
                </SourceLink>{' '}
                <span className="text-neutral-400">{EDGE_STYLES[p.edge.kind].label}{p.edge.version_requested ? ` ${p.edge.version_requested}` : ''}</span>
              </li>
            ))}
          </ul>
        </Field>
      )}

      <Field label={`Referenced by ${detail.parents_total}`}>
        {detail.parents.length === 0 ? (
          <span className="text-neutral-400">nothing in the repository: a root</span>
        ) : (
          <ul className="space-y-0.5">
            {detail.parents.map((p) => (
              <li key={`${p.edge.from_node}|${p.edge.kind}`}>
                <button type="button" onClick={() => onSelect(p.node.id)} className="text-left text-violet-700 hover:underline">
                  {p.node.name}
                </button>
              </li>
            ))}
            {detail.parents_total > detail.parents.length && <li className="text-neutral-400">and {detail.parents_total - detail.parents.length} more</li>}
          </ul>
        )}
      </Field>

      <Field label={`Work items (${detail.work_items.length})`}>
        {detail.work_items.length === 0 ? (
          <span className="text-neutral-400">none found</span>
        ) : (
          <ul className="space-y-0.5">
            {detail.work_items.map((w, i) => (
              <li key={i}>
                <span className="font-medium">{w.item_name}</span>
                {w.value && <span className="text-neutral-500"> — {w.value}</span>}
                {w.file_path && (
                  <>
                    {' '}
                    <SourceLink localPath={localPath} filePath={w.file_path} line={1} className="font-mono text-violet-700">
                      {w.file_path}
                    </SourceLink>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </Field>

      <Field label="Dependency assessment">
        <AssessmentStatus node={detail.node} projectPath={str(project.path)} packageId={str(pkg.packageId)} assessmentId={assessmentId} />
      </Field>
    </div>
  )
}

/** dependency-assessment's word on the node, from its stored result: a project's status with its reason, or a declared
 * package's outcome with its reason, per project that declares it. */
function AssessmentStatus({ node, projectPath, packageId, assessmentId }: { node: HierarchyNodeDetail['node']; projectPath: string | null; packageId: string | null; assessmentId: string | null }) {
  if (!assessmentId) return <span className="text-neutral-400">dependency-assessment has not run for this repository.</span>
  if (node.type === 'assembly') return <span className="text-neutral-500">Not assessed: dependency-assessment assesses NuGet packages, not assembly references.</span>
  if (node.type === 'project') return <ProjectAssessment assessmentId={assessmentId} projectPath={projectPath} />
  if (node.transitive) {
    return <span className="text-neutral-500">Not assessed: dependency-assessment assesses the packages a project declares, and only another package depends on this one.</span>
  }
  return <PackageAssessment assessmentId={assessmentId} packageId={packageId ?? ''} version={node.version ?? null} />
}

function ProjectAssessment({ assessmentId, projectPath }: { assessmentId: string; projectPath: string | null }) {
  const [p, setP] = useState<Rec | null | undefined>(undefined)
  useEffect(() => {
    let live = true
    setP(undefined)
    if (!projectPath) setP(null)
    else getDependencyProject(assessmentId, projectPath).then((r) => live && setP(r ? rec(r) : null), () => live && setP(null))
    return () => {
      live = false
    }
  }, [assessmentId, projectPath])
  if (p === undefined) return <span className="text-neutral-400">Loading…</span>
  if (!p) return <span className="text-neutral-500">Not assessed: the project is not in dependency-assessment’s artifact.</span>
  const counts = Object.entries(rec(rec(p.summary).countByOutcome)).map(([k, v]) => `${v} ${k.replace(/_/g, ' ')}`)
  return (
    <span>
      {str(p.status)?.toLowerCase()}
      {str(p.skipReason) ? `: ${str(p.skipReason)}` : ''}
      {counts.length > 0 && <span className="text-neutral-500"> · {counts.join(', ')}</span>}
    </span>
  )
}

interface PackageUse {
  project: string
  pkg: Rec
}

/** This version's rows; every version's when restore chose a version other than the declared one. */
function PackageAssessment({ assessmentId, packageId, version }: { assessmentId: string; packageId: string; version: string | null }) {
  const [exact, setExact] = useState<boolean | null>(null)
  useEffect(() => {
    let live = true
    setExact(null)
    if (!version) setExact(false)
    else dependencyUses(assessmentId, packageId, version)('', 0, 1).then((page) => live && setExact(page.total > 0), () => live && setExact(false))
    return () => {
      live = false
    }
  }, [assessmentId, packageId, version])
  if (exact === null) return <span className="text-neutral-400">Loading…</span>
  return (
    <PagedList<PackageUse>
      load={dependencyUses(assessmentId, packageId, exact ? version : null)}
      resetKey={`${assessmentId}|${packageId}|${exact ? version : '*'}`}
      noun="projects"
      empty={<span className="text-neutral-500">Not in dependency-assessment’s artifact.</span>}
    >
      {(rows) => (
        <ul className="space-y-1">
          {rows.map((r) => (
            <li key={`${r.project}|${str(r.pkg.currentVersion)}`}>
              <span className="font-medium">{str(r.pkg.outcome)?.replace(/_/g, ' ')}</span>
              {str(r.pkg.recommendedVersion) && <span className="text-neutral-500"> → {str(r.pkg.recommendedVersion)}</span>}
              {str(r.pkg.outcomeReason) && <div className="text-neutral-600">{str(r.pkg.outcomeReason)}</div>}
              <div className="font-mono text-[10px] text-neutral-400">{r.project}</div>
            </li>
          ))}
        </ul>
      )}
    </PagedList>
  )
}
