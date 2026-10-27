import { Fragment, useEffect, useState } from 'react'
import {
  dependencyPackages,
  dependencyUses,
  fingerprintSignals,
  getFingerprintOverview,
  getWorkItemTotals,
  listDependencyFeeds,
  workItemFiles,
  workItems,
} from '../../api/results'
import { LimitedList } from '../../components/LimitedList'
import { PagedList, type Page } from '../../components/PagedList'
import type { WorkListDecisions } from '../../types/items'
import { list, num, obj, str, type Json } from '../workflow/artifacts/adapters'
import {
  CertaintyTag,
  Chip,
  ItemDecisionCell,
  OutcomeBadge,
  ProjectUseDetail,
  STATE_STYLE,
  Table,
  packageReasons,
  shortProjectPath,
  type ProjectUse,
  type WorkFile,
} from '../workflow/artifacts/renderers'
import { SourceLink } from './SourceLink'

// The repository page's fingerprint, dependencies and work list, read from the stored result (backend app.results)
// a page at a time: the header from the artifact's summary, each list from the database 20 at a time, filtered there.
// An execution's own artifact viewer still renders a whole artifact (renderers.tsx).

interface StoredViewProps {
  artifactId: string
  /** The artifact without its lists: summary, versions. */
  head: Json
  localPath: string | null
}

// ---------- application-fingerprint ----------

interface SignalRow {
  name: string
  value: string | null
  project: string
  sourcePath: string | null
  occurrences: number
  confidence: number
}

export function StoredFingerprintView({ artifactId, head }: StoredViewProps) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [overview, setOverview] = useState<Awaited<ReturnType<typeof getFingerprintOverview>> | null>(null)
  const summary = obj(head.summary)

  useEffect(() => {
    let live = true
    getFingerprintOverview(artifactId).then((r) => live && setOverview(r), () => live && setOverview({ status_counts: {}, categories: [] }))
    return () => {
      live = false
    }
  }, [artifactId])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        <Chip>{num(summary.totalSignals)} signals</Chip>
        <Chip>{num(summary.totalEvidence)} evidence</Chip>
        {Object.entries(overview?.status_counts ?? {}).map(([status, count]) => (
          <Chip key={status} tone={status === 'FAILED' ? 'red' : 'neutral'} title="Projects by fingerprint status">
            {count} {status.toLowerCase()}
          </Chip>
        ))}
        {str(head.signalRegistryVersion) && <Chip>registry {str(head.signalRegistryVersion)}</Chip>}
      </div>
      {!overview ? (
        <p className="text-xs text-neutral-400">Loading…</p>
      ) : (
        <LimitedList
          items={overview.categories}
          name={(c) => c.category.replace(/_/g, ' ').toLowerCase()}
          noun="signal categories"
          empty={<p className="text-xs text-neutral-400">No signals.</p>}
        >
          {(visibleCategories) => (
            <ul className="divide-y divide-neutral-100 rounded border border-neutral-200">
              {visibleCategories.map(({ category, signals, distinct }) => (
                <li key={category}>
                  <button
                    type="button"
                    onClick={() => setOpen((o) => ({ ...o, [category]: !o[category] }))}
                    className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-neutral-50"
                  >
                    <span className="text-neutral-400">{open[category] ? '▾' : '▸'}</span>
                    <span className="font-medium text-neutral-800">{category.replace(/_/g, ' ').toLowerCase()}</span>
                    <span className="text-neutral-400">
                      {signals} signal{signals === 1 ? '' : 's'} · {distinct} distinct
                    </span>
                  </button>
                  {open[category] && (
                    <PagedList<SignalRow> load={fingerprintSignals(artifactId, category)} resetKey={`${artifactId}|${category}`} noun="signals" className="px-3 pb-2">
                      {(visibleRows) => (
                        <Table head={['Signal', 'Value', 'Project', 'Occurrences']} minWidth={520}>
                          {visibleRows.map((r, i) => (
                            <tr key={`${r.name}|${r.project}|${r.value}|${i}`} className="border-b border-neutral-100 align-top last:border-0">
                              <td className="py-1 pr-3 font-mono text-[11px] text-neutral-800">{r.name}</td>
                              <td className="max-w-[16rem] break-all py-1 pr-3 font-mono text-[11px] text-neutral-500">{r.value ?? '—'}</td>
                              <td className="break-all py-1 pr-3 font-mono text-[11px] text-neutral-500" title={r.sourcePath ?? undefined}>
                                {r.project.split('/').pop()}
                              </td>
                              <td className="py-1 pr-3 text-neutral-600">
                                {r.occurrences}
                                {r.confidence < 1 && <span className="ml-1 text-neutral-400">({Number(r.confidence).toFixed(2)})</span>}
                              </td>
                            </tr>
                          ))}
                        </Table>
                      )}
                    </PagedList>
                  )}
                </li>
              ))}
            </ul>
          )}
        </LimitedList>
      )}
    </div>
  )
}

