import { useEffect, useMemo, useRef } from 'react'
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { HierarchyNode } from '../../../types/hierarchy'
import { NodeBadges } from './NodeBadges'
import { MORE_HEIGHT, MORE_WIDTH, NODE_HEIGHT, NODE_WIDTH, layout, moreId } from './layout'
import { CYCLE_STROKE, EDGE_STYLES, LOOKS, lookOf, subtitle } from './nodeStyle'
import type { VisibleGraph } from './structureModel'

interface GraphProps {
  graph: VisibleGraph
  expanded: ReadonlySet<string>
  selectedId: string | null
  /** A node a search revealed: centred and outlined. */
  focusId: string | null
  onToggle: (nodeId: string) => void
  onMore: (nodeId: string) => void
  onSelect: (nodeId: string) => void
}

type HierarchyFlowNode = Node<
  { node: HierarchyNode; expanded: boolean; selected: boolean; focused: boolean; onToggle: (id: string) => void; onSelect: (id: string) => void },
  'hierarchy'
>
type MoreFlowNode = Node<{ parentId: string; hidden: number; onMore: (id: string) => void }, 'more'>

/** One node: its kind's colours, name, subtitle (framework or version), badges, and + / − for its children. Clicking
 * the node opens its details; only + and − expand and collapse, and nothing happens on a double click. */
