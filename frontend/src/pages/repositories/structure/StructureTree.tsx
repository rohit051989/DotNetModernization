import type { HierarchyChild, HierarchyNode } from '../../../types/hierarchy'
import { NodeBadges } from './NodeBadges'
import { EDGE_STYLES, LOOKS, lookOf, subtitle } from './nodeStyle'
import { wanted, type StructureState } from './structureModel'

interface TreeProps {
  state: StructureState
  selectedId: string | null
  focusId: string | null
  onToggle: (nodeId: string) => void
  onMore: (nodeId: string) => void
  onSelect: (nodeId: string) => void
}

/**
 * The indented tree: the same graph, the same + and −, for a repository too large to look at as a picture. A tree
 * repeats a shared node under each parent that is expanded ("referenced by N" says it is shared); an edge back to a
 * node already above it on the branch is shown and not followed.
 */
export function StructureTree(props: TreeProps) {
  return (
    <div className="max-h-[620px] overflow-auto rounded border border-neutral-200 bg-white py-1" role="tree" aria-label="Dependency tree">
      {props.state.roots.map((root) => (
        <Row key={root.id} {...props} node={root} via={null} depth={0} ancestors={[]} />
      ))}
    </div>
  )
}

function Row(props: TreeProps & { node: HierarchyNode; via: HierarchyChild['edge'] | null; depth: number; ancestors: string[] }) {
  const { state, node, via, depth, ancestors, selectedId, focusId, onToggle, onMore, onSelect } = props
  const cycle = ancestors.includes(node.id)
  const expanded = !cycle && state.expanded.has(node.id)
  const loaded = state.children[node.id]
  const shown = loaded ? loaded.items.slice(0, wanted(state, node.id)) : []
  const shownIds = new Set(shown.map((c) => c.node.id))
  const children = [...shown, ...(state.pinned[node.id] ?? []).filter((p) => !shownIds.has(p.node.id))]
  const hidden = loaded ? loaded.total - shown.length : 0
  const look = LOOKS[lookOf(node)]

  return (
    <div role="treeitem" aria-expanded={node.child_count > 0 ? expanded : undefined} aria-label={node.name}>
      <div
        className={`flex items-center gap-1.5 py-0.5 pr-2 text-xs ${node.id === focusId ? 'bg-amber-100' : node.id === selectedId ? 'bg-violet-50' : 'hover:bg-neutral-50'}`}
        style={{ paddingLeft: 8 + depth * 18 }}
      >
        {node.child_count > 0 && !cycle ? (
          <button
            type="button"
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${node.name}`}
            onClick={() => onToggle(node.id)}
            className="h-4 w-4 shrink-0 rounded border border-neutral-300 bg-white text-[11px] font-bold leading-3 text-neutral-700 hover:bg-neutral-100"
          >
            {expanded ? '−' : '+'}
          </button>
        ) : (
          <span className="w-4 shrink-0" />
        )}
        <span className={`h-2.5 w-2.5 shrink-0 rounded-sm border-2 ${look.box}`} title={look.label} />
        <button type="button" onClick={() => onSelect(node.id)} className="min-w-0 truncate text-left font-medium text-neutral-900 hover:underline" title={node.name}>
          {node.name}
        </button>
        <span className="shrink-0 text-[10px] text-neutral-500">{subtitle(node)}</span>
        {via && via.kind !== 'project_reference' && <span className="shrink-0 text-[10px] text-neutral-400">via {EDGE_STYLES[via.kind].label}</span>}
        {cycle && <span className="shrink-0 rounded bg-red-100 px-1 text-[10px] text-red-700">cycle: already above on this branch</span>}
        <NodeBadges node={node} compact />
      </div>
      {expanded && (
        <div role="group">
          {!loaded && <div className="py-0.5 text-[11px] text-neutral-400" style={{ paddingLeft: 30 + depth * 18 }}>Loading…</div>}
          {children.map((child) => (
            <Row key={`${child.edge.kind}|${child.node.id}`} {...props} node={child.node} via={child.edge} depth={depth + 1} ancestors={[...ancestors, node.id]} />
          ))}
          {hidden > 0 && (
            <div style={{ paddingLeft: 30 + depth * 18 }} className="py-0.5">
              <button type="button" onClick={() => onMore(node.id)} className="text-[11px] text-violet-700 hover:underline">
                +{hidden} more
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