// ---------- dependency-assessment ----------

interface StoredVersion {
  version: string
  useCount: number
  outcomes: string[]
  /** The project whose assessment blocks first: what the row's columns show. */
  worst: ProjectUse
  /** The first project, by path, for the package's link to where it is declared. */
  first: { project: string; declaredAt: Json | null }
  /** The first 20 projects, by path. */
  projects: string[]
}

interface StoredPackage {
  packageId: string
  drift: boolean
  projectCount: number
  versions: StoredVersion[]
}

export function StoredDependenciesView({ artifactId, head, localPath }: StoredViewProps) {
  const [showCurrent, setShowCurrent] = useState(false)
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const [feeds, setFeeds] = useState<Json[]>([])
  const summary = obj(head.summary)
  const outcomes = obj(summary.countByOutcome) as Record<string, number>
  const sources = obj(summary.countByFeedSource) as Record<string, number>
  const targetFramework = str(head.targetFramework)

  useEffect(() => {
    let live = true
    listDependencyFeeds(artifactId).then((r) => live && setFeeds(r as Json[]), () => live && setFeeds([]))
    return () => {
      live = false
    }
  }, [artifactId])

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip>{num(summary.packageCount)} package references</Chip>
        {(outcomes.no_compatible_version ?? 0) > 0 && <Chip tone="red">{outcomes.no_compatible_version} no compatible version</Chip>}
        {(outcomes.upgrade_breaking ?? 0) > 0 && <Chip tone="amber">{outcomes.upgrade_breaking} breaking</Chip>}
        {(outcomes.framework_provided ?? 0) > 0 && <Chip>{outcomes.framework_provided} provided by framework</Chip>}
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
      <div className="text-[11px] text-neutral-500">
        Target <span className="font-mono">{targetFramework}</span> · answered by{' '}
        {(sources.client_feed ?? 0) > 0 && <span className="font-medium text-teal-700">client feed ×{sources.client_feed} </span>}
        {(sources.nuget_org_fallback ?? 0) > 0 && <span className="font-medium text-neutral-700">nuget.org fallback ×{sources.nuget_org_fallback} </span>}
        {(sources.none ?? 0) > 0 && <span className="text-neutral-500">no feed ×{sources.none}</span>}
        <LimitedList items={feeds} name={(f) => [str(f.name), str(f.url)]} noun="feeds">
          {(visibleFeeds) => (
            <span className="block text-neutral-400">
              Feeds:{' '}
              {visibleFeeds.map((f, i) => (
                <span key={i} title={`${str(f.url)} — declared in ${str(f.declaredIn)}`}>
                  {i > 0 && ' · '}
                  {str(f.name)} <span className="text-neutral-300">({str(f.role)?.replace(/_/g, ' ')})</span>
                </span>
              ))}
            </span>
          )}
        </LimitedList>
      </div>
      <p className="text-[11px] text-neutral-500">
        <span className="font-medium text-neutral-700">Version in use</span> is what the project references now;{' '}
        <span className="font-medium text-neutral-700">Recommended version</span> is the newest that supports {targetFramework} and has no known advisory.{' '}
        <span className="font-medium text-neutral-700">Vulnerable</span> always refers to the version in use.
      </p>
      <PagedList<StoredPackage>
        load={dependencyPackages(artifactId, showCurrent)}
        resetKey={`${artifactId}|${showCurrent}`}
        noun="packages"
        empty={<p className="text-xs text-neutral-400">No packages to show.</p>}
      >
        {(visibleGroups) => (
          <Table head={['Package', 'Projects', 'Version in use', 'Recommended version', 'Outcome', 'Flags', 'Reason', 'Feed']} minWidth={1200}>
            {visibleGroups.map((group) => (
              <Fragment key={group.packageId}>
                {group.drift && (
                  <tr className="border-b border-neutral-100 bg-amber-50/40 align-top">
                    <td className="py-1.5 pr-3 font-medium text-neutral-800">{group.packageId}</td>
                    <td colSpan={7} className="py-1.5 pr-3">
                      <Chip tone="amber" title="One package at different versions across projects. Consolidating first is usually the sensible order before upgrading.">
                        version drift: {group.versions.length} versions across {group.projectCount} projects
                      </Chip>
                    </td>
                  </tr>
                )}
                {group.versions.map((version) => {
                  const key = `${group.packageId}|${version.version}`
                  return (
                    <StoredVersionRow
                      key={key}
                      artifactId={artifactId}
                      group={group}
                      version={version}
                      localPath={localPath}
                      targetFramework={targetFramework}
                      expanded={!!open[key]}
                      onToggle={() => setOpen((o) => ({ ...o, [key]: !o[key] }))}
                    />
                  )
                })}
              </Fragment>
            ))}
          </Table>
        )}
      </PagedList>
    </div>
  )
}

