/** Step 5 output — see docs/26-STEP-005-PATTERN-DISCOVERY.md. */

export type NarrationStatus = 'succeeded' | 'partial' | 'failed' | 'disabled'

export interface ClusterMember {
  project_id: string
  project_path: string
  repository_name: string
  classification_status: string
  similarity_to_signature: number | null
  signal_count: number
}

export interface SimilarPattern {
  pattern_id: string
  similarity: number
}

export interface PatternCandidate {
  cluster_id: string
  cluster_method: 'exact' | 'similarity'
  canonical_signature: { facets: Record<string, string | null>; signals: string[] }
  signal_count: number
  member_count: number
  repository_count: number
  repository_distribution: Record<string, number>
  cohesion: number | null
  is_singleton: boolean
  is_stale: boolean
  similar_patterns: SimilarPattern[] | null
  status: string
  resolved_pattern_id: string | null
  resolution_note: string | null
  needs_rereview: boolean
  rereview_reason: string | null
  /** Advisory only (Part E). Null throughout when narration was unavailable
   * or disabled — which is what `narration.status` on the response explains. */
  suggested_name: string | null
  suggested_description: string | null
  suggested_pattern_id: string | null
  narration_confidence: string | null
  naming_source: 'claude-code' | 'human' | 'none'
  members: ClusterMember[]
}

export interface NarrationStatusInfo {
  status: NarrationStatus
  reason: string | null
  narrated_cluster_count: number
  cluster_count: number
  run_at: string | null
  retryable: boolean
}

export interface PatternCandidatesResponse {
  engagement_id: string
  coverage_ratio: number | null
  partial_estate: boolean
  narration: NarrationStatusInfo | null
  clusters: PatternCandidate[]
}

export interface RetryNarrationResult {
  narration_status: NarrationStatus
  narration_reason: string | null
  narrated_count: number
  cluster_count: number
}
