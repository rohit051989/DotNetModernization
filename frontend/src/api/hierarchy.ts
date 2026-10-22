import { api } from './client'
import type { HierarchyChildren, HierarchyNodeDetail, HierarchyOverview, HierarchySearch, HierarchyView } from '../types/hierarchy'

function base(repositoryId: string) {
  return `/api/repositories/${encodeURIComponent(repositoryId)}/hierarchy`
}

function viewQuery(view: HierarchyView) {
  return `transitive=${view.transitive}&show=${view.show}`
}

/** The graph's summary and its roots. 409 until dependency-hierarchy has run for the repository. */
export function getHierarchy(repositoryId: string, view: HierarchyView) {
  return api.get<HierarchyOverview>(`${base(repositoryId)}?${viewQuery(view)}`)
}

/** One page of a node's children under the view. */
export function getHierarchyChildren(repositoryId: string, nodeId: string, view: HierarchyView, offset = 0, limit = 20) {
  return api.get<HierarchyChildren>(
    `${base(repositoryId)}/children?node=${encodeURIComponent(nodeId)}&${viewQuery(view)}&offset=${offset}&limit=${limit}`,
  )
}

/** Nodes whose name contains the query, each with a shortest path from a root under the view. */
export function searchHierarchy(repositoryId: string, query: string, view: HierarchyView) {
  return api.get<HierarchySearch>(`${base(repositoryId)}/search?q=${encodeURIComponent(query)}&${viewQuery(view)}`)
}

/** One node's details: its parents and work items. */
export function getHierarchyNode(repositoryId: string, nodeId: string, view: HierarchyView) {
  return api.get<HierarchyNodeDetail>(`${base(repositoryId)}/node?node=${encodeURIComponent(nodeId)}&${viewQuery(view)}`)
}