function HierarchyNodeView({ data }: NodeProps<HierarchyFlowNode>) {
  const { node, expanded, selected, focused, onToggle, onSelect } = data
  const look = LOOKS[lookOf(node)]
  return (
    <div
      onClick={() => onSelect(node.id)}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
      className={`flex cursor-pointer flex-col justify-between overflow-hidden rounded border-2 px-2 py-1 shadow-sm ${look.box} ${
        focused ? 'ring-4 ring-amber-300' : selected ? 'ring-2 ring-violet-400' : ''
      }`}
      data-testid={`graph-node-${node.id}`}
    >
      <Handle type="target" position={Position.Top} className="!h-1 !min-h-0 !w-1 !min-w-0 !border-0 !bg-transparent" />
      <div className="flex items-start gap-1">
        <span className={`mt-0.5 shrink-0 rounded px-1 text-[9px] font-semibold uppercase leading-3 ${look.tag}`}>{look.label.split(' ')[0]}</span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-semibold text-neutral-900" title={node.name}>
            {node.name}
          </div>
          <div className="truncate text-[10px] text-neutral-500">{subtitle(node)}</div>
        </div>
        {(node.child_count > 0 || expanded) && (
          <button
            type="button"
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${node.name}`}
            title={expanded ? 'Hide its children' : `Show its ${node.child_count} children`}
            onClick={(event) => {
              event.stopPropagation()
              onToggle(node.id)
            }}
            onDoubleClick={(event) => event.stopPropagation()}
            className="nodrag h-5 w-5 shrink-0 rounded border border-neutral-300 bg-white text-xs font-bold leading-4 text-neutral-700 hover:bg-neutral-100"
          >
            {expanded ? '−' : '+'}
          </button>
        )}
      </div>
      <NodeBadges node={node} compact />
      <Handle type="source" position={Position.Bottom} className="!h-1 !min-h-0 !w-1 !min-w-0 !border-0 !bg-transparent" />
    </div>
  )
}

function MoreNodeView({ data }: NodeProps<MoreFlowNode>) {
  return (
    <div style={{ width: MORE_WIDTH, height: MORE_HEIGHT }} className="flex items-center justify-center">
      <Handle type="target" position={Position.Top} className="!h-1 !min-h-0 !w-1 !min-w-0 !border-0 !bg-transparent" />
      <button
        type="button"
        onClick={() => data.onMore(data.parentId)}
        className="nodrag rounded-full border border-dashed border-neutral-400 bg-white px-3 py-1 text-xs text-violet-700 hover:bg-violet-50"
      >
        +{data.hidden} more
      </button>
    </div>
  )
}

const NODE_TYPES = { hierarchy: HierarchyNodeView, more: MoreNodeView }

function Graph({ graph, expanded, selectedId, focusId, onToggle, onMore, onSelect }: GraphProps) {
  const placed = useMemo(() => layout(graph), [graph])
  const flow = useReactFlow()

  const nodes = useMemo<(HierarchyFlowNode | MoreFlowNode)[]>(() => {
    const out: (HierarchyFlowNode | MoreFlowNode)[] = graph.nodes.map((node) => ({
      id: node.id,
      type: 'hierarchy',
      position: placed.get(node.id) ?? { x: 0, y: 0 },
      data: { node, expanded: expanded.has(node.id), selected: node.id === selectedId, focused: node.id === focusId, onToggle, onSelect },
      draggable: false,
      connectable: false,
    }))
    for (const [parentId, hidden] of Object.entries(graph.more)) {
      out.push({
        id: moreId(parentId),
        type: 'more',
        position: placed.get(moreId(parentId)) ?? { x: 0, y: 0 },
        data: { parentId, hidden, onMore },
        draggable: false,
        connectable: false,
        selectable: false,
      })
    }
    return out
  }, [graph, placed, expanded, selectedId, focusId, onToggle, onMore, onSelect])

  const edges = useMemo<Edge[]>(() => {
    const out: Edge[] = graph.edges.map(({ id, edge }) => {
      const style = EDGE_STYLES[edge.kind]
      const stroke = edge.closes_cycle ? CYCLE_STROKE : style.stroke
      return {
        id,
        source: edge.from_node,
        target: edge.to_node,
        style: { stroke, strokeDasharray: style.dash, strokeWidth: edge.kind === 'project_reference' ? 1.6 : 1.1 },
        markerEnd: { type: MarkerType.ArrowClosed, color: stroke, width: 14, height: 14 },
        selectable: false,
      }
    })
    for (const parentId of Object.keys(graph.more)) {
      out.push({ id: `${moreId(parentId)}:edge`, source: parentId, target: moreId(parentId), style: { stroke: '#a3a3a3', strokeDasharray: '1 3' }, selectable: false })
    }
    return out
  }, [graph])

  // After a node is expanded and its children are laid out, bring the node and its children into view.
  const previous = useRef<ReadonlySet<string>>(expanded)
  useEffect(() => {
    const opened = [...expanded].filter((id) => !previous.current.has(id))
    const children = graph.edges.filter(({ edge }) => opened.includes(edge.from_node)).map(({ edge }) => edge.to_node)
    if (opened.length === 0 || children.length === 0) return
    previous.current = expanded
    const ids = [...opened, ...children, ...opened.filter((id) => graph.more[id]).map(moreId)]
    requestAnimationFrame(() => void flow.fitView({ nodes: ids.map((id) => ({ id })), maxZoom: 1, padding: 0.2, duration: 300 }))
  }, [expanded, graph, flow])
  useEffect(() => {
    if (expanded.size < previous.current.size) previous.current = expanded         // a collapse: nothing to bring into view
  }, [expanded])

  useEffect(() => {
    if (!focusId) return
    const at = placed.get(focusId)
    if (at) flow.setCenter(at.x + NODE_WIDTH / 2, at.y + NODE_HEIGHT / 2, { zoom: 1, duration: 300 })
  }, [focusId, placed, flow])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={NODE_TYPES}
      fitView
      fitViewOptions={{ maxZoom: 1, padding: 0.15 }}
      minZoom={0.1}
      nodesDraggable={false}
      nodesConnectable={false}
      zoomOnDoubleClick={false}
      onlyRenderVisibleElements
    >
      <Background gap={20} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  )
}

/** The node-link view (React Flow, laid out top to bottom by dagre). It opens showing only the roots. */
export function StructureGraph(props: GraphProps) {
  return (
    <div className="h-[620px] min-w-0 rounded border border-neutral-200 bg-neutral-50" data-testid="structure-graph">
      <ReactFlowProvider>
        <Graph {...props} />
      </ReactFlowProvider>
    </div>
  )
}
