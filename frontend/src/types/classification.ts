// Read-only shapes returned by lifecycle step 4's (pattern-classification)
// API — see 24-STEP-004-CLASSIFICATION.md Part I.

export type ClassificationStatus =
  | 'SKIPPED'
  | 'NOT_ELIGIBLE'
  | 'INSUFFICIENT_FINGERPRINT'
  | 'AMBIGUOUS'
  | 'MULTIPLE_MATCHES'
  | 'MATCHED'
  | 'NO_PATTERN_MATCHED'
  | 'CLASSIFICATION_FAILED'

export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'VERY_LOW'

export interface ClassificationSummary {
  repository_id: string
  evaluated: number
  matched: number
  multiple_matches: number
  ambiguous: number
  no_pattern_matched: number
  insufficient_fingerprint: number
  not_eligible: number
  skipped: number
  classification_failed: number
}

export interface ClassificationListItem {
  project_id: string
  project_path: string
  project_role: string | null
  primary_pattern_id: string | null
  primary_pattern_name: string | null
  confidence_level: ConfidenceLevel | null
  classification_status: ClassificationStatus
  classified_at: string
}

export interface RuleEvidence {
  source_path: string | null
  value: string | null
  extraction_confidence: number
}

export interface MatchedRule {
  rule_id: string
  signal_name?: string
  field?: string
  actual?: unknown
  actual_occurrences?: number
  required_occurrences?: number | null
  weight?: number
  evidence?: RuleEvidence[]
}

export interface ClassificationMatch {
  pattern_id: string
  pattern_name: string
  pattern_version: number
  classification_role: 'PRIMARY' | 'SECONDARY' | 'PROJECT_ROLE'
  classification_family: string | null
  classification_value: string | null
  matched: boolean
  match_score: number
  confidence: number
  confidence_level: ConfidenceLevel
  is_primary_selected: boolean
  rejection_reason: string | null
  matched_rules: MatchedRule[]
  failed_rules: MatchedRule[]
  missing_preferred: MatchedRule[]
  negative_triggered: MatchedRule[]
  explanation: string | null
}

export interface ProjectClassificationDetail {
  project_id: string
  project_path: string
  repository_id: string
  classification_status: ClassificationStatus
  project_role: string | null
  project_role_confidence: number | null
  catalog_revision: number
  signal_registry_version: string | null
  config_version: string
  evaluated_pattern_count: number
  primary_pattern_id: string | null
  matches: ClassificationMatch[]
  near_misses: ClassificationMatch[]
  warnings: { code: string; severity: string; message: string }[]
  classified_at: string
}

export interface PatternCount {
  pattern_id: string
  pattern_name: string
  count: number
}

export interface PatternDistribution {
  engagement_id: string
  projects_evaluated: number
  primary_pattern_distribution: PatternCount[]
  secondary_capability_distribution: PatternCount[]
  confidence_distribution: Record<string, number>
  pattern_match_rate: number
  pattern_ambiguity_rate: number
}

export interface UnmatchedSignalCombination {
  anchor_signals: string[]
  count: number
}

export interface NeverEmittedSignalFinding {
  pattern_id: string
  name: string
  never_emitted_signals: string[]
}

export interface CatalogCoverage {
  engagement_id: string
  repositories_included: number
  catalog_version: string
  signal_registry_version: string | null
  registered_signal_count: number
  referenced_signal_count: number
  unreferenced_signal_count: number
  active_pattern_count: number
  evaluated_pattern_count: number
  matched_pattern_count: number
  never_matched_pattern_ids: string[]
  patterns_awaiting_signals_by_extractor: Record<string, string[]>
  most_frequent_unmatched_signal_combinations: UnmatchedSignalCombination[]
  rule_references_never_emitted_signal: NeverEmittedSignalFinding[]
}

export interface PendingSignalPromotion {
  pattern_id: string
  name: string
  required_signals_pending: {
    signal_name: string
    purpose: string
    expected_extractor: string
    blocking: boolean
  }[]
  still_missing_blocking: string[]
  promotable: boolean
}
