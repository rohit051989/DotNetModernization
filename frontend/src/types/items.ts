// Item catalog — 28-ITEM-AND-CONVERSION-MODEL.md Parts C to H.
// Mirrors backend/app/items/schemas.py and the detection grammar in
// backend/app/items/detection.py. `state` / `state_reason` are computed by the
// API and only ever appear on responses — never send them.

import type { ConsumerImpact, EffortLevel, ForcingPerspective } from './catalog'

export type ItemScope = 'application' | 'occurrence'
export type ReadinessState = 'ready' | 'not_ready'
export type ItemStatus = 'active' | 'deprecated'
export type ExtractorStatus = 'implemented' | 'planned'
export type ProjectRole = 'TEST' | 'DEPLOYMENT' | 'DATABASE' | 'APPLICATION' | 'LIBRARY' | 'UNKNOWN'
export type ItemReasonCode = 'signal_mapping_pending' | 'signal_not_ready'
export type BlockingReasonCode = 'extractor_not_implemented' | 'signal_not_registered'
export type EngagementDecisionStatus = 'pending' | 'in_review' | 'approved' | 'superseded'
export type EditableDecisionStatus = Exclude<EngagementDecisionStatus, 'superseded'>
export type OccurrenceGroupBy = 'source_path' | 'source_path_and_value'

export const ITEM_CATEGORIES = [
  'hosting',
  'logging',
  'configuration',
  'security',
  'data-access',
  'integration',
  'packaging',
  'dependencies',
  'framework',
] as const
export type ItemCategory = (typeof ITEM_CATEGORIES)[number]

export const PROJECT_ROLES: ProjectRole[] = ['TEST', 'DEPLOYMENT', 'DATABASE', 'APPLICATION', 'LIBRARY', 'UNKNOWN']

export const FORCING_PERSPECTIVES: ForcingPerspective[] = [
  'SECURITY',
  'EVOLUTION',
  'REGULATION',
  'PERFORMANCE_SCALABILITY',
  'AVAILABILITY_RESILIENCE',
  'LOCATION',
  'DEVELOPMENT_RESOURCE',
]

export const CONSUMER_IMPACT_RANK: Record<ConsumerImpact, number> = { none: 0, low: 1, medium: 2, high: 3 }

// ---------- detection grammar (Part E) ----------

export interface ItemValueMatch {
  equals?: string
  in?: string[]
  startsWith?: string
  contains?: string
  regex?: string
}

export interface ItemSignalCondition {
  name: string
  category?: string
  type?: string
  sourceType?: string
  value?: ItemValueMatch
  minimumOccurrences?: number
  maximumOccurrences?: number
  minimumDistinctValues?: number
  minimumDistinctSourceFiles?: number
  minimumExtractionConfidence?: number
}

export interface ItemRuleCondition {
  id?: string
  signal: ItemSignalCondition
}

export interface ItemAtLeastGroup {
  id?: string
  count: number
  of: ItemRuleCondition[]
}

export interface ItemMetadataCondition extends ItemValueMatch {
  id?: string
  field: string
  notEquals?: string
  notIn?: string[]
}

export interface ItemMatch {
  all?: ItemRuleCondition[]
  any?: ItemRuleCondition[]
  atLeast?: ItemAtLeastGroup[]
  none?: ItemRuleCondition[]
  metadata?: ItemMetadataCondition[]
}

export interface OccurrenceSource {
  signal: string
  group_by?: OccurrenceGroupBy
}

export interface ItemDetection {
  match: ItemMatch
  occurrence_source?: OccurrenceSource
}

// ---------- readiness (Part C) ----------

export interface BlockingSignal {
  signal: string
  reason_code: BlockingReasonCode
  expected_extractor: string | null
}

export interface ItemStateReason {
  state: ReadinessState
  reason_code: ItemReasonCode
  blocking_signals: BlockingSignal[]
}

// ---------- catalog items (Part D) ----------

