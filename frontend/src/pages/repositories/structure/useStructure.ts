import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError } from '../../../api/client'
import { getHierarchy, getHierarchyChildren } from '../../../api/hierarchy'
import type { HierarchyOverview, HierarchySearchMatch, HierarchyView } from '../../../types/hierarchy'
import {
  CHILD_PAGE,
  addChildren,
  collapse,
  expand,
  initialState,
  needsLoad,
  pin,
  resetChildren,
  showMore,
  visibleGraph,
  wanted,
  type StructureState,
} from './structureModel'

export type LoadState = { kind: 'loading' } | { kind: 'not_scanned'; message: string } | { kind: 'error'; message: string } | { kind: 'ready' }

/**
 * The Dependency graph tab's state: the view (transitive packages, filter), the graph's roots, and every expanded node's
 * children — loaded from the backend when the node is expanded, a page at a time, never the whole graph.
 */
export function useStructure(repositoryId: string, refreshToken: number) {
  const [view, setView] = useState<HierarchyView>({ transitive: false, show: 'all' })
  const [overview, setOverview] = useState<HierarchyOverview | null>(null)
  const [load, setLoad] = useState<LoadState>({ kind: 'loading' })
  const [state, setState] = useState<StructureState>(() => initialState([]))
  // Answers for a view that has since changed are dropped.
  const generation = useRef(0)
  const inFlight = useRef(new Set<string>())

  useEffect(() => {
    const current = ++generation.current
    inFlight.current = new Set()
    getHierarchy(repositoryId, view)
      .then((result) => {
        if (current !== generation.current) return
        setOverview(result)
        setState((s) => resetChildren(s, result.roots))
        setLoad({ kind: 'ready' })
      })
      .catch((err) => {
        if (current !== generation.current) return
        if (err instanceof ApiError && err.status === 409) setLoad({ kind: 'not_scanned', message: err.message })
        else setLoad({ kind: 'error', message: err instanceof Error ? err.message : 'The dependency graph could not be loaded.' })
      })
  }, [repositoryId, view, refreshToken])

  useEffect(() => {
    const current = generation.current
    for (const id of state.expanded) {
      if (!needsLoad(state, id) || inFlight.current.has(id)) continue
      inFlight.current.add(id)
      const offset = state.children[id]?.items.length ?? 0
      const limit = Math.max(CHILD_PAGE, wanted(state, id) - offset)
      getHierarchyChildren(repositoryId, id, view, offset, limit)
        .then((page) => {
          if (current === generation.current) setState((s) => addChildren(s, id, page.total, page.items))
        })
        .catch(() => {
          if (current === generation.current) setState((s) => addChildren(s, id, 0, []))
        })
        .finally(() => inFlight.current.delete(id))
    }
  }, [state, view, repositoryId])

  const toggle = useCallback((nodeId: string) => setState((s) => (s.expanded.has(nodeId) ? collapse(s, nodeId) : expand(s, nodeId))), [])
  const more = useCallback((nodeId: string) => setState((s) => showMore(s, nodeId)), [])

  /** Expands every node on the match's path from its root, and pins each step under its parent, so the match shows
   * whatever page it is on. */
  const reveal = useCallback((match: HierarchySearchMatch) => {
    const path = match.path
    if (!path) return
    setState((s) => {
      let next = s
      for (let i = 1; i < path.length; i++) {
        const parent = path[i - 1].node.id
        next = pin(expand(next, parent), parent, { edge: path[i].edge!, node: path[i].node })
      }
      return next
    })
  }, [])

  const graph = useMemo(() => visibleGraph(state), [state])
  return { view, setView, overview, load, state, graph, toggle, more, reveal }
}
