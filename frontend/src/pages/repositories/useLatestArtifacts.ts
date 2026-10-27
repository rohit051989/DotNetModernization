import { useEffect, useState } from 'react'
import { getRepositoryResults } from '../../api/results'
import type { RepositoryResults } from '../../types/results'
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
  artifactId: string
  /** The artifact without its lists — its summary, counts and versions. The lists come a page at a time. */
  data: Json
  executionId: string
  createdAt: string
}

/**
 * The newest stored copy of each artifact type (backend app.results): what the repository page's summary tiles, tab
 * labels and each view's header read. From the database, so the same on every machine, whoever scanned the
 * repository; each view asks for its own lists.
 */
export function useLatestArtifacts(repositoryId: string, refreshToken: number) {
  const [artifacts, setArtifacts] = useState<Partial<Record<PageArtifactType, LatestArtifact>>>({})
  const [results, setResults] = useState<RepositoryResults | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getRepositoryResults(repositoryId)
      .then((found) => {
        if (cancelled) return
        setResults(found)
        const latest: Partial<Record<PageArtifactType, LatestArtifact>> = {}
        for (const type of PAGE_ARTIFACT_TYPES) {
          const stored = found.results[type]
          if (stored) latest[type] = { artifactId: stored.artifact_id, data: stored.head, executionId: stored.job_execution_id, createdAt: stored.created_at }
        }
        setArtifacts(latest)
      })
      .catch(() => {
        if (!cancelled) {
          setArtifacts({})
          setResults(null)
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [repositoryId, refreshToken])

  return { artifacts, results, loading }
}
