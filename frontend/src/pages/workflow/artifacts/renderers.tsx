import { Fragment, useEffect, useMemo, useState } from 'react'
import { listCatalogItems } from '../../../api/items'
import { InboundProjectPanel } from '../../repositories/RepositorySurfaceSection'
import { OutboundProjectPanel } from '../../repositories/RepositoryOutboundPanel'
import { SourceLink } from '../../repositories/SourceLink'
import { ShowMoreToggle } from '../../../components/ShowMoreToggle'
import { entryPointProjects, list, num, obj, outboundProjects, str, type Json } from './adapters'
import type { WorkListDecisions } from '../../../types/items'

export interface ArtifactRendererProps {
  data: Json
  /** The repository's path on this machine, for source links; null when unknown. */
  localPath: string | null
}

// ---------- shared bits ----------

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(1)} ${units[unit]}`
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">{label}</dt>
      <dd className="mt-0.5 break-words text-sm text-neutral-800">{children}</dd>
    </div>
  )
}

function Chip({ children, tone = 'neutral', title }: { children: React.ReactNode; tone?: 'neutral' | 'amber' | 'red' | 'teal'; title?: string }) {
  const style = {
    neutral: 'border-neutral-200 bg-neutral-50 text-neutral-600',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    red: 'border-red-200 bg-red-50 text-red-700',
    teal: 'border-teal-200 bg-teal-50 text-teal-700',
  }[tone]
  return (
    <span className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[11px] ${style}`} title={title}>
      {children}
    </span>
  )
}