export interface CatalogItem {
  id: string
  name: string
  description: string | null
  scope: ItemScope
  category: string
  detection: ItemDetection
  excluded_roles: string[]
  state: ReadinessState
  state_reason: ItemStateReason | null
  version: number
  owner_team: string | null
  status: ItemStatus
  deleted_at: string | null
  deleted_by: string | null
  created_at: string
  updated_at: string
}

export interface CatalogItemWriteInput {
  name: string
  description: string | null
  scope: ItemScope
  category: ItemCategory
  detection: ItemDetection
  excluded_roles: ProjectRole[]
  owner_team: string | null
  status: ItemStatus
}

export interface CatalogItemCreateInput extends CatalogItemWriteInput {
  id: string
}

export interface CatalogItemWriteResult {
  item: CatalogItem
  warnings: string[]
}

export interface SoftDeleteResult {
  id: string
  deleted_at: string | null
}

// ---------- resolutions (Part F) ----------

export interface ItemResolution {
  id: string
  item_id: string
  name: string
  description: string | null
  target_description: string | null
  consumer_impact: ConsumerImpact
  effort: EffortLevel
  is_default: boolean
  linux_compatible: boolean
  container_ready: boolean
  notes: string | null
  status: ItemStatus
  deleted_at: string | null
  created_at: string
  updated_at: string
  /** Part U: what choosing this resolution means for each dependent item. */
  derivations?: ResolutionDerivation[]
}

export type DerivationAction = 'derive' | 'not_derived' | 'subsume' | 'not_subsumed'

/** One row of `resolution_derivations`: master catalog data. */
export interface ResolutionDerivation {
  dependent_item_id: string
  action: DerivationAction
  dependent_resolution_id: string | null
  applies_to: 'all' | 'internal_clients'
  reason: string
}

export interface ResolutionWriteInput {
  name: string
  description: string | null
  target_description: string | null
  consumer_impact: ConsumerImpact
  effort: EffortLevel
  is_default: boolean
  linux_compatible: boolean
  container_ready: boolean
  notes: string | null
  status: ItemStatus
}

export interface ResolutionCreateInput extends ResolutionWriteInput {
  id: string
}

// ---------- engagement decisions (Part F) ----------

export interface EngagementDecision {
  id: string
  engagement_id: string
  item_id: string
  item_name: string
  resolution_id: string | null
  resolution_name: string | null
  candidates_considered: string[] | null
  rationale: string | null
  forcing_perspective: ForcingPerspective | null
  forcing_rationale: string | null
  evaluation_notes: string | null
  approver_name: string | null
  approver_role: string | null
  decision_date: string | null
  status: EngagementDecisionStatus
  warnings: string[]
  /** Part U: 'derived' — follows another item's decision (derived_from). */
  source?: 'manual' | 'derived'
  derived_from?: DecisionLink | null
  /** Decided by hand where a derivation applies; what it would give is derived_from.would_derive. */
  overrides_derivation?: boolean
  /** An override made against a leading decision that has since changed. */
  needs_review?: boolean
  review_note?: string | null
  followers?: DecisionLink[]
  created_at: string
  updated_at: string
}

/** One end of a Part U dependency between two decisions. */
export interface DecisionLink {
  decision_id: string
  item_id: string
  item_name: string
  resolution_id: string | null
  resolution_name: string | null
  status: string
  source: 'manual' | 'derived'
  /** The leading resolution the dependent was derived from or overridden against. */
  derived_against_resolution_id: string | null
  derivation_reason: string | null
  would_derive: string | null
  overrides_derivation: boolean
  needs_review: boolean
}

export interface WorkListItemNote {
  subsumed_by: { item_id: string; decision_id: string; resolution_id: string; resolution_name: string; reason: string } | null
  /** The leading item this one depends on. */
  follows: string | null
  action: DerivationAction | null
  /** Whether the leading decision settles this item here; null while the leader is undecided. */
  applies: boolean | null
  note: string | null
}

