import type { HierarchyEdgeKind, HierarchyNode } from '../../../types/hierarchy'

/** The visual kinds the legend lists: each kind of project, internal and external package, assembly reference. */
export type NodeLook = 'application' | 'library' | 'test' | 'other' | 'internal' | 'external' | 'unknown' | 'assembly'

export function lookOf(node: HierarchyNode): NodeLook {
  if (node.type === 'project') return node.kind ?? 'other'
  if (node.type === 'package') return node.origin === 'internal' ? 'internal' : node.origin === 'external' ? 'external' : 'unknown'
  return 'assembly'
}

/** Border, fill and text classes, and a short label, per kind. Assembly references are dashed: no package declares them. */
export const LOOKS: Record<NodeLook, { label: string; box: string; tag: string }> = {
  application: { label: 'Application', box: 'border-violet-500 bg-violet-50', tag: 'bg-violet-600 text-white' },
  library: { label: 'Library', box: 'border-sky-500 bg-sky-50', tag: 'bg-sky-600 text-white' },
  test: { label: 'Test project', box: 'border-emerald-500 bg-emerald-50', tag: 'bg-emerald-600 text-white' },
  other: { label: 'Other project', box: 'border-neutral-400 bg-neutral-50', tag: 'bg-neutral-500 text-white' },
  internal: { label: 'Internal package', box: 'border-amber-500 bg-amber-50 rounded-xl', tag: 'bg-amber-500 text-white' },
  external: { label: 'External package', box: 'border-slate-400 bg-white rounded-xl', tag: 'bg-slate-500 text-white' },
  unknown: { label: 'Package, origin unknown', box: 'border-slate-300 bg-slate-50 rounded-xl', tag: 'bg-slate-400 text-white' },
  assembly: { label: 'Assembly reference', box: 'border-stone-400 border-dashed bg-stone-50', tag: 'bg-stone-500 text-white' },
}

export const LEGEND_LOOKS: NodeLook[] = ['application', 'library', 'test', 'other', 'internal', 'external', 'assembly']

/** Edge styles per kind: colour, dash pattern and the legend's words. A cycle-closing edge is drawn red whatever its kind. */
export const EDGE_STYLES: Record<HierarchyEdgeKind, { label: string; stroke: string; dash?: string }> = {
  project_reference: { label: 'ProjectReference', stroke: '#6d28d9' },
  package_reference: { label: 'PackageReference', stroke: '#475569' },
  central_package_version: { label: 'PackageReference, central version', stroke: '#475569', dash: '2 3' },
  packages_config: { label: 'packages.config', stroke: '#b45309', dash: '7 4' },
  assembly_reference: { label: 'Assembly reference', stroke: '#78716c', dash: '9 3 2 3' },
  package_dependency: { label: 'Package dependency (transitive)', stroke: '#94a3b8', dash: '3 3' },
}

export const CYCLE_STROKE = '#dc2626'

/** One line under the name: what the node is, in words. */
export function subtitle(node: HierarchyNode): string {
  if (node.type === 'project') return [LOOKS[lookOf(node)].label, node.target_frameworks[0]].filter(Boolean).join(' · ')
  if (node.type === 'package') return [node.version ?? 'version unknown', node.transitive ? 'transitive' : null].filter(Boolean).join(' · ')
  const where = { repository: 'DLL in the repository', outside_repository: 'DLL outside the repository', gac: 'GAC', framework: '.NET Framework' }
  return [node.version, node.location ? where[node.location] : null].filter(Boolean).join(' · ')
}