function Table({ head, children, minWidth = 560 }: { head: string[]; children: React.ReactNode; minWidth?: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs" style={{ minWidth }}>
        <thead className="text-neutral-400">
          <tr className="border-b border-neutral-200">
            {head.map((h) => (
              <th key={h} className="py-1.5 pr-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  )
}

function StatusText({ status }: { status: string | null }) {
  const bad = status !== null && !['success', 'SUCCESS', 'COMPLETE', 'SCANNED', 'resolved'].includes(status)
  return <span className={bad ? 'font-medium text-amber-700' : 'text-neutral-500'}>{status ?? '—'}</span>
}

// ---------- repository-inventory (step 1) ----------

export function RepositoryInventoryView({ data }: ArtifactRendererProps) {
  const languages = list(data.primary_languages)
  const commit = str(data.ingest_commit_sha)
  const branch = str(data.current_branch) ?? str(data.default_branch)
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
      <Fact label="Path">
        <span className="font-mono text-xs">{str(data.local_path) ?? '—'}</span>
      </Fact>
      <Fact label="Commit">
        {commit ? <span className="font-mono text-xs">{commit.slice(0, 12)}</span> : <span className="text-neutral-400">no git history</span>}
      </Fact>
      <Fact label="Branch">{branch ?? <span className="text-neutral-400">—</span>}</Fact>
      <Fact label="Size">{formatBytes(typeof data.size_bytes === 'number' ? data.size_bytes : null)}</Fact>
      <Fact label="Files">{num(data.file_count).toLocaleString()}</Fact>
      <Fact label="Source control">{str(data.source_control_status) ?? '—'}</Fact>
      <div className="sm:col-span-2 lg:col-span-3">
        <dt className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">Primary languages</dt>
        <dd className="mt-1 space-y-1">
          {languages.length === 0 && <span className="text-sm text-neutral-400">—</span>}
          {languages.map((l) => (
            <div key={str(l.language) ?? ''} className="flex items-center gap-2 text-xs">
              <span className="w-24 flex-none truncate text-neutral-700">{str(l.language)}</span>
              <span className="h-2 flex-1 rounded bg-neutral-100">
                <span className="block h-2 rounded bg-violet-400" style={{ width: `${Math.max(2, num(l.percentage))}%` }} />
              </span>
              <span className="w-28 flex-none text-right text-neutral-500">
                {num(l.percentage)}% · {num(l.file_count)} files
              </span>
            </div>
          ))}
        </dd>
      </div>
    </dl>
  )
}

// ---------- solution-project-inventory (step 2) ----------

/** What the project builds into, from its OutputType. Not step 6's role
 * (application, library, test...), which is decided later from entry points. */
function outputKind(project: Json): string {
  const structural = str(project.structural_type)
  if (structural && !['csharp_project', 'vb_project', 'fsharp_project'].includes(structural)) return structural.replace(/_/g, ' ')
  const output = (str(project.output_type) ?? '').toLowerCase()
  if (output === 'exe') return 'executable'
  if (output === 'winexe') return 'windows executable'
  if (output === 'library') return 'library'
  return 'library (default)'
}

export function SolutionInventoryView({ data }: ArtifactRendererProps) {
  const solutions = list(data.solutions)
  const projects = list(data.projects)
  const summary = obj(data.summary)
  const families = obj(summary.framework_families) as Record<string, number>
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        <Chip>{num(summary.solution_count)} solution(s)</Chip>
        <Chip>{num(summary.project_file_count)} project(s)</Chip>
        {Object.entries(families).map(([family, count]) => (
          <Chip key={family}>
            {family} × {count}
          </Chip>
        ))}
        {num(summary.failed_parse_count) > 0 && <Chip tone="amber">{num(summary.failed_parse_count)} failed to parse</Chip>}
        {num(summary.unresolved_reference_count) > 0 && <Chip tone="amber">{num(summary.unresolved_reference_count)} unresolved reference(s)</Chip>}
      </div>

      <div>
        <h5 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">Solutions</h5>
        {solutions.length === 0 ? (
          <p className="text-xs text-neutral-400">No solution files.</p>
        ) : (
          <Table head={['Solution', 'Visual Studio', 'Projects', 'Folders', 'Parse status']}>
            {solutions.map((s) => (
              <tr key={str(s.relative_path) ?? ''} className="border-b border-neutral-100 align-top last:border-0">
                <td className="py-1.5 pr-3">
                  <span className="font-medium text-neutral-800">{str(s.name)}</span>
                  <span className="block font-mono text-[11px] text-neutral-400">{str(s.relative_path)}</span>
                </td>
                <td className="py-1.5 pr-3 text-neutral-500">{str(s.visual_studio_version) ?? str(s.format_version) ?? '—'}</td>
                <td className="py-1.5 pr-3 text-neutral-700">
                  {num(s.resolved_project_count)}/{num(s.project_count)}
                  {num(s.missing_project_count) > 0 && <span className="ml-1 text-amber-700">({num(s.missing_project_count)} missing)</span>}
                </td>
                <td className="py-1.5 pr-3 text-neutral-500">{num(s.solution_folder_count)}</td>
                <td className="py-1.5 pr-3">
                  <StatusText status={str(s.parse_status)} />
                </td>
              </tr>
            ))}
          </Table>
        )}
      </div>

      <div>
        <h5 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-neutral-400">Projects</h5>
        <Table head={['Project', 'Framework', 'Format', 'Builds as', 'Parse status']} minWidth={640}>
          {projects.map((p) => (
            <tr key={str(p.relative_path) ?? ''} className="border-b border-neutral-100 align-top last:border-0">
              <td className="py-1.5 pr-3">
                <span className="font-medium text-neutral-800">{str(p.name)}</span>
                <span className="block break-all font-mono text-[11px] text-neutral-400">{str(p.relative_path)}</span>
              </td>
              <td className="py-1.5 pr-3 text-neutral-700">
                {str(p.framework_family) ?? '—'} {str(p.framework_version) ?? ''}
                <span className="block font-mono text-[11px] text-neutral-400">
                  {list<string>(p.target_frameworks_raw).join(';') || str(p.target_framework_raw) || ''}
                </span>
              </td>
              <td className="py-1.5 pr-3 text-neutral-500">{(str(p.project_format) ?? '—').replace(/_/g, '-')}</td>
              <td className="py-1.5 pr-3 text-neutral-500" title="From the project's OutputType. Step 6 assigns the application role.">
                {outputKind(p)}
              </td>
              <td className="py-1.5 pr-3">
                <StatusText status={str(p.parse_status)} />
                {list(p.parse_warnings).length > 0 && <span className="ml-1 text-amber-700">· {list(p.parse_warnings).length} warning(s)</span>}
              </td>
            </tr>
          ))}
        </Table>
      </div>
    </div>
  )
}

// ---------- application-fingerprint (step 3) ----------

interface SignalRow {
  name: string
  value: string | null
  project: string
  sourcePath: string | null
  occurrences: number
  confidence: number
}

export function FingerprintView({ data }: ArtifactRendererProps) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const summary = obj(data.summary)

  const byCategory = useMemo(() => {
    const groups = new Map<string, SignalRow[]>()
    const add = (signal: Json, project: string) => {
      const category = str(signal.category) ?? 'UNCATEGORISED'
      const rows = groups.get(category) ?? []
      rows.push({
        name: str(signal.name) ?? '',
        value: str(signal.value),
        project,
        sourcePath: str(signal.sourcePath),
        occurrences: num(signal.occurrenceCount, 1),
        confidence: num(signal.extractionConfidence, 1),
      })
      groups.set(category, rows)
    }
    for (const project of list(data.projects)) {
      for (const signal of list(project.signals)) add(signal, str(project.projectPath) ?? '')
    }
    for (const signal of list(data.repositorySignals)) add(signal, '(repository)')
    return [...groups.entries()]
      .map(([category, rows]) => [category, rows.sort((a, b) => a.name.localeCompare(b.name) || a.project.localeCompare(b.project))] as const)
      .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
  }, [data])

  const projects = list(data.projects)
  const statusCounts = projects.reduce<Record<string, number>>((acc, p) => {
    const status = str(p.fingerprintStatus) ?? 'UNKNOWN'
    acc[status] = (acc[status] ?? 0) + 1
    return acc
  }, {})

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <Chip>{num(summary.totalSignals)} signals</Chip>
        <Chip>{num(summary.totalEvidence)} evidence</Chip>
        {Object.entries(statusCounts).map(([status, count]) => (
          <Chip key={status} tone={status === 'FAILED' ? 'red' : 'neutral'} title="Projects by fingerprint status">
            {count} {status.toLowerCase()}
          </Chip>
        ))}
        {str(data.signalRegistryVersion) && <Chip>registry {str(data.signalRegistryVersion)}</Chip>}
      </div>
      {byCategory.length === 0 ? (
        <p className="text-xs text-neutral-400">No signals.</p>
      ) : (
        <ul className="divide-y divide-neutral-100 rounded border border-neutral-200">
          {byCategory.map(([category, rows]) => (
            <li key={category}>
              <button
                type="button"
                onClick={() => setOpen((o) => ({ ...o, [category]: !o[category] }))}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-neutral-50"
              >
                <span className="text-neutral-400">{open[category] ? '▾' : '▸'}</span>
                <span className="font-medium text-neutral-800">{category.replace(/_/g, ' ').toLowerCase()}</span>
                <span className="text-neutral-400">
                  {rows.length} signal{rows.length === 1 ? '' : 's'} · {new Set(rows.map((r) => r.name)).size} distinct
                </span>
              </button>
              {open[category] && (
                <div className="px-3 pb-2">
                  <Table head={['Signal', 'Value', 'Project', 'Occurrences']} minWidth={520}>
                    {rows.map((r, i) => (
                      <tr key={`${r.name}|${r.project}|${r.value}|${i}`} className="border-b border-neutral-100 align-top last:border-0">
                        <td className="py-1 pr-3 font-mono text-[11px] text-neutral-800">{r.name}</td>
                        <td className="max-w-[16rem] break-all py-1 pr-3 font-mono text-[11px] text-neutral-500">{r.value ?? '—'}</td>
                        <td className="break-all py-1 pr-3 font-mono text-[11px] text-neutral-500" title={r.sourcePath ?? undefined}>
                          {r.project.split('/').pop()}
                        </td>
                        <td className="py-1 pr-3 text-neutral-600">
                          {r.occurrences}
                          {r.confidence < 1 && <span className="ml-1 text-neutral-400">({r.confidence.toFixed(2)})</span>}
                        </td>
                      </tr>
                    ))}
                  </Table>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------- entry-point-inventory (step 4) ----------

export function EntryPointsView({ data, localPath }: ArtifactRendererProps) {
  const projects = useMemo(() => entryPointProjects(data), [data])
  const summary = obj(data.summary)
  const withEntries = projects.filter((p) => p.entry_points.length > 0)
  const empty = projects.length - withEntries.length
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <Chip>{num(summary.requestEntryPointCount)} request entry points</Chip>
        <Chip>{num(summary.lifecycleHookCount)} lifecycle hooks</Chip>
        {num(summary.noDeclaredAuthenticationCount) > 0 && <Chip tone="amber">{num(summary.noDeclaredAuthenticationCount)} no declared authentication</Chip>}
        {empty > 0 && <Chip>{empty} project(s) with none</Chip>}
      </div>
      {withEntries.length === 0 ? (
        <p className="text-xs text-neutral-400">No entry points found.</p>
      ) : (
        withEntries.map((project) => <InboundProjectPanel key={project.project_id} project={project} localPath={localPath} />)
      )}
    </div>
  )
}

// ---------- outbound-invocation-inventory (step 5) ----------

const VERDICT_RANK: Record<string, number> = { incompatible: 0, requires_change: 1, unknown: 2, compatible: 3 }

export function OutboundView({ data, localPath }: ArtifactRendererProps) {
  const projects = useMemo(
    () =>
      outboundProjects(data)
        .filter((p) => p.invocations.length > 0)
        .sort(
          (a, b) =>
            Math.min(...a.invocations.map((i) => (i.usage === 'unused' ? 9 : VERDICT_RANK[i.linux_verdict]))) -
              Math.min(...b.invocations.map((i) => (i.usage === 'unused' ? 9 : VERDICT_RANK[i.linux_verdict]))) ||
            a.project_path.localeCompare(b.project_path),
        ),
    [data],
  )
  const summary = obj(data.summary)
  const verdicts = obj(summary.countByVerdict) as Record<string, number>
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-1.5">
        <Chip>{num(summary.invocationCount) - num(summary.unusedCount)} invocations</Chip>
        {(verdicts.incompatible ?? 0) > 0 && <Chip tone="red">{verdicts.incompatible} incompatible</Chip>}
        {(verdicts.requires_change ?? 0) > 0 && <Chip tone="amber">{verdicts.requires_change} requires change</Chip>}
        {(verdicts.unknown ?? 0) > 0 && <Chip>{verdicts.unknown} unknown</Chip>}
        {(verdicts.compatible ?? 0) > 0 && <Chip tone="teal">{verdicts.compatible} compatible</Chip>}
        {num(summary.unusedCount) > 0 && <Chip>{num(summary.unusedCount)} unused (not counted)</Chip>}
      </div>
      {projects.length === 0 ? (
        <p className="text-xs text-neutral-400">No outbound invocations found.</p>
      ) : (
        projects.map((project) => <OutboundProjectPanel key={project.project_id} project={project} localPath={localPath} />)
      )}
    </div>
  )
}

// ---------- dependency-assessment (step 6) ----------

const OUTCOME_STYLE: Record<string, string> = {
  no_compatible_version: 'border-red-200 bg-red-50 text-red-700',
  upgrade_breaking: 'border-amber-200 bg-amber-50 text-amber-800',
  unknown: 'border-neutral-300 bg-neutral-100 text-neutral-600',
  upgrade_safe: 'border-teal-200 bg-teal-50 text-teal-700',
  current: 'border-neutral-200 bg-white text-neutral-400',
}
const OUTCOME_LABEL: Record<string, string> = {
  no_compatible_version: 'no compatible version',
  upgrade_breaking: 'upgrade breaking',
  unknown: 'unknown',
  upgrade_safe: 'upgrade safe',
  current: 'current',
}
const OUTCOME_ORDER = ['no_compatible_version', 'upgrade_breaking', 'unknown', 'upgrade_safe', 'current']

interface ProjectUse {
  project: string
  pkg: Json
}

/** One package at one version: every project that references it there. */
interface VersionGroup {
  version: string
  uses: ProjectUse[]
}

/** One package id; more than one version group is version drift. */
interface PackageGroup {
  packageId: string
  versions: VersionGroup[]
  drift: boolean
}

/** Part G: what blocks first — no compatible version, then vulnerable, then
 * breaking, unknown, safe and current. */
function packageRank(pkg: Json): number {
  const outcome = str(pkg.outcome) ?? ''
  if (outcome === 'no_compatible_version') return 0
  if (pkg.vulnerable) return 1
  return 2 + Math.max(0, OUTCOME_ORDER.indexOf(outcome))
}

const groupRank = (uses: ProjectUse[]) => Math.min(...uses.map((u) => packageRank(u.pkg)))
const worst = (uses: ProjectUse[]) => uses.slice().sort((a, b) => packageRank(a.pkg) - packageRank(b.pkg))[0].pkg

/** The project file, prefixed by its top-level folder: two solutions in one
 * repository often hold projects with the same file name. */
function shortProjectPath(path: string): string {
  const parts = path.split('/')
  return parts.length > 2 ? `${parts[0]}/…/${parts[parts.length - 1]}` : path
}

/** A breaking package whose call sites are all ambiguous is "possibly breaking". */
const possiblyOnly = (pkg: Json) => str(pkg.breakingEvidence) === 'ambiguous_call_sites_only'

function OutcomeBadge({ pkg }: { pkg: Json }) {
  const outcome = str(pkg.outcome) ?? ''
  const label = outcome === 'upgrade_breaking' && possiblyOnly(pkg) ? 'possibly breaking' : (OUTCOME_LABEL[outcome] ?? outcome)
  return (
    <span
      className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-semibold ${OUTCOME_STYLE[outcome] ?? OUTCOME_STYLE.unknown} ${possiblyOnly(pkg) ? 'border-dashed' : ''}`}
      title={str(pkg.outcomeReason) ?? undefined}
    >
      {label}
    </span>
  )
}

export function DependenciesView({ data, localPath }: ArtifactRendererProps) {
  const [showCurrent, setShowCurrent] = useState(false)
  const [open, setOpen] = useState<Record<string, boolean>>({})

  const groups = useMemo(() => {
    const byId = new Map<string, Map<string, ProjectUse[]>>()
    for (const project of list(data.projects)) {
      const projectPath = str(project.projectPath) ?? ''
      for (const pkg of list(project.packages)) {
        const id = str(pkg.packageId) ?? ''
        const key = id.toLowerCase()
        const version = str(pkg.currentVersion) ?? '—'
        if (!byId.has(key)) byId.set(key, new Map())
        const versions = byId.get(key)!
        if (!versions.has(version)) versions.set(version, [])
        versions.get(version)!.push({ project: projectPath, pkg })
      }
    }
    const result: PackageGroup[] = []
    for (const versions of byId.values()) {
      const versionGroups = [...versions.entries()]
        .map(([version, uses]) => ({ version, uses: uses.sort((a, b) => a.project.localeCompare(b.project)) }))
        .sort((a, b) => a.version.localeCompare(b.version, undefined, { numeric: true }))
      result.push({
        packageId: str(versionGroups[0].uses[0].pkg.packageId) ?? '',
        versions: versionGroups,
        drift: versionGroups.length > 1,
      })
    }
    return result.sort(
      (a, b) =>
        Math.min(...a.versions.map((v) => groupRank(v.uses))) - Math.min(...b.versions.map((v) => groupRank(v.uses))) ||
        a.packageId.localeCompare(b.packageId, undefined, { sensitivity: 'base' }),
    )
  }, [data])

  // The feeds NuGet resolved, deduplicated across projects — so it is always
  // visible whether answers came from a client feed or the nuget.org fallback.
  const feeds = useMemo(() => {
    const seen = new Map<string, Json>()
    for (const project of list(data.projects)) {
      for (const feed of list(project.feeds)) seen.set(`${str(feed.url)}|${str(feed.role)}`, feed)
    }
    return [...seen.values()].sort((a, b) => (str(a.role) ?? '').localeCompare(str(b.role) ?? ''))
  }, [data])

  const summary = obj(data.summary)
  const outcomes = obj(summary.countByOutcome) as Record<string, number>
  const sources = obj(summary.countByFeedSource) as Record<string, number>
  const allCurrent = (g: PackageGroup) => g.versions.every((v) => v.uses.every((u) => str(u.pkg.outcome) === 'current'))
  // A drifting package is a finding even when every copy is current.
  const visible = showCurrent ? groups : groups.filter((g) => g.drift || !allCurrent(g))
  const toggle = (key: string) => setOpen((o) => ({ ...o, [key]: !o[key] }))

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip>{num(summary.packageCount)} package references</Chip>
        {(outcomes.no_compatible_version ?? 0) > 0 && <Chip tone="red">{outcomes.no_compatible_version} no compatible version</Chip>}
        {(outcomes.upgrade_breaking ?? 0) > 0 && <Chip tone="amber">{outcomes.upgrade_breaking} breaking</Chip>}
        {(outcomes.unknown ?? 0) > 0 && <Chip>{outcomes.unknown} unknown</Chip>}
        {(outcomes.upgrade_safe ?? 0) > 0 && <Chip tone="teal">{outcomes.upgrade_safe} safe</Chip>}
        {(outcomes.current ?? 0) > 0 && <Chip>{outcomes.current} current</Chip>}
        <span className="mx-1 text-neutral-300">|</span>
        {num(summary.vulnerableCount) > 0 && <Chip tone="red">{num(summary.vulnerableCount)} vulnerable</Chip>}
        {num(summary.deprecatedCount) > 0 && <Chip tone="amber">{num(summary.deprecatedCount)} deprecated</Chip>}
        {num(summary.notInClientFeedCount) > 0 && <Chip tone="amber">{num(summary.notInClientFeedCount)} not in client feed</Chip>}
        {num(summary.versionDriftCount) > 0 && (
          <Chip tone="amber" title="Packages referenced at more than one version across projects: consolidate before upgrading">
            {num(summary.versionDriftCount)} version drift
          </Chip>
        )}
        {num(summary.contentBreakingPossibleCount) > 0 && (
          <Chip title="Content packages (scripts, CSS) moving a major version: markup or CSS may break, which this step cannot see">
            {num(summary.contentBreakingPossibleCount)} content breaking possible
          </Chip>
        )}
        <label className="ml-auto flex items-center gap-1.5 text-[11px] text-neutral-500">
          <input type="checkbox" checked={showCurrent} onChange={(e) => setShowCurrent(e.target.checked)} />
          Show current packages
        </label>
      </div>
      <p className="text-[11px] text-neutral-500">
        Target <span className="font-mono">{str(data.targetFramework)}</span> · answered by{' '}
        {(sources.client_feed ?? 0) > 0 && <span className="font-medium text-teal-700">client feed ×{sources.client_feed} </span>}
        {(sources.nuget_org_fallback ?? 0) > 0 && <span className="font-medium text-neutral-700">nuget.org fallback ×{sources.nuget_org_fallback} </span>}
        {(sources.none ?? 0) > 0 && <span className="text-neutral-500">no feed ×{sources.none}</span>}
        {feeds.length > 0 && (
          <span className="block text-neutral-400">
            Feeds:{' '}
            {feeds.map((f, i) => (
              <span key={i} title={`${str(f.url)} — declared in ${str(f.declaredIn)}`}>
                {i > 0 && ' · '}
                {str(f.name)} <span className="text-neutral-300">({str(f.role)?.replace(/_/g, ' ')})</span>
              </span>
            ))}
          </span>
        )}
      </p>
      {visible.length === 0 ? (
        <p className="text-xs text-neutral-400">No packages to show.</p>
      ) : (
        <Table head={['Package', 'Projects', 'Current', 'Recommended', 'Outcome', 'Flags', 'Feed']} minWidth={900}>
          {visible.map((group) => (
            <Fragment key={group.packageId}>
              {group.drift && (
                <tr className="border-b border-neutral-100 bg-amber-50/40 align-top">
                  <td className="py-1.5 pr-3 font-medium text-neutral-800">{group.packageId}</td>
                  <td colSpan={6} className="py-1.5 pr-3">
                    <Chip tone="amber" title="One package at different versions across projects. Consolidating first is usually the sensible order before upgrading.">
                      version drift: {group.versions.length} versions across {new Set(group.versions.flatMap((v) => v.uses.map((u) => u.project))).size} projects
                    </Chip>
                  </td>
                </tr>
              )}
              {group.versions.map((version) => {
                const key = `${group.packageId}|${version.version}`
                return (
                  <VersionRowView
                    key={key}
                    group={group}
                    version={version}
                    localPath={localPath}
                    expanded={!!open[key]}
                    onToggle={() => toggle(key)}
                  />
                )
              })}
            </Fragment>
          ))}
        </Table>
      )}
    </div>
  )
}

/** How many projects a row lists before "+N more". */
const PROJECTS_SHOWN = 3

function VersionRowView({
  group,
  version,
  localPath,
  expanded,
  onToggle,
}: {
  group: PackageGroup
  version: VersionGroup
  localPath: string | null
  expanded: boolean
  onToggle: () => void
}) {
  const [allProjects, setAllProjects] = useState(false)
  const pkg = worst(version.uses)
  const outcomes = new Set(version.uses.map((u) => str(u.pkg.outcome)))
  const deprecated = pkg.deprecated ? obj(pkg.deprecated) : null
  const vulnerable = pkg.vulnerable ? obj(pkg.vulnerable) : null
  const gap = pkg.notInClientFeed ? obj(pkg.notInClientFeed) : null
  const recommended = str(pkg.recommendedVersion)
  const latest = str(pkg.latestVersion)
  const kind = str(pkg.packageKind)
  const first = version.uses[0]
  const declaredAt = obj(first.pkg.declaredAt)

  return (
    <Fragment>
      <tr className="border-b border-neutral-100 align-top last:border-0">
        <td className={`py-1.5 pr-3 ${group.drift ? 'pl-4' : ''}`}>
          <button type="button" onClick={onToggle} className="mr-1 text-neutral-400 hover:text-violet-700" aria-expanded={expanded} title="Show details">
            {expanded ? '▾' : '▸'}
          </button>
          {group.drift ? (
            <span className="font-mono text-neutral-500">{version.version}</span>
          ) : (
            <SourceLink localPath={localPath} filePath={str(declaredAt.filePath) ?? ''} line={num(declaredAt.line, 1)} className="font-medium text-neutral-800">
              {group.packageId}
            </SourceLink>
          )}
          {kind && kind !== 'runtime' && <span className="ml-1.5 text-[10px] uppercase tracking-wide text-neutral-400">{kind}</span>}
        </td>
        <td className="py-1.5 pr-3 font-mono text-[11px] text-neutral-600">
          {(allProjects ? version.uses : version.uses.slice(0, PROJECTS_SHOWN)).map((u) => (
            <span key={u.project} className="block max-w-[15rem] truncate" title={u.project}>
              {shortProjectPath(u.project)}
            </span>
          ))}
          <ShowMoreToggle
            expanded={allProjects}
            hidden={version.uses.length - PROJECTS_SHOWN}
            onToggle={() => setAllProjects((v) => !v)}
            className="block"
          />
        </td>
        <td className="py-1.5 pr-3 font-mono text-neutral-700">{version.version}</td>
        <td className="py-1.5 pr-3 font-mono">
          {gap ? (
            <span className="text-amber-800" title={`Newest compatible on nuget.org vs newest in ${str(gap.clientFeedName)}`}>
              client {str(gap.latestInClientFeed) ?? 'none'} · public {str(gap.latestPublicVersion)}
            </span>
          ) : (
            <span className="text-neutral-800">{recommended ?? '—'}</span>
          )}
          {latest && latest !== recommended && !gap && (
            <span className="block text-[11px] text-neutral-400" title="The newest version on the feed, which does not support the target framework">
              latest {latest}
            </span>
          )}
        </td>
        <td className="py-1.5 pr-3">
          <OutcomeBadge pkg={pkg} />
          {outcomes.size > 1 && <span className="block text-[11px] text-amber-700">varies by project</span>}
          {str(pkg.classificationMethod) && (
            <span className="block text-[11px] text-neutral-400">
              {{ api_diff: 'API diff', semver_heuristic: 'semver heuristic', package_kind: 'by package kind' }[str(pkg.classificationMethod) ?? ''] ??
                str(pkg.classificationMethod)}
            </span>
          )}
          {str(pkg.outcome) === 'unknown' && <span className="block max-w-[16rem] text-[11px] text-neutral-500">{str(pkg.outcomeReason)}</span>}
        </td>
        <td className="py-1.5 pr-3">
          <div className="flex flex-wrap gap-1">
            {vulnerable && (
              <Chip
                tone="red"
                title={`${list(vulnerable.advisories).length} advisory(ies)${vulnerable.resolvedByUpgrade === true ? '; the recommended version resolves them' : vulnerable.resolvedByUpgrade === false ? '; the recommended version does not resolve them' : ''}`}
              >
                vulnerable: {str(vulnerable.maxSeverity)}
              </Chip>
            )}
            {deprecated && (
              <Chip tone="amber" title={str(deprecated.message) ?? list<string>(deprecated.reasons).join(', ')}>
                deprecated{str(deprecated.replacementId) ? ` → ${str(deprecated.replacementId)}` : ''}
              </Chip>
            )}
            {gap && <Chip tone="amber">not in client feed</Chip>}
            {pkg.contentBreakingPossible === true && (
              <Chip title="Content package moving a major version: markup or CSS may break. Not analysed by this step, and not counted as breaking.">
                content breaking possible
              </Chip>
            )}
          </div>
        </td>
        <td className="py-1.5 pr-3 text-[11px]">
          {str(pkg.feedSource) ? (
            <>
              <span className={str(pkg.feedSource) === 'client_feed' ? 'font-medium text-teal-700' : 'text-neutral-600'}>
                {str(pkg.feedSource) === 'client_feed' ? 'client feed' : 'nuget.org fallback'}
              </span>
              <span className="block text-neutral-400" title={str(pkg.feedUrl) ?? undefined}>
                {str(pkg.feedName)}
              </span>
            </>
          ) : (
            <span className="text-neutral-300">no feed answered</span>
          )}
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-neutral-100 bg-neutral-50/60">
          <td colSpan={7} className="space-y-2 px-6 py-2">
            {version.uses.map((use) => (
              <ProjectUseDetail key={use.project} use={use} localPath={localPath} />
            ))}
          </td>
        </tr>
      )}
    </Fragment>
  )
}

/** One project's assessment of the package: reason, changed members and call
 * sites, confirmed and possible (ambiguous) sites kept visibly apart. */
function ProjectUseDetail({ use, localPath }: { use: ProjectUse; localPath: string | null }) {
  const pkg = use.pkg
  const declaredAt = obj(pkg.declaredAt)
  const members = list(pkg.breakingMembers)
  const sites = list(pkg.callSites)
  const confirmed = sites.filter((s) => str(s.certainty) !== 'ambiguous')
  const possible = sites.filter((s) => str(s.certainty) === 'ambiguous')
  const site = (s: Json, i: number) => (
    <li key={i} className="font-mono text-[11px]">
      <SourceLink localPath={localPath} filePath={str(s.filePath) ?? ''} line={num(s.lineStart, 1)} className="text-violet-700">
        {str(s.filePath)}:{num(s.lineStart)}
      </SourceLink>
      <span className="text-neutral-400"> {str(s.member)}</span>
    </li>
  )
  return (
    <div className="min-w-0">
      <p className="text-[11px]">
        <SourceLink localPath={localPath} filePath={str(declaredAt.filePath) ?? ''} line={num(declaredAt.line, 1)} className="font-mono text-neutral-700">
          {use.project}
        </SourceLink>{' '}
        <OutcomeBadge pkg={pkg} />
      </p>
      <p className="text-[11px] text-neutral-600">{str(pkg.outcomeReason)}</p>
      {list<string>(pkg.confidenceReasons).length > 0 && (
        <p className="text-[11px] text-neutral-400">
          confidence {num(pkg.confidence).toFixed(2)} — {list<string>(pkg.confidenceReasons).join('; ')}
        </p>
      )}
      {members.length > 0 && (
        <div className="mt-1">
          <p className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">Changed members the code calls</p>
          <ul className="mt-0.5 space-y-0.5">
            {members.map((m, i) => (
              <li key={i} className="font-mono text-[11px] text-neutral-700">
                <span className="text-neutral-400">{str(m.change)?.replace(/_/g, ' ')}</span> {str(m.type)}
                {str(m.member) ? `.${str(m.member)}` : ''}
                {str(m.oldSignature) && <span className="block pl-4 text-neutral-400">was {str(m.oldSignature)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {confirmed.length > 0 && (
        <div className="mt-1">
          <p className="text-[11px] font-medium uppercase tracking-wide text-neutral-400">Call sites ({confirmed.length})</p>
          <ul className="mt-0.5 space-y-0.5">{confirmed.map(site)}</ul>
        </div>
      )}
      {possible.length > 0 && (
        <div className="mt-1">
          <p className="text-[11px] font-medium uppercase tracking-wide text-neutral-400" title="An unchanged overload accepts the same arguments; syntax cannot tell which one the call binds to">
            Possible call sites ({possible.length}) — may bind to an unchanged overload
          </p>
          <ul className="mt-0.5 space-y-0.5 opacity-75">{possible.map(site)}</ul>
        </div>
      )}
      {str(pkg.outcome) === 'upgrade_breaking' && sites.length === 0 && (
        <p className="mt-1 text-[11px] text-neutral-500">No API diff was possible, so call sites were not determined; semver presumes a break.</p>
      )}
    </div>
  )
}

// ---------- item-occurrences (step 7): the work list ----------

const STATE_RANK: Record<string, number> = { found: 0, not_checked: 1, excluded: 2, checked_absent: 3, skipped: 4 }
const STATE_STYLE: Record<string, string> = {
  found: 'border-violet-200 bg-violet-50 text-violet-700',
  not_checked: 'border-amber-200 bg-amber-50 text-amber-800',
  excluded: 'border-neutral-200 bg-neutral-50 text-neutral-500',
  checked_absent: 'border-neutral-200 bg-white text-neutral-400',
}

/** One located occurrence: item_occurrences stays per file (conversion
 * batches per file); the work list only groups them for display. */
interface WorkFile {
  filePath: string
  line: number | null
  value: string | null
  /** item-occurrences 1.1.0: 'possible' when every piece of evidence is ambiguous. */
  certainty: string
}

/** One row of the work list: one item in one project. */
interface WorkGroup {
  itemId: string
  scope: string
  project: string
  projectId: string
  /** Application scope: the item's recorded attribute (wcf-service's hosting). */
  attribute: string | null
  state: string
  reason: string | null
  /** Occurrence scope, found: each located occurrence, confirmed first. */
  files: WorkFile[]
  /** Application scope: the files whose signals made the item apply. */
  evidencePaths: string[]
}

/** How many files a work-list row lists before "+N more". */
const FILES_SHOWN = 3

const possibleOnly = (g: WorkGroup) => g.files.length > 0 && g.files.every((f) => f.certainty === 'possible')

/** The work list. With `decisions` (the repository page), each row also
 * shows the engagement's decision for the item — derived or manual, what it
 * follows and drives — and what another item's decision subsumes (Part S). */
export function ItemOccurrencesView({ data, localPath, decisions }: ArtifactRendererProps & { decisions?: WorkListDecisions | null }) {
  const [showAll, setShowAll] = useState(false)
  // Possible occurrences rest only on ambiguous evidence: shown, but left
  // out of the totals unless the reader asks for them.
  const [countPossible, setCountPossible] = useState(false)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [names, setNames] = useState<Record<string, string>>({})
  // occurrence_source.group_by per item: value-grouped items are listed by
  // value under their file, since their occurrences share files.
  const [groupBy, setGroupBy] = useState<Record<string, string>>({})

  useEffect(() => {
    let cancelled = false
    listCatalogItems({})
      .then((items) => {
        if (cancelled) return
        setNames(Object.fromEntries(items.map((i) => [i.id, i.name])))
        setGroupBy(Object.fromEntries(items.map((i) => [i.id, i.detection.occurrence_source?.group_by ?? 'source_path'])))
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [])

  const groups = useMemo(() => {
    const result: WorkGroup[] = []
    for (const project of list(data.projects)) {
      const projectPath = str(project.projectPath) ?? ''
      for (const item of list(project.items)) {
        const state = str(item.detectionState) ?? ''
        const occurrences = list(item.occurrences)
        const files = occurrences
          .filter((o) => str(o.filePath))
          .map((o) => ({
            filePath: str(o.filePath) ?? '',
            line: num(obj(list(o.evidence)[0]).line_start, 0) || null,
            value: str(o.value),
            certainty: str(o.certainty) ?? 'confirmed',
          }))
          .sort(
            (a, b) =>
              (a.certainty === 'possible' ? 1 : 0) - (b.certainty === 'possible' ? 1 : 0) ||
              a.filePath.localeCompare(b.filePath) ||
              (a.value ?? '').localeCompare(b.value ?? ''),
          )
        const evidencePaths =
          files.length > 0
            ? []
            : [...new Set(occurrences.flatMap((o) => list(o.evidence).map((e) => str(e.source_path)).filter((p): p is string => p !== null)))].sort()
        result.push({
          itemId: str(item.itemId) ?? '',
          scope: str(item.scope) ?? '',
          project: projectPath,
          projectId: str(project.projectId) ?? '',
          attribute: str(item.scope) === 'application' ? (occurrences.map((o) => str(o.value)).find((v) => v) ?? null) : null,
          state,
          reason: str(item.reason),
          files: state === 'found' ? files : [],
          evidencePaths,
        })
      }
    }
    return result.sort(
      (a, b) =>
        (STATE_RANK[a.state] ?? 9) - (STATE_RANK[b.state] ?? 9) ||
        a.itemId.localeCompare(b.itemId) ||
        (possibleOnly(a) ? 1 : 0) - (possibleOnly(b) ? 1 : 0) ||
        a.project.localeCompare(b.project),
    )
  }, [data])

  const summary = obj(data.summary)
  // The work list is what needs doing: found, and what could not be checked.
  const visible = showAll ? groups : groups.filter((g) => g.state === 'found' || g.state === 'not_checked')
  const found = groups.filter((g) => g.state === 'found')
  // Totals count occurrences (one per file), as item_occurrences does; an
  // unlocated found item is one occurrence.
  const occurrenceCount = found.reduce((n, g) => n + Math.max(g.files.length, 1), 0)
  const possibleCount = found.reduce((n, g) => n + g.files.filter((f) => f.certainty === 'possible').length, 0)
  const countedRows = countPossible ? occurrenceCount : occurrenceCount - possibleCount
  const countedFound = num(summary.found) - (countPossible ? 0 : num(summary.possible_only_found))

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip tone="teal" title="Item and project pairs where the item was found">
          {countedFound} found
        </Chip>
        <Chip title="Found occurrences, one per file: the work list's size">{countedRows} occurrences</Chip>
        {possibleCount > 0 && (
          <Chip title="Occurrences whose every piece of evidence is ambiguous (e.g. a call an unchanged overload could take). Shown below, not counted unless you include them.">
            {possibleCount} possible {countPossible ? '(counted)' : '(not counted)'}
          </Chip>
        )}
        {num(summary.not_checked) > 0 && <Chip tone="amber">{num(summary.not_checked)} not checked</Chip>}
        <Chip>{num(summary.checked_absent)} checked absent</Chip>
        {num(summary.excluded) > 0 && <Chip>{num(summary.excluded)} excluded by role</Chip>}
        <div className="ml-auto flex flex-wrap items-center gap-3">
          {possibleCount > 0 && (
            <label className="flex items-center gap-1.5 text-[11px] text-neutral-500">
              <input type="checkbox" checked={countPossible} onChange={(e) => setCountPossible(e.target.checked)} />
              Count possible in totals
            </label>
          )}
          <label className="flex items-center gap-1.5 text-[11px] text-neutral-500">
            <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            Show checked-absent and excluded
          </label>
        </div>
      </div>
      {visible.length === 0 ? (
        <p className="text-xs text-neutral-400">Nothing found — no work items for this repository.</p>
      ) : (
        <Table head={['Item', 'Scope', 'Project', 'Files', 'Detection', ...(decisions ? ['Decision'] : [])]} minWidth={decisions ? 900 : 680}>
          {visible.map((g) => {
            const key = `${g.itemId}|${g.project}`
            return (
              <WorkGroupRow
                key={key}
                group={g}
                name={names[g.itemId]}
                decisions={decisions ?? null}
                byValue={groupBy[g.itemId] === 'source_path_and_value'}
                localPath={localPath}
                expanded={!!open[key]}
                onToggle={() => setOpen((o) => ({ ...o, [key]: !o[key] }))}
              />
            )
          })}
        </Table>
      )}
    </div>
  )
}

function CertaintyTag({ certainty }: { certainty: string }) {
  return (
    <span
      className={`ml-1.5 rounded border px-1 font-sans text-[10px] ${certainty === 'possible' ? 'border-dashed border-violet-300 text-violet-600' : 'border-violet-200 text-violet-700'}`}
      title={certainty === 'possible' ? 'Every piece of evidence is ambiguous' : 'At least one confirmed piece of evidence'}
    >
      {certainty}
    </span>
  )
}

/** Value-grouped occurrences (group_by source_path_and_value) under their
 * file: each value — a package with its versions, a path literal — linking
 * to its own line. Generic over items; nothing here knows about packages. */
function ValuesByFile({ entries, localPath, showCertainty }: { entries: WorkFile[]; localPath: string | null; showCertainty: boolean }) {
  const byFile = new Map<string, WorkFile[]>()
  for (const entry of entries) {
    if (!byFile.has(entry.filePath)) byFile.set(entry.filePath, [])
    byFile.get(entry.filePath)!.push(entry)
  }
  return (
    <>
      {[...byFile.entries()].map(([filePath, values]) => (
        <span key={filePath} className="block">
          <SourceLink localPath={localPath} filePath={filePath} line={1} className="text-violet-700">
            {filePath}
          </SourceLink>
          {values.map((v, i) => (
            <span key={`${v.value}|${i}`} className="block pl-3 text-neutral-600">
              <SourceLink localPath={localPath} filePath={filePath} line={v.line ?? 1} className="text-neutral-700" title={`${filePath}${v.line ? `:${v.line}` : ''}`}>
                {v.value ?? '(no value)'}
              </SourceLink>
              {v.line ? <span className="text-neutral-400">:{v.line}</span> : null}
              {showCertainty && <CertaintyTag certainty={v.certainty} />}
            </span>
          ))}
        </span>
      ))}
    </>
  )
}

const DECISION_STATUS_STYLE: Record<string, string> = {
  approved: 'border-teal-200 bg-teal-50 text-teal-800',
  in_review: 'border-sky-200 bg-sky-50 text-sky-800',
  pending: 'border-neutral-200 bg-neutral-50 text-neutral-600',
}

/** The engagement's decision for this row's item (Part S): what it is,
 * whether it was derived (and from what) or overridden by hand, what it
 * drives, and — per project — whether another decision subsumes it or a
 * follow rule does not apply here. */
function DecisionCell({ group: g, decisions }: { group: WorkGroup; decisions: WorkListDecisions }) {
  const decision = decisions.decisions[g.itemId]
  const note = decisions.projects.find((p) => p.project_id === g.projectId)?.items[g.itemId]
  if (note?.subsumed_by) {
    return (
      <td className="py-1.5 text-[11px]">
        <span className="rounded border border-violet-200 bg-violet-50 px-1 text-violet-800" title={note.subsumed_by.reason}>
          subsumed by {note.subsumed_by.item_id}
        </span>
        <span className="block text-neutral-500">{note.subsumed_by.resolution_name} — no separate work</span>
      </td>
    )
  }
  const notHere = note && note.applies === false
  return (
    <td className="py-1.5 text-[11px]">
      {decision ? (
        <>
          <span className="font-medium text-neutral-800">{decision.resolution_name ?? '(no option chosen)'}</span>{' '}
          <span className={`rounded border px-1 ${DECISION_STATUS_STYLE[decision.status] ?? DECISION_STATUS_STYLE.pending}`}>{decision.status.replace('_', ' ')}</span>
          {decision.source === 'derived' && decision.derived_from && (
            <span className="mt-0.5 block text-violet-700">
              derived from {decision.derived_from.item_id} ({decision.derived_from.resolution_name})
            </span>
          )}
          {decision.overrides_derivation && decision.derived_from && !decision.needs_review && (
            <span className="mt-0.5 block text-amber-700">
              overridden by hand
              {decision.derived_from.would_derive && <> — {decision.derived_from.item_id} would give {decision.derived_from.would_derive}</>}
            </span>
          )}
          {decision.needs_review && (
            <span className="mt-0.5 block rounded border border-amber-300 bg-amber-50 px-1 text-amber-900">
              <span className="font-semibold">needs review</span> — {decision.review_note}
            </span>
          )}
          {(decision.followers ?? []).length > 0 && (
            <span className="mt-0.5 block text-neutral-500">
              drives{' '}
              {decision.followers!
                .map((f) => `${f.item_id} (${f.source === 'derived' ? 'derived' : f.needs_review ? 'overridden, needs review' : 'overridden'})`)
                .join(', ')}
            </span>
          )}
        </>
      ) : (
        <span className="text-neutral-400">
          not decided
          {note?.follows && note.applies !== false && <span className="block">will follow {note.follows} once it is decided</span>}
        </span>
      )}
      {notHere && <span className="mt-0.5 block text-neutral-500">{note!.note}</span>}
      {note?.applies && decision?.source === 'derived' && <span className="mt-0.5 block text-neutral-400">{note.note}</span>}
    </td>
  )
}

function WorkGroupRow({
  group: g,
  name,
  decisions,
  byValue,
  localPath,
  expanded,
  onToggle,
}: {
  group: WorkGroup
  name: string | undefined
  decisions: WorkListDecisions | null
  /** The item groups occurrences by file and value: list values under files. */
  byValue: boolean
  localPath: string | null
  expanded: boolean
  onToggle: () => void
}) {
  const possible = g.files.filter((f) => f.certainty === 'possible').length
  const allPossible = possibleOnly(g)
  const mixed = possible > 0 && !allPossible
  const shown = expanded ? g.files : g.files.slice(0, FILES_SHOWN)
  // A value-grouped item puts several occurrences in one file (one per
  // package in a project file), so values and files are counted apart.
  const distinctFiles = new Set(g.files.map((f) => f.filePath)).size
  const fileWord = `${distinctFiles} file${distinctFiles === 1 ? '' : 's'}`
  const countLabel = byValue
    ? `${g.files.length} value${g.files.length === 1 ? '' : 's'} in ${fileWord}`
    : distinctFiles === g.files.length
      ? `${g.files.length} files`
      : `${g.files.length} occurrences in ${fileWord}`
  return (
    <tr className="border-b border-neutral-100 align-top last:border-0">
      <td className="py-1.5 pr-3">
        <span className="font-medium text-neutral-800">{name ?? g.itemId}</span>
        {name && <span className="block font-mono text-[11px] text-neutral-400">{g.itemId}</span>}
        {g.attribute && <span className="block text-[11px] text-neutral-500">{g.attribute}</span>}
      </td>
      <td className="py-1.5 pr-3 text-neutral-500">{g.scope}</td>
      <td className="break-all py-1.5 pr-3 font-mono text-[11px] text-neutral-600" title={g.project}>
        {g.project.split('/').pop()}
      </td>
      <td className="break-all py-1.5 pr-3 font-mono text-[11px]">
        {g.files.length > 0 ? (
          <>
            {g.files.length > 1 && <span className="block text-neutral-400">{countLabel}</span>}
            {byValue ? (
              <ValuesByFile entries={shown} localPath={localPath} showCertainty={mixed || allPossible} />
            ) : (
              shown.map((f, i) => (
              <span key={`${f.filePath}|${f.value}|${i}`} className="block">
                <SourceLink localPath={localPath} filePath={f.filePath} line={f.line ?? 1} className="text-violet-700">
                  {f.filePath}
                  {f.line ? `:${f.line}` : ''}
                </SourceLink>
                {(mixed || allPossible) && <CertaintyTag certainty={f.certainty} />}
                {f.value && <span className="block text-neutral-400">{f.value}</span>}
              </span>
              ))
            )}
            <ShowMoreToggle expanded={expanded} hidden={g.files.length - FILES_SHOWN} onToggle={onToggle} className="block font-sans" />
          </>
        ) : g.evidencePaths.length > 0 ? (
          <span className="text-neutral-500" title="Application scope: the files whose signals made this item apply">
            {g.evidencePaths.map((path) => (
              <span key={path} className="block">
                <SourceLink localPath={localPath} filePath={path} line={1} className="text-violet-700">
                  {path}
                </SourceLink>
              </span>
            ))}
          </span>
        ) : (
          <span className="text-neutral-300">{g.scope === 'application' ? 'whole project' : '—'}</span>
        )}
      </td>
      <td className="py-1.5 pr-3">
        {allPossible ? (
          <span
            className="whitespace-nowrap rounded border border-dashed border-violet-300 bg-white px-1.5 py-0.5 text-[10px] font-semibold text-violet-600"
            title="Every piece of evidence is ambiguous: the code may not use what changed. Not counted in totals by default."
          >
            possible
          </span>
        ) : (
          <span className={`whitespace-nowrap rounded border px-1.5 py-0.5 text-[10px] font-semibold ${STATE_STYLE[g.state] ?? STATE_STYLE.excluded}`}>
            {g.state.replace('_', ' ')}
          </span>
        )}
        {allPossible && <span className="block text-[11px] text-neutral-400">ambiguous evidence only</span>}
        {mixed && <span className="block text-[11px] text-neutral-400">{possible} of {g.files.length} possible</span>}
        {g.reason && <span className="block text-[11px] text-neutral-400">{g.reason}</span>}
      </td>
      {decisions && <DecisionCell group={g} decisions={decisions} />}
    </tr>
  )
}