function StoredVersionRow({
  artifactId,
  group,
  version,
  localPath,
  targetFramework,
  expanded,
  onToggle,
}: {
  artifactId: string
  group: StoredPackage
  version: StoredVersion
  localPath: string | null
  targetFramework: string | null
  expanded: boolean
  onToggle: () => void
}) {
  const pkg = version.worst.pkg
  const deprecated = pkg.deprecated ? obj(pkg.deprecated) : null
  const vulnerable = pkg.vulnerable ? obj(pkg.vulnerable) : null
  const gap = pkg.notInClientFeed ? obj(pkg.notInClientFeed) : null
  const recommended = str(pkg.recommendedVersion)
  const latest = str(pkg.latestVersion)
  const kind = str(pkg.packageKind)
  const declaredAt = obj(version.first.declaredAt)
  // The first page of projects came with the row; the rest, with their assessments, from the server.
  const firstProjects: Page<ProjectUse> = {
    total: version.useCount,
    matching: version.useCount,
    offset: 0,
    items: version.projects.map((project) => ({ project, pkg: {} })),
  }
  const uses = dependencyUses(artifactId, group.packageId, version.version)

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
          <PagedList<ProjectUse> load={uses} resetKey={`${artifactId}|${group.packageId}|${version.version}`} initial={firstProjects} noun="projects">
            {(visibleUses) =>
              visibleUses.map((u) => (
                <span key={u.project} className="block max-w-[15rem] truncate" title={u.project}>
                  {shortProjectPath(u.project)}
                </span>
              ))
            }
          </PagedList>
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
          {version.outcomes.length > 1 && <span className="block text-[11px] text-amber-700">varies by project</span>}
          {str(pkg.classificationMethod) && (
            <span className="block text-[11px] text-neutral-400">
              {{ api_diff: 'API diff', semver_heuristic: 'semver heuristic', package_kind: 'by package kind' }[str(pkg.classificationMethod) ?? ''] ??
                str(pkg.classificationMethod)}
            </span>
          )}
        </td>
        <td className="py-1.5 pr-3">
          <div className="flex flex-wrap gap-1">
            {vulnerable && (
              <Chip
                tone="red"
                title={`${list(vulnerable.advisories).length} advisory(ies)${vulnerable.resolvedByUpgrade === true ? '; the recommended version resolves them' : vulnerable.resolvedByUpgrade === false ? '; the recommended version does not resolve them' : ''}`}
              >
                vulnerable (in use): {str(vulnerable.maxSeverity)}
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
        <td className="max-w-[22rem] py-1.5 pr-3 text-[11px] text-neutral-700">
          {packageReasons(pkg, targetFramework).map((line) => (
            <span key={line} className="block">
              {line}
            </span>
          ))}
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
          <td colSpan={8} className="px-6 py-2">
            <PagedList<ProjectUse> load={uses} resetKey={`${artifactId}|${group.packageId}|${version.version}|detail`} noun="projects">
              {(visibleUses) => (
                <div className="space-y-2">
                  {visibleUses.map((use) => (
                    <ProjectUseDetail key={use.project} use={use} localPath={localPath} />
                  ))}
                </div>
              )}
            </PagedList>
          </td>
        </tr>
      )}
    </Fragment>
  )
}

