import type { ComponentType } from 'react'
import {
  DependenciesView,
  EntryPointsView,
  FingerprintView,
  ItemOccurrencesView,
  OutboundView,
  RepositoryInventoryView,
  SolutionInventoryView,
  type ArtifactRendererProps,
} from './renderers'

/**
 * Readable views of artifacts, keyed by artifact_type. A step that produces
 * a new artifact type adds one line here; the timeline, the artifact drawer
 * and the repository page pick it up without changing. A type with no
 * entry is shown as JSON.
 */
const RENDERERS: Record<string, ComponentType<ArtifactRendererProps>> = {
  'repository-inventory': RepositoryInventoryView,
  'solution-project-inventory': SolutionInventoryView,
  'application-fingerprint': FingerprintView,
  'entry-point-inventory': EntryPointsView,
  'outbound-invocation-inventory': OutboundView,
  'dependency-assessment': DependenciesView,
  'item-occurrences': ItemOccurrencesView,
}

export function rendererFor(artifactType: string): ComponentType<ArtifactRendererProps> | null {
  return RENDERERS[artifactType] ?? null
}
