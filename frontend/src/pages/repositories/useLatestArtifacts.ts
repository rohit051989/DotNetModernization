import { useEffect, useState } from 'react'
import { listRepositoryExecutions } from '../../api/repositories'
import { getArtifactContent, listExecutionArtifacts } from '../../api/workflow'
import type { Json } from '../workflow/artifacts/adapters'

/** The artifact types the repository page reads. */
export const PAGE_ARTIFACT_TYPES = [
  'solution-project-inventory',
  'application-fingerprint',
  'entry-point-inventory',
  'outbound-invocation-inventory',
  'dependency-assessment',
  'item-occurrences',
] as const

export type PageArtifactType = (typeof PAGE_ARTIFACT_TYPES)[number]

export interface LatestArtifact {
  data: Json
  executionId: string
  createdAt: string
}

/** How many executions back to look for a type a recent run did not produce
 * (a run that failed at step 3 still has step 2's inventory). */
const LOOKBACK = 5

/**
 * The newest copy of each artifact type, across the repository's recent
 * executions — what the repository page's fingerprint summary, work list
 * and summary tiles draw. Read from the artifacts themselves, through the
 * same renderers as an execution's timeline.
 */
export function useLatestArtifacts(repositoryId: string, refreshToken: number) {
  const [artifacts, setArtifacts] = useState<Partial<Record<PageArtifactType, LatestArtifact>>>({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const executions = (await listRepositoryExecutions(repositoryId))
          .slice()
          .sort((a, b) => (b.started_at ?? '').localeCompare(a.started_at ?? ''))
          .slice(0, LOOKBACK)
        const found: Partial<Record<PageArtifactType, { id: string; executionId: string; createdAt: string }>> = {}
        for (const execution of executions) {
          if (PAGE_ARTIFACT_TYPES.every((type) => found[type])) break
          const list = await listExecutionArtifacts(execution.id)
          for (const artifact of list) {
            const type = artifact.artifact_type as PageArtifactType
            if (PAGE_ARTIFACT_TYPES.includes(type) && !found[type]) {
              found[type] = { id: artifact.id, executionId: execution.id, createdAt: artifact.created_at }
            }
          }
        }
        const entries = await Promise.all(
          Object.entries(found).map(async ([type, ref]) => {
            try {
              const data = (await getArtifactContent(ref.id)) as Json
              return [type, { data, executionId: ref.executionId, createdAt: ref.createdAt }] as const
            } catch {
              return null
            }
          }),
        )
        if (!cancelled) setArtifacts(Object.fromEntries(entries.filter((e) => e !== null)))
      } catch {
        if (!cancelled) setArtifacts({})
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  return { artifacts, loading }
}
