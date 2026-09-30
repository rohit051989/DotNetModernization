export type LifecycleStatus = 'draft' | 'active' | 'deprecated'
export type ConsumerImpact = 'none' | 'low' | 'medium' | 'high'
export type EffortLevel = 'low' | 'medium' | 'high'
export type DecisionStatus = 'parked' | 'in_review' | 'approved' | 'superseded'
export type ForcingPerspective =
  | 'SECURITY'
  | 'EVOLUTION'
  | 'REGULATION'
  | 'PERFORMANCE_SCALABILITY'
  | 'AVAILABILITY_RESILIENCE'
  | 'LOCATION'
  | 'DEVELOPMENT_RESOURCE'
export type EngineCoverage = 'none' | 'partial' | 'strong'
export type ScopeStatus = 'active' | 'deferred'

// ---------- Step 4 classification schema (24-STEP-004-CLASSIFICATION.md Part C) ----------

export type ClassificationRole = 'PRIMARY' | 'SECONDARY' | 'PROJECT_ROLE'
export type PatternScope = 'PROJECT' | 'REPOSITORY'
export type RulesStatus = 'active' | 'awaiting_signals' | 'draft'

export interface ValueMatch {
  equals?: string | null
  in?: string[] | null
  startsWith?: string | null
  contains?: string | null
  regex?: string | null
}

export interface SignalCondition {
  name: string
  category?: string | null
  type?: string | null
  sourceType?: string | null
  value?: ValueMatch | null
  minimumOccurrences?: number | null
  maximumOccurrences?: number | null
  minimumDistinctValues?: number | null
  minimumDistinctSourceFiles?: number | null
  minimumExtractionConfidence?: number | null
}

export interface RuleCondition {
  id?: string
  signal: SignalCondition
}

export interface SupportingCondition extends RuleCondition {
  weight: number
}

export interface NoneCondition extends RuleCondition {
  disqualify?: boolean
  penalty?: number | null
}

export interface AtLeastGroup {
  id?: string
  count: number
  of: RuleCondition[]
}

export interface MetadataCondition {
  id?: string
  field: string
  equals?: string | null
  in?: string[] | null
  startsWith?: string | null
  contains?: string | null
  regex?: string | null
}

export interface SignalRuleSet {
  schema: 'signal-rules/1.0'
  all: RuleCondition[]
  any: RuleCondition[]
  atLeast: AtLeastGroup[]
  supporting: SupportingCondition[]
  none: NoneCondition[]
  metadata: MetadataCondition[]
}

export function emptySignalRuleSet(): SignalRuleSet {
  return { schema: 'signal-rules/1.0', all: [], any: [], atLeast: [], supporting: [], none: [], metadata: [] }
}

export interface PatternEligibility {
  fingerprintStatuses: string[]
  excludedProjectRoles: string[]
}

export interface AnalysisRequirementSet {
  required: Record<string, boolean>
  preferred: Record<string, boolean>
}

export interface PatternThresholds {
  minimumScore: number
  highConfidenceScore: number
}

export interface RequiredSignalPending {
  signal_name: string
  purpose: string
  expected_extractor: string
  blocking: boolean
}

export interface SignalRegistryEntry {
  name: string
  category: string
  type: string
  description: string
  extractor: string
  value_semantics: string
  weak_anchor: boolean
}

export interface SignalRegistry {
  registry_version: string
  signals: SignalRegistryEntry[]
}

/** Part B1 classification fields as they appear on PatternDetail — always
 * populated (the backend defaults every one of these at write time). See
 * PatternClassificationInput below for the create/update payload shape,
 * where every field is optional instead ('omit to leave unchanged/default'). */
export interface PatternClassificationFields {
  classification_role: ClassificationRole
  classification_family: string | null
  classification_value: string | null
  scope: PatternScope
  priority: number
  compatible_with: string[]
  conflicts_with: string[]
  anchor_signals: string[]
  eligibility: PatternEligibility | null
  analysis_requirements: AnalysisRequirementSet | null
  thresholds: PatternThresholds
  rules_status: RulesStatus
  required_signals_pending: RequiredSignalPending[]
  detection_rules: SignalRuleSet
}

/** Same fields, all optional — the create/update payload shape. Omitting a
 * field on create applies the same default the J1 migration gave existing
 * patterns; omitting it on update leaves the pattern's current value
 * untouched (see backend/app/routers/patterns.py's `_resolve_classification_fields`). */
export interface PatternClassificationInput {
  classification_role?: ClassificationRole
  classification_family?: string | null
  classification_value?: string | null
  scope?: PatternScope
  priority?: number
  compatible_with?: string[]
  conflicts_with?: string[]
  anchor_signals?: string[]
  eligibility?: PatternEligibility | null
  analysis_requirements?: AnalysisRequirementSet | null
  thresholds?: PatternThresholds
  rules_status?: RulesStatus
  required_signals_pending?: RequiredSignalPending[]
  detection_rules?: SignalRuleSet
}

export interface EngineSupport {
  engine: string | null
  coverage: EngineCoverage | null
  scenarios: string[]
  skills: string[]
  gaps: string[]
  custom_skills_required: string[]
}

export interface PatternSummary {
  id: string
  name: string
  summary: string
  legacy_stack: string
  category: string
  status: LifecycleStatus
  /** PRIMARY, SECONDARY or PROJECT_ROLE. A cluster cannot meaningfully merge
   * into a PROJECT_ROLE pattern, so step 6's merge selector filters on it. */
  classification_role: string
  version: number
  target_state_count: number
  updated_at: string
  deleted_at: string | null
  deleted_by: string | null
}

