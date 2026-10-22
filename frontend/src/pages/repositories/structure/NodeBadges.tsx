import type { HierarchyNode } from '../../../types/hierarchy'

/** A node's badges: legacy-style, not checked, discovery's findings (vulnerable, outdated, deprecated, work items),
 * and "referenced by N" when more than one node depends on it. The target framework is in the node's subtitle. */
export function NodeBadges({ node, compact = false }: { node: HierarchyNode; compact?: boolean }) {
  const f = node.findings
  const badge = 'whitespace-nowrap rounded px-1 text-[10px] font-medium leading-4'
  return (
    <span className={`flex ${compact ? 'flex-nowrap overflow-hidden' : 'flex-wrap'} items-center gap-1`}>
      {node.legacy && <span className={`${badge} bg-neutral-200 text-neutral-700`} title="A legacy (non-SDK-style) project file">legacy</span>}
      {node.status === 'not_checked' && (
        <span className={`${badge} bg-neutral-700 text-white`} title={node.not_checked_reason ?? undefined}>
          not checked
        </span>
      )}
      {f.vulnerable && (
        <span className={`${badge} bg-red-600 text-white`} title="Known advisories for this version">
          vulnerable{f.vulnerability_max_severity ? ` · ${f.vulnerability_max_severity}` : ''}
        </span>
      )}
      {f.outdated && <span className={`${badge} bg-amber-200 text-amber-900`} title="dependency-assessment recommends a newer version">outdated</span>}
      {f.deprecated && <span className={`${badge} bg-orange-200 text-orange-900`}>deprecated</span>}
      {node.work_items > 0 && (
        <span className={`${badge} bg-violet-100 text-violet-800`} title="Work items item-detection found">
          {node.work_items} work item{node.work_items === 1 ? '' : 's'}
        </span>
      )}
      {node.referenced_by > 1 && (
        <span className={`${badge} bg-white text-neutral-600 ring-1 ring-neutral-300`} title="How many nodes depend on it">
          referenced by {node.referenced_by}
        </span>
      )}
    </span>
  )
}