// ---------- item-occurrences: the work list ----------

type ItemDecision = WorkListDecisions['decisions'][string]
type ItemNote = WorkListDecisions['projects'][number]['items'][string]

/** One row of the work list, as the server shapes it: one item in one project, with the first page of its files. */
interface StoredWorkRow {
  itemId: string
  name: string | null
  groupBy: string
  scope: string
  project: string
  projectId: string
  attribute: string | null
  state: string
  reason: string | null
  fileCount: number
  possibleCount: number
  distinctFiles: number
  files: Page<WorkFile> | Page<FileValues>
  evidencePaths: string[]
  decision: ItemDecision | null
  note: ItemNote | null
}

/** A value-grouped item's file, with its values. */
interface FileValues {
  filePath: string
  values: { value: string | null; line: number | null; certainty: string }[]
}

export function StoredWorkListView({ artifactId, head, localPath, withDecisions = true }: StoredViewProps & { withDecisions?: boolean }) {
  const [showAll, setShowAll] = useState(false)
  // Possible occurrences rest only on ambiguous evidence: shown, but left out of the totals unless asked for.
  const [countPossible, setCountPossible] = useState(false)
  const [totals, setTotals] = useState<{ occurrence_rows: number; possible_rows: number } | null>(null)
  const summary = obj(head.summary)

  useEffect(() => {
    let live = true
    getWorkItemTotals(artifactId).then((r) => live && setTotals(r), () => live && setTotals(null))
    return () => {
      live = false
    }
  }, [artifactId])

  const occurrences = totals?.occurrence_rows ?? 0
  const possible = totals?.possible_rows ?? 0
  const countedRows = countPossible ? occurrences : occurrences - possible
  const countedFound = num(summary.found) - (countPossible ? 0 : num(summary.possible_only_found))

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <Chip tone="teal" title="Item and project pairs where the item was found">
          {countedFound} found
        </Chip>
        <Chip title="Found occurrences, one per file: the work list's size">{countedRows} occurrences</Chip>
        {possible > 0 && (
          <Chip title="Occurrences whose every piece of evidence is ambiguous (e.g. a call an unchanged overload could take). Shown below, not counted unless you include them.">
            {possible} possible {countPossible ? '(counted)' : '(not counted)'}
          </Chip>
        )}
        {num(summary.not_checked) > 0 && <Chip tone="amber">{num(summary.not_checked)} not checked</Chip>}
        <Chip>{num(summary.checked_absent)} checked absent</Chip>
        {num(summary.excluded) > 0 && <Chip>{num(summary.excluded)} excluded by role</Chip>}
        <div className="ml-auto flex flex-wrap items-center gap-3">
          {possible > 0 && (
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
      <PagedList<StoredWorkRow>
        load={workItems(artifactId, showAll)}
        resetKey={`${artifactId}|${showAll}`}
        noun="work items"
        empty={<p className="text-xs text-neutral-400">Nothing found — no work items for this repository.</p>}
      >
        {(visibleRows) => (
          <Table head={['Item', 'Scope', 'Project', 'Files', 'Detection', ...(withDecisions ? ['Decision'] : [])]} minWidth={withDecisions ? 900 : 680}>
            {visibleRows.map((row) => (
              <StoredWorkRowView key={`${row.itemId}|${row.project}`} artifactId={artifactId} row={row} localPath={localPath} withDecisions={withDecisions} />
            ))}
          </Table>
        )}
      </PagedList>
    </div>
  )
}

function StoredWorkRowView({ artifactId, row: g, localPath, withDecisions }: { artifactId: string; row: StoredWorkRow; localPath: string | null; withDecisions: boolean }) {
  const byValue = g.groupBy === 'source_path_and_value'
  const allPossible = g.fileCount > 0 && g.possibleCount === g.fileCount
  const mixed = g.possibleCount > 0 && !allPossible
  const fileWord = `${g.distinctFiles} file${g.distinctFiles === 1 ? '' : 's'}`
  const countLabel = byValue
    ? `${g.fileCount} value${g.fileCount === 1 ? '' : 's'} in ${fileWord}`
    : g.distinctFiles === g.fileCount
      ? `${g.fileCount} files`
      : `${g.fileCount} occurrences in ${fileWord}`
  const files = workItemFiles(artifactId, g.projectId, g.itemId, byValue)
  const key = `${artifactId}|${g.projectId}|${g.itemId}`
  return (
    <tr className="border-b border-neutral-100 align-top last:border-0">
      <td className="py-1.5 pr-3">
        <span className="font-medium text-neutral-800">{g.name ?? g.itemId}</span>
        {g.name && <span className="block font-mono text-[11px] text-neutral-400">{g.itemId}</span>}
        {g.attribute && <span className="block text-[11px] text-neutral-500">{g.attribute}</span>}
      </td>
      <td className="py-1.5 pr-3 text-neutral-500">{g.scope}</td>
      <td className="break-all py-1.5 pr-3 font-mono text-[11px] text-neutral-600" title={g.project}>
        {g.project.split('/').pop()}
      </td>
      <td className="break-all py-1.5 pr-3 font-mono text-[11px]">
        {g.fileCount > 0 ? (
          <>
            {g.fileCount > 1 && <span className="block text-neutral-400">{countLabel}</span>}
            {byValue ? (
              <PagedList<FileValues> load={files} resetKey={key} initial={g.files as Page<FileValues>} noun="files">
                {(visibleFiles) =>
                  visibleFiles.map(({ filePath, values }) => (
                    <div key={filePath}>
                      <SourceLink localPath={localPath} filePath={filePath} line={1} className="text-violet-700">
                        {filePath}
                      </SourceLink>
                      <LimitedList items={values} name={(v) => v.value} noun="values">
                        {(visibleValues) =>
                          visibleValues.map((v, i) => (
                            <span key={`${v.value}|${i}`} className="block pl-3 text-neutral-600">
                              <SourceLink localPath={localPath} filePath={filePath} line={v.line ?? 1} className="text-neutral-700" title={`${filePath}${v.line ? `:${v.line}` : ''}`}>
                                {v.value ?? '(no value)'}
                              </SourceLink>
                              {v.line ? <span className="text-neutral-400">:{v.line}</span> : null}
                              {(mixed || allPossible) && <CertaintyTag certainty={v.certainty} />}
                            </span>
                          ))
                        }
                      </LimitedList>
                    </div>
                  ))
                }
              </PagedList>
            ) : (
              <PagedList<WorkFile> load={files} resetKey={key} initial={g.files as Page<WorkFile>} noun="occurrences">
                {(visibleFiles) =>
                  visibleFiles.map((f, i) => (
                    <span key={`${f.filePath}|${f.value}|${i}`} className="block">
                      <SourceLink localPath={localPath} filePath={f.filePath} line={f.line ?? 1} className="text-violet-700">
                        {f.filePath}
                        {f.line ? `:${f.line}` : ''}
                      </SourceLink>
                      {(mixed || allPossible) && <CertaintyTag certainty={f.certainty} />}
                      {f.value && <span className="block text-neutral-400">{f.value}</span>}
                    </span>
                  ))
                }
              </PagedList>
            )}
          </>
        ) : g.evidencePaths.length > 0 ? (
          <LimitedList items={g.evidencePaths} name={(path) => path} noun="files" className="text-neutral-500">
            {(visiblePaths) => (
              <span title="Application scope: the files whose signals made this item apply">
                {visiblePaths.map((path) => (
                  <span key={path} className="block">
                    <SourceLink localPath={localPath} filePath={path} line={1} className="text-violet-700">
                      {path}
                    </SourceLink>
                  </span>
                ))}
              </span>
            )}
          </LimitedList>
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
        {mixed && (
          <span className="block text-[11px] text-neutral-400">
            {g.possibleCount} of {g.fileCount} possible
          </span>
        )}
        {g.reason && <span className="block text-[11px] text-neutral-400">{g.reason}</span>}
      </td>
      {withDecisions && <ItemDecisionCell decision={g.decision} note={g.note} />}
    </tr>
  )
}
