import { useEffect, useState } from 'react'
import { getEngagementRuleConflicts, listCatalogRuleConflicts } from '../api/surface'
import { LimitedList } from '../components/LimitedList'
import type { EngagementRuleConflicts, MasterRuleConflict, RuleSide } from '../types/impact'

// Catalog rule conflicts — 33-IMPACT-ANALYSIS.md Part G, as implemented: a
// rule pair that conflicts on more than one pair of work items across the
// estate. For catalog authors to fix once, in the rules.

const KIND: Record<string, string> = { delete_with_change: 'delete with change', create_same_path: 'create at the same path' }

function Side({ side }: { side: RuleSide }) {
  return (
    <span>
      <span className="font-medium">{side.item_name}</span> · {side.resolution_name} · <span className="font-mono">{side.action}</span>
      <span className="font-mono text-[11px] text-neutral-400"> [{side.rule_ids.join(', ')}]</span>
    </span>
  )
}

/** What a person sees of a rule pair: its two items and their resolutions. */
function sideNames(r: { first: RuleSide; second: RuleSide }): string[] {
  return [r.first.item_name, r.first.resolution_name, r.second.item_name, r.second.resolution_name]
}

function plural(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`
}

/** The Estate tab's view: the engagement's rule conflicts, every instance by repository. */
export function EstateRuleConflictsView({ engagementId, onOpenRepository }: { engagementId: string; onOpenRepository: (repositoryId: string) => void }) {
  const [data, setData] = useState<EngagementRuleConflicts | null>(null)
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getEngagementRuleConflicts(engagementId)
      .then((result) => !cancelled && setData(result))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [engagementId])

  if (failed) return <p className="text-sm text-red-600">Could not load the rule conflicts.</p>
  if (!data) return <div className="h-16 animate-pulse rounded bg-neutral-100" />
  return (
    <div className="space-y-3 rounded border border-neutral-200 bg-white p-4 text-sm">
      <p className="text-xs text-neutral-500">{data.note}</p>
      <LimitedList
        items={data.rule_conflicts}
        name={sideNames}
        noun="rule conflicts"
        empty={<p className="text-neutral-400">No catalog rule conflicts in this estate.</p>}
      >
        {(visible) => (
        <ul className="divide-y divide-neutral-100">
          {visible.map((r) => (
            <li key={r.rule_key} className="py-2">
              <p>
                <span className="text-red-700">
                  1 rule conflict affecting {plural(r.work_items, 'work item', 'work items')} across {plural(r.repositories, 'repository', 'repositories')}
                </span>
                <span className="text-xs text-neutral-500"> · {KIND[r.kind]}</span>
              </p>
              <ul className="ml-3 text-xs">
                <li>
                  <Side side={r.first} />
                </li>
                <li>
                  <Side side={r.second} />
                </li>
              </ul>
              <button type="button" onClick={() => setOpen(open === r.rule_key ? null : r.rule_key)} className="ml-3 text-xs text-violet-700 hover:underline">
                {open === r.rule_key ? 'hide instances' : `${r.instances.length} instance(s)`}
              </button>
              {open === r.rule_key && (
                <LimitedList items={r.instances} name={(i) => [i.repository_slug ?? i.repository_id, i.file_key]} noun="instances" className="ml-3">
                  {(visibleInstances) => (
                <ul className="text-xs">
                  {visibleInstances.map((i) => (
                    <li key={`${i.repository_id}:${i.file_key}:${i.first_project_path}:${i.second_project_path}`}>
                      <button type="button" onClick={() => onOpenRepository(i.repository_id)} className="text-violet-700 hover:underline">
                        {i.repository_slug ?? i.repository_id}
                      </button>{' '}
                      <span className="font-mono">{i.file_key}</span>
                    </li>
                  ))}
                </ul>
                  )}
                </LimitedList>
              )}
            </li>
          ))}
        </ul>
        )}
      </LimitedList>
    </div>
  )
}

/** The master catalog's view: each rule pair with the engagements whose
 * estates show it. Counts only; the files are each engagement's own data. */
export function MasterRuleConflictsView({ onSelectItem }: { onSelectItem: (itemId: string) => void }) {
  // Per-engagement counts: everyone signed in sees every engagement (app.auth.policy).
  const [data, setData] = useState<MasterRuleConflict[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    listCatalogRuleConflicts()
      .then((result) => !cancelled && setData(result))
      .catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [])

  if (failed) return <p className="p-4 text-sm text-red-600">Could not load the rule conflicts.</p>
  if (!data) return <div className="m-4 h-16 animate-pulse rounded bg-neutral-100" />
  return (
    <div className="space-y-3 p-4 text-sm">
      <div>
        <h2 className="text-base font-semibold text-neutral-900">Catalog rule conflicts</h2>
        <p className="text-xs text-neutral-500">
          Impact rules from two items that conflict on the same file wherever both appear, across each engagement&apos;s estate as of its last estate run.
          Fix the rules once; every instance goes away on the next scan.
        </p>
      </div>
      <LimitedList
        items={data}
        name={sideNames}
        noun="rule conflicts"
        empty={<p className="text-neutral-400">No catalog rule conflicts in any engagement.</p>}
      >
        {(visible) => (
        <ul className="divide-y divide-neutral-100 rounded border border-neutral-200 bg-white">
          {visible.map((r) => (
            <li key={r.rule_key} className="p-3">
              <p>
                <span className="text-red-700">
                  1 rule conflict affecting {plural(r.work_items, 'work item', 'work items')} across {plural(r.repositories, 'repository', 'repositories')}
                </span>
                <span className="text-xs text-neutral-500"> · {KIND[r.kind]}</span>
              </p>
              <ul className="ml-3 text-xs">
                {[r.first, r.second].map((side) => (
                  <li key={`${side.item_id}:${side.resolution_id}`}>
                    <button type="button" onClick={() => onSelectItem(side.item_id)} className="text-violet-700 hover:underline">
                      {side.item_name}
                    </button>{' '}
                    · {side.resolution_name} · <span className="font-mono">{side.action}</span>
                    <span className="font-mono text-[11px] text-neutral-400"> [{side.rule_ids.join(', ')}]</span>
                  </li>
                ))}
              </ul>
              <p className="ml-3 text-xs text-neutral-500">
                {r.engagements.map((e) => `${e.client_name}: ${plural(e.work_items, 'work item', 'work items')} in ${plural(e.repositories, 'repository', 'repositories')}`).join(' · ')}
              </p>
            </li>
          ))}
        </ul>
        )}
      </LimitedList>
    </div>
  )
}