export interface WorkListDecisions {
  engagement_id: string
  decisions: Record<string, EngagementDecision>
  projects: { project_id: string; items: Record<string, WorkListItemNote> }[]
}

/** Partial-update semantics: an OMITTED field keeps its current value; a
 * field sent as an explicit `null` is cleared. The result is validated as a
 * whole (e.g. clearing something an approval needs is a 422). `status` can
 * be omitted but never null. */
export interface EngagementDecisionUpsertInput {
  resolution_id?: string | null
  candidates_considered?: string[] | null
  rationale?: string | null
  forcing_perspective?: ForcingPerspective | null
  forcing_rationale?: string | null
  evaluation_notes?: string | null
  approver_name?: string | null
  approver_role?: string | null
  decision_date?: string | null
  status?: EditableDecisionStatus
}

// ---------- signals and coverage (Parts C and H) ----------

export interface CatalogSignal {
  name: string
  category: string
  type: string
  description: string | null
  expected_extractor: string
  evidence_kind: string
  value_semantics: string | null
  signal_introduced_in_version: string
  state: ReadinessState
  state_reason: Record<string, unknown> | null
  updated_at: string
}

export interface ExtractorBacklogEntry {
  expected_extractor: string | null
  extractor_status: ExtractorStatus | null
  signals: string[]
  items_blocked: string[]
  items_unblocked: string[]
}

export interface ExtractorBacklog {
  entries: ExtractorBacklogEntry[]
}

export interface ItemCoverageEntry {
  item_id: string
  name: string
  scope: ItemScope
  reason_code: string
  blocking_by_extractor: Record<string, string[]>
}

export interface ItemCoverage {
  ready_count: number
  not_ready_count: number
  not_ready: ItemCoverageEntry[]
}

export interface UnreferencedSignal {
  name: string
  category: string
  expected_extractor: string
}

export interface SignalCoverage {
  ready_signal_count: number
  referenced_ready_count: number
  unreferenced: UnreferencedSignal[]
}

// ---------- signal index ----------

/** How an item's detection uses a signal: in `match` (all/any/atLeast), in a
 * `none` condition (exclusion), or as `occurrence_source`. */
export type SignalUsage = 'match' | 'none' | 'occurrence_source'

export interface SignalReference {
  item_id: string
  item_name: string
  item_scope: ItemScope
  item_status: ItemStatus
  usages: SignalUsage[]
}

/** GET /api/catalog/signal-index — one entry per signal. `registered` is
 * false for a name an item references that the registry does not have; its
 * registry fields are then null. */
export interface SignalIndexEntry {
  name: string
  registered: boolean
  type: string | null
  category: string | null
  expected_extractor: string | null
  state: ReadinessState | null
  signal_introduced_in_version: string | null
  description: string | null
  referenced: boolean
  /** Union of usages across all referencing items. */
  usages: SignalUsage[]
  /** Referenced, but only ever in `none`: exclusion work, not detection. */
  exclusion_only: boolean
  referenced_by: SignalReference[]
}

/** GET /api/catalog/items/{item_id}/signals — the reverse of the index. */
export interface ItemSignal {
  name: string
  registered: boolean
  type: string | null
  category: string | null
  expected_extractor: string | null
  state: ReadinessState | null
  usages: SignalUsage[]
}

// ---------- catalog export staleness (28-ITEM Part W) ----------

export interface CatalogExportChange {
  item_id: string
  /** Null when the item is no longer in the database at all. */
  item_name: string | null
  change: 'added' | 'edited' | 'deleted'
}

/** How far the database has drifted from the last export into the
 * repository's catalog/items/. Nothing exports automatically. */
export interface CatalogExportStatus {
  last_export: { exported_at: string; catalog_hash: string; item_count: number } | null
  current_hash: string
  is_current: boolean
  changed: number
  changes: CatalogExportChange[]
  /** The command a person runs to export into the repository, then commits. */
  command: string
}
