import { Fragment, useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { getRepositoryImpact, getWorkItemImpact } from '../../api/surface'
import { LimitedList } from '../../components/LimitedList'
import type { FileRollup, ImpactAction, ImpactConflict, ImpactEntry, RepositoryImpact, ResolutionImpact, RollupWorkItem, RuleConflict, RuleSide, WorkItemImpact, WorkItemSummary } from '../../types/impact'
import { SourceLink } from './SourceLink'

/** The order actions are listed in, strongest first (33-IMPACT-ANALYSIS Part F). */
const ACTIONS: ImpactAction[] = ['delete', 'rewrite', 'update', 'create', 'review']

const ACTION_STYLE: Record<ImpactAction, string> = {
  delete: 'border-red-200 bg-red-50 text-red-800',
  rewrite: 'border-amber-200 bg-amber-50 text-amber-800',
  update: 'border-sky-200 bg-sky-50 text-sky-800',
  create: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  review: 'border-neutral-200 bg-neutral-50 text-neutral-600',
}

const ROLE_LABEL: Record<string, string> = { default: 'Default', presumptive: 'Presumptive', chosen: 'Chosen' }

function ActionChip({ action, count }: { action: ImpactAction; count?: number }) {
  return (
    <span className={`inline-block rounded border px-1 text-[11px] ${ACTION_STYLE[action]}`}>
      {count !== undefined ? `${count} ` : ''}
      {action}
    </span>
  )
}

function SourceChip({ source }: { source: 'structural' | 'client' }) {
  if (source === 'structural') return null
  return <span className="inline-block rounded border border-violet-200 bg-violet-50 px-1 text-[11px] text-violet-800">client</span>
}

function roleLabel(roles: string[]) {
  return roles.map((r) => ROLE_LABEL[r] ?? r).join(' and ')
}

const CONFLICT_KIND: Record<ImpactConflict['kind'], string> = {
  delete_with_change: 'delete with change',
  create_same_path: 'create at the same path',
}

function Rules({ ids }: { ids: string[] }) {
  if (ids.length === 0) return null
  return <span className="font-mono text-[11px] text-neutral-400"> [{ids.join(', ')}]</span>
}

function RuleSideRef({ side }: { side: RuleSide }) {
  return (
    <span>
      <span className="font-medium">{side.item_name}</span> · {side.resolution_name} <ActionChip action={side.action} />
      <Rules ids={side.rule_ids} />
    </span>
  )
}

/** Part G, grouped by the rules that produce them: a catalog rule pair
 * recurring on several pairs of work items is fixed once by catalog authors;
 * the rest are decisions about this repository's code. */
function Conflicts({ rules, workItems, localPath }: { rules: RuleConflict[]; workItems: ImpactConflict[]; localPath: string | null }) {
  const [open, setOpen] = useState<number | null>(null)
  if (rules.length === 0 && workItems.length === 0) return <p className="text-xs text-neutral-400">None.</p>
  return (
    <div className="space-y-2">
      {rules.length > 0 && (
        <div>
          <p className="text-xs font-medium text-neutral-700">Catalog rule conflicts — fix once, in the catalog rules</p>
          <LimitedList
            items={rules}
            name={(g) => [g.first.item_name, g.first.resolution_name, g.second.item_name, g.second.resolution_name]}
            noun="rule conflicts"
          >
            {(visible) => (
          <ul className="space-y-1.5">
            {visible.map((g) => {
              const index = rules.indexOf(g)
              return (
              <li key={index} className="text-xs">
                <span className="text-red-700">
                  1 rule conflict affecting {g.work_items} work items across {g.repositories} repositor{g.repositories === 1 ? 'y' : 'ies'}
                </span>
                <span className="text-neutral-500">
                  {' '}
                  · {CONFLICT_KIND[g.kind]} on {g.instances.length} file(s) here
                  {g.classified_by === 'repository' && ' · recurs within this repository; the next estate run classifies it across the estate'}
                </span>
                <ul className="ml-3">
                  <li>
                    <RuleSideRef side={g.first} />
                  </li>
                  <li>
                    <RuleSideRef side={g.second} />
                  </li>
                </ul>
                <button type="button" onClick={() => setOpen(open === index ? null : index)} className="ml-3 text-violet-700 hover:underline">
                  {open === index ? 'hide files' : 'files'}
                </button>
                {open === index && (
                  <LimitedList items={g.instances} name={(c) => c.file_key} noun="files" className="ml-3">
                    {(visibleInstances) => (
                      <ul>
                        {visibleInstances.map((c) => (
                          <li key={`${c.file_key}:${c.first.project_path}:${c.second.project_path}`}>
                            <SourceLink localPath={localPath} filePath={c.file_key} line={1} className="font-mono">
                              {c.file_key}
                            </SourceLink>
                          </li>
                        ))}
                      </ul>
                    )}
                  </LimitedList>
                )}
              </li>
              )
            })}
          </ul>
            )}
          </LimitedList>
        </div>
      )}
      {workItems.length > 0 && (
        <div>
          <p className="text-xs font-medium text-neutral-700">Work-item conflicts — a person decides</p>
          <LimitedList items={workItems} name={(c) => [c.file_key, c.first.item_name, c.second.item_name]} noun="conflicts">
            {(visible) => (
          <ul className="space-y-1.5">
            {visible.map((c, index) => (
              <li key={`${c.file_key}:${index}`}>
                <span className="mr-1 text-xs text-red-700">{CONFLICT_KIND[c.kind]}</span>
                <span className="font-mono text-xs">{c.file_key}</span>
                <ul className="ml-3 text-xs">
                  <li>
                    <WorkItemRef item={c.first} />
                    <Rules ids={c.first.rule_ids} />
                  </li>
                  <li>
                    <WorkItemRef item={c.second} />
                    <Rules ids={c.second.rule_ids} />
                  </li>
                </ul>
              </li>
            ))}
          </ul>
            )}
          </LimitedList>
        </div>
      )}
    </div>
  )
}

function WorkItemRef({ item }: { item: RollupWorkItem }) {
  return (
    <span>
      <span className="font-medium">{item.item_name}</span> <span className="text-neutral-400">on {item.project_path.split('/').pop()}</span> ·{' '}
      {item.resolution_name} <ActionChip action={item.action} /> <SourceChip source={item.source} />
    </span>
  )
}

/** One impacted file: path (a link where it is in this repository), certainty,
 * reasons, and the traversal path back to the seed. */
function EntryRow({ entry, localPath }: { entry: ImpactEntry; localPath: string | null }) {
  return (
    <li className="py-1">
      <div className="flex flex-wrap items-baseline gap-1.5">
        <ActionChip action={entry.action} />
        {entry.file_path ? (
          entry.file_repository_slug ? (
            <span className="font-mono text-xs">
              <span className="text-neutral-400">{entry.file_repository_slug}:</span>
              {entry.file_path}
            </span>
          ) : (
            <SourceLink localPath={localPath} filePath={entry.file_path} line={1} className="font-mono text-xs">
              {entry.file_path}
            </SourceLink>
          )
        ) : (
          <span className="font-mono text-xs text-emerald-700">+ {entry.proposed_path}</span>
        )}
        <SourceChip source={entry.source} />
        {entry.certainty === 'possible' && <span className="text-[11px] text-amber-700">possible</span>}
      </div>
      {entry.description && <p className="ml-1 text-xs text-neutral-600">{entry.description}</p>}
      <LimitedList items={entry.details} name={(d) => d} noun="details">
        {(visible) =>
          visible.map((d) => (
            <p key={d} className="ml-1 text-xs text-neutral-700">
              {d}
            </p>
          ))
        }
      </LimitedList>
      <LimitedList items={entry.reasons} name={(r) => [r.ruleId, r.reason]} noun="reasons">
        {(visible) => (
          <ul className="ml-1 text-xs text-neutral-600">
            {visible.map((r) => (
              <li key={r.ruleId}>
                <span className="font-mono text-neutral-400">{r.ruleId}</span> {r.reason}
              </li>
            ))}
          </ul>
        )}
      </LimitedList>
      <LimitedList items={entry.traversal_paths} name={(p) => p} noun="paths" className="ml-1">
        {(visible) => (
          <ul className="text-[11px] text-neutral-400">
            {visible.map((p) => (
              <li key={p} className="font-mono">
                {p}
              </li>
            ))}
          </ul>
        )}
      </LimitedList>
    </li>
  )
}

/** One resolution's files, grouped by action, expandable per group. */
function ResolutionFiles({ resolution, localPath }: { resolution: ResolutionImpact; localPath: string | null }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  return (
    <div className="min-w-0 flex-1">
      <h5 className="mb-1 text-xs font-medium text-neutral-700">
        {roleLabel(resolution.roles)}: {resolution.name}
        {resolution.rules_source === 'default' && <span className="ml-1 font-normal text-neutral-400">(default rule: its own evidence)</span>}
      </h5>
      {resolution.stale && <p className="mb-1 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-xs text-amber-800">Stale: {resolution.stale_reason}</p>}
      {ACTIONS.map((action) => {
        const entries = resolution.entries.filter((e) => e.action === action)
        if (entries.length === 0) return null
        const key = action
        return (
          <div key={action} className="mb-1">
            <button type="button" onClick={() => setOpen((o) => ({ ...o, [key]: !o[key] }))} className="text-xs text-violet-700 hover:underline">
              {open[key] ? '▾' : '▸'} {action} ({entries.length})
            </button>
            {open[key] && (
              <LimitedList items={entries} name={(e) => [e.file_repository_slug, e.file_path ?? e.proposed_path]} noun="files" className="ml-3">
                {(visible) => (
                  <ul className="divide-y divide-neutral-100">
                    {visible.map((e) => (
                      <EntryRow key={`${e.source}:${e.file_repository_slug ?? ''}:${e.file_path ?? e.proposed_path}`} entry={e} localPath={localPath} />
                    ))}
                  </ul>
                )}
              </LimitedList>
            )}
          </div>
        )
      })}
      {resolution.known_limits.length > 0 && (
        <div className="mt-1 text-xs text-neutral-500">
          Known limits:
          <LimitedList items={resolution.known_limits} name={(l) => l} noun="known limits">
            {(visible) => (
              <ul className="ml-3 list-disc">
                {visible.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            )}
          </LimitedList>
        </div>
      )}
    </div>
  )
}

/** Part J: where the default and the chosen resolution are both computed,
 * side by side — counts first, then the file lists beneath. */
function WorkItemDetail({ repositoryId, workItem, localPath }: { repositoryId: string; workItem: WorkItemSummary; localPath: string | null }) {
  const [data, setData] = useState<WorkItemImpact | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    getWorkItemImpact(repositoryId, workItem.item_id, workItem.project_path)
      .then((result) => !cancelled && setData(result))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [repositoryId, workItem.item_id, workItem.project_path])

  if (failed) return <p className="text-xs text-red-600">Could not load this work item's impact.</p>
  if (!data) return <div className="h-10 animate-pulse rounded bg-neutral-100" />

  const columns = data.resolutions
  const cells = (value: (r: ResolutionImpact) => string | number, className = '') =>
    columns.map((r) => (
      <td key={r.resolution_id} className={`pr-6 font-mono ${className}`}>
        {value(r)}
      </td>
    ))
  return (
    <div className="space-y-3 rounded border border-neutral-200 bg-neutral-50/50 p-3">
      <table className="text-xs">
        <thead>
          <tr className="text-left text-neutral-500">
            <th className="pr-4 font-normal" />
            {columns.map((r) => (
              <th key={r.resolution_id} className="pr-6 font-medium text-neutral-700">
                {roleLabel(r.roles)} — {r.name}
                {r.effective && <span className="ml-1 font-normal text-neutral-400">(effective)</span>}
                {r.stale && <span className="ml-1 font-normal text-amber-700">stale</span>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {(['rewrite', 'update', 'delete'] as ImpactAction[]).map((action) => (
            <tr key={action}>
              <td className="pr-4 capitalize text-neutral-500">{action}</td>
              {cells((r) => r.counts[action])}
            </tr>
          ))}
          <tr className="border-t border-neutral-200 font-medium">
            <td className="pr-4">Files changed</td>
            {cells((r) => r.changed)}
          </tr>
          <tr>
            <td className="pr-4 text-neutral-500">New files</td>
            {cells((r) => r.created)}
          </tr>
          <tr>
            <td className="pr-4 text-neutral-500">Files to review</td>
            {cells((r) => r.to_review)}
          </tr>
          <tr>
            <td className="pr-4 text-neutral-500">Client files changed · to review</td>
            {cells((r) => `${r.client_changed} · ${r.client_review}`)}
          </tr>
          <tr>
            <td className="pr-4 text-neutral-500">Confirmed · possible</td>
            {cells((r) => `${r.confirmed} · ${r.possible}`)}
          </tr>
        </tbody>
      </table>
      <p className="text-[11px] text-neutral-400">
        Files changed are updated, rewritten or deleted; new files and files to review are counted apart and never added to them. Structural figures
        come from impact analysis; client files are added by the estate job and listed with the files below.
      </p>

      <div className="flex flex-col gap-4 lg:flex-row">
        {columns.map((r) => (
          <ResolutionFiles key={r.resolution_id} resolution={r} localPath={localPath} />
        ))}
      </div>

      <p className="text-xs text-neutral-500">
        {data.pending_note}
        {data.pending.length > 0 && <> Pending: {data.pending.map((p) => p.name).join(', ')}.</>}
      </p>
    </div>
  )
}

function FileKey({ file, localPath }: { file: FileRollup; localPath: string | null }) {
  if (file.file_key.startsWith('create:')) return <span className="font-mono text-xs text-emerald-700">+ {file.file_key.slice('create:'.length)}</span>
  return (
    <SourceLink localPath={localPath} filePath={file.file_key} line={1} className="font-mono text-xs">
      {file.file_key}
    </SourceLink>
  )
}

/** The work items that touch one file: a list of its own, limited independently of the file list. */
function FileWorkItems({ file }: { file: FileRollup }) {
  return (
    <LimitedList items={file.work_items} name={(i) => [i.item_name, i.project_path]} noun="work items" className="ml-3">
      {(visible) => (
        <ul className="text-xs">
          {visible.map((i) => (
            <li key={`${i.item_id}:${i.project_path}:${i.source}`}>
              <WorkItemRef item={i} />
            </li>
          ))}
        </ul>
      )}
    </LimitedList>
  )
}

/** impact-analysis's Impact section (33-IMPACT-ANALYSIS Part J): the repository summary,
 * hotspots and conflicts, each work item with its default-versus-chosen
 * side by side, and the per-file view. */
export function RepositoryImpactSection({ repositoryId, localPath, refreshToken }: { repositoryId: string; localPath: string | null; refreshToken: number }) {
  const [data, setData] = useState<RepositoryImpact | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'not_scanned' | 'error'>('loading')
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setState('loading')
    getRepositoryImpact(repositoryId)
      .then((result) => {
        if (cancelled) return
        setData(result)
        setState('ready')
      })
      .catch((err) => {
        if (!cancelled) setState(err instanceof ApiError && err.status === 409 ? 'not_scanned' : 'error')
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  if (state === 'loading') return <div className="h-16 animate-pulse rounded bg-neutral-100" />
  if (state === 'not_scanned') return <p className="text-sm text-neutral-400">Impact analysis hasn't run for this repository yet.</p>
  if (state === 'error' || !data) return <p className="text-sm text-red-600">Could not load the impact.</p>

  const t = data.totals

  return (
    <div className="space-y-4 text-sm">
      {/* Repository summary */}
      <div>
        <p>
          <span className="font-medium">{t.changes}</span> change(s) across <span className="font-medium">{t.files_changed}</span> distinct file(s) by{' '}
          {t.work_items} work item(s) under their effective resolutions{t.client_changes > 0 && <>, {t.client_changes} of the changes as clients</>}.
        </p>
        <div className="mt-1 flex flex-wrap items-baseline gap-1.5">
          {(['rewrite', 'update', 'delete'] as ImpactAction[]).map((a) => (
            <ActionChip key={a} action={a} count={t.by_action[a]} />
          ))}
          <span className="text-xs text-neutral-500">
            · {t.new_files} new file(s){t.creates !== t.new_files && <> from {t.creates} creates</>} · {t.files_to_review} file(s) to review
            {t.review_marks !== t.files_to_review && <> ({t.review_marks} review marks)</>} · {t.hotspots} hotspot(s) ·{' '}
            {t.rule_conflicts} catalog rule conflict(s){t.rule_conflicts > 0 && <> affecting {t.rule_conflict_work_items} work items across the estate</>} · {t.work_item_conflicts}{' '}
            work-item conflict(s)
          </span>
        </div>
        {t.stale_work_items > 0 && (
          <p className="mt-1 text-xs text-amber-700">{t.stale_work_items} work item(s) stale: a decision changed after impact was computed. Rescan to recompute.</p>
        )}
        <p className="mt-1 text-[11px] text-neutral-400">{data.client_impact_note}</p>
      </div>

      {/* Hotspots and conflicts, Part G */}
      {(data.hotspots.length > 0 || data.rule_conflicts.length > 0 || data.work_item_conflicts.length > 0) && (
        <div className="grid gap-3 lg:grid-cols-2">
          <div>
            <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">Hotspots — three or more work items</h4>
            <LimitedList items={data.hotspots} name={(f) => f.file_key} noun="hotspots" empty={<p className="text-xs text-neutral-400">None.</p>}>
              {(visible) => (
                <ul className="space-y-1.5">
                  {visible.map((f) => (
                    <li key={f.file_key}>
                      <FileKey file={f} localPath={localPath} />
                      <FileWorkItems file={f} />
                    </li>
                  ))}
                </ul>
              )}
            </LimitedList>
          </div>
          <div>
            <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">Conflicts</h4>
            <Conflicts rules={data.rule_conflicts} workItems={data.work_item_conflicts} localPath={localPath} />
          </div>
        </div>
      )}

      {/* Work items */}
      <div>
        <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">Work items</h4>
        <LimitedList items={data.work_items} name={(w) => [w.item_name, w.project_path]} noun="work items">
          {(visibleWorkItems) => (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-neutral-500">
              <th className="py-1 pr-3 font-normal">Work item</th>
              <th className="py-1 pr-3 font-normal">Project</th>
              <th className="py-1 pr-3 font-normal">Computed resolutions</th>
              <th className="py-1 font-normal" />
            </tr>
          </thead>
          <tbody>
            {visibleWorkItems.map((w) => {
              const key = `${w.item_id}|${w.project_path}`
              const open = expanded === key
              return (
                <Fragment key={key}>
                  <tr className="border-t border-neutral-100 align-top">
                    <td className="py-1 pr-3 font-medium">{w.item_name}</td>
                    <td className="py-1 pr-3 font-mono text-neutral-500">{w.project_path}</td>
                    <td className="py-1 pr-3">
                      <LimitedList items={w.resolutions} name={(r) => r.name} noun="resolutions">
                        {(visibleResolutions) =>
                          visibleResolutions.map((r) => (
                        <div key={r.resolution_id}>
                          <span className={r.effective ? 'font-medium' : 'text-neutral-500'}>{r.name}</span>{' '}
                          <span className="text-neutral-400">({roleLabel(r.roles).toLowerCase()})</span>{' '}
                          <span className="font-mono">{r.changed}</span> changed
                          {r.created > 0 && <>, {r.created} new</>}
                          {r.to_review > 0 && <>, {r.to_review} to review</>}
                          {r.client_changed + r.client_review > 0 && (
                            <span className="text-violet-700">
                              {' '}
                              (client: {r.client_changed > 0 && <>{r.client_changed} changed</>}
                              {r.client_changed > 0 && r.client_review > 0 && ', '}
                              {r.client_review > 0 && <>{r.client_review} to review</>})
                            </span>
                          )}
                          {r.stale && <span className="ml-1 text-amber-700">stale</span>}
                        </div>
                          ))
                        }
                      </LimitedList>
                    </td>
                    <td className="py-1 text-right">
                      <button type="button" onClick={() => setExpanded(open ? null : key)} className="text-violet-700 hover:underline">
                        {open ? 'hide' : 'files'}
                      </button>
                    </td>
                  </tr>
                  {open && (
                    <tr>
                      <td colSpan={4} className="pb-3">
                        <WorkItemDetail repositoryId={repositoryId} workItem={w} localPath={localPath} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
          )}
        </LimitedList>
      </div>

      {/* Per-file view */}
      <div>
        <h4 className="mb-1 text-[11px] font-medium uppercase tracking-wide text-neutral-400">Files</h4>
        <LimitedList items={data.files} name={(f) => f.file_key} noun="files">
          {(visible) => (
            <ul className="divide-y divide-neutral-100">
              {visible.map((f) => (
                <li key={f.file_key} className="py-1">
                  <div className="flex flex-wrap items-baseline gap-1.5">
                    <FileKey file={f} localPath={localPath} />
                    {f.hotspot && <span className="text-[11px] text-amber-700">hotspot</span>}
                    {f.conflicts > 0 && <span className="text-[11px] text-red-700">{f.conflicts} conflict(s)</span>}
                  </div>
                  <FileWorkItems file={f} />
                </li>
              ))}
            </ul>
          )}
        </LimitedList>
      </div>
    </div>
  )
}