export interface PatternDetail extends PatternClassificationFields {
  id: string
  name: string
  summary: string
  description: string | null
  legacy_stack: string
  category: string
  typical_indicators: string | null
  known_risks: string | null
  status: LifecycleStatus
  version: number
  created_at: string
  updated_at: string
  deleted_at: string | null
  deleted_by: string | null
  target_state_options: TargetStateSummary[]
}

export interface TargetStateSummary {
  id: string
  pattern_id: string
  name: string
  summary: string
  target_stack: string
  consumer_impact: ConsumerImpact
  effort: EffortLevel
  linux_compatible: boolean
  container_ready: boolean
  is_lift_and_shift: boolean
  is_recommended: boolean
  status: LifecycleStatus
  version: number
  updated_at: string
}

export interface TargetStateDetail {
  id: string
  pattern_id: string
  name: string
  summary: string
  target_stack: string
  consumer_impact: ConsumerImpact
  effort: EffortLevel
  linux_compatible: boolean
  container_ready: boolean
  is_lift_and_shift: boolean
  is_recommended: boolean
  engine_support: EngineSupport | null
  playbook_md: string | null
  prerequisites: string | null
  known_limitations: string | null
  status: LifecycleStatus
  version: number
  created_at: string
  updated_at: string
  deleted_at: string | null
  deleted_by: string | null
}

export interface Engagement {
  id: string
  client_name: string
  description: string | null
  target_platform: string | null
  default_posture: string
  status: LifecycleStatus
  created_at: string
  updated_at: string
  deleted_at: string | null
  deleted_by: string | null
}

export interface CoverageSummary {
  engagement_id: string
  total_patterns: number
  approved: number
  in_review: number
  parked: number
  deferred: number
  patterns_without_decision: string[]
  perspective_breakdown: Record<string, number>
}

export interface DecisionRecord {
  id: string
  engagement_id: string
  pattern_id: string
  pattern_name: string
  selected_target_state_id: string | null
  selected_target_state_name: string | null
  candidates_considered: string[] | null
  evaluation_notes: string | null
  forcing_perspective: ForcingPerspective | null
  forcing_rationale: string | null
  rationale: string | null
  approver_name: string | null
  approver_role: string | null
  decision_date: string | null
  status: DecisionStatus
  created_at: string
  updated_at: string
  deleted_at: string | null
  deleted_by: string | null
}

export interface HealthStatus {
  status: string
  database: 'connected' | 'error'
  version: string
}

// ---------- Request payloads (mirror the backend's Create/Update schemas) ----------

export type EngineSupportInput = EngineSupport

export interface PatternInput extends PatternClassificationInput {
  name: string
  summary: string
  description: string | null
  legacy_stack: string
  category: string
  typical_indicators: string | null
  known_risks: string | null
  status: LifecycleStatus
}

export interface PatternCreateInput extends PatternInput {
  id: string
}

export type PatternUpdateInput = PatternInput

export interface TargetStateInput {
  name: string
  summary: string
  target_stack: string
  consumer_impact: ConsumerImpact
  effort: EffortLevel
  linux_compatible: boolean
  container_ready: boolean
  is_lift_and_shift: boolean
  is_recommended: boolean
  engine_support: EngineSupportInput | null
  playbook_md: string | null
  prerequisites: string | null
  known_limitations: string | null
  status: LifecycleStatus
}

export interface TargetStateCreateInput extends TargetStateInput {
  id: string
}

export type TargetStateUpdateInput = TargetStateInput

export interface PatternDeprecateResponse {
  id: string
  status: LifecycleStatus
  referenced_by_decisions: number
}

export interface PatternSoftDeleteResponse {
  id: string
  deleted_at: string | null
}

export interface TargetStateDeprecateResponse {
  id: string
  status: LifecycleStatus
}

export interface TargetStateSoftDeleteResponse {
  id: string
  deleted_at: string | null
}

export interface DecisionRecordInput {
  selected_target_state_id: string | null
  candidates_considered: string[] | null
  evaluation_notes: string | null
  forcing_perspective: ForcingPerspective | null
  forcing_rationale: string | null
  rationale: string | null
  approver_name: string | null
  approver_role: string | null
  decision_date: string | null
  status: DecisionStatus
}

// Body for PUT /api/engagements/{eid}/patterns/{pid}/decision — identity is
// fully in the path, so there is no pattern_id here.
export type DecisionRecordUpsertInput = DecisionRecordInput

// Body for PUT /api/decisions/{id} — editing a specific record by its own id.
export type DecisionRecordUpdateInput = DecisionRecordInput

// ---------- Client-scoped patterns (engagement_patterns overlay) ----------

export interface EngagementPatternDeferRequest {
  deferred_reason: string | null
}

export interface EngagementPatternView {
  engagement_id: string
  pattern_id: string
  name: string
  summary: string
  description: string | null
  legacy_stack: string
  category: string
  detection_rules: SignalRuleSet
  typical_indicators: string | null
  known_risks: string | null
  status: LifecycleStatus
  version: number
  created_at: string
  updated_at: string
  target_state_options: TargetStateSummary[]
  scope_status: ScopeStatus
  deferred_reason: string | null
  deleted_at: string | null
  deleted_by: string | null
  decision_status: DecisionStatus | null
  selected_target_state_name: string | null
  forcing_perspective: ForcingPerspective | null
}

export interface EngagementPatternSoftDeleteResponse {
  engagement_id: string
  pattern_id: string
  deleted_at: string | null
}
