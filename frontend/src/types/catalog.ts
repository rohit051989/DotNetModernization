export type LifecycleStatus = 'draft' | 'active' | 'deprecated'
export type ConsumerImpact = 'none' | 'low' | 'medium' | 'high'
export type EffortLevel = 'low' | 'medium' | 'high'
export type DecisionStatus = 'parked' | 'in_review' | 'approved' | 'superseded'
export type EngineCoverage = 'none' | 'partial' | 'strong'

export interface DetectionRules {
  target_frameworks: string[]
  required_namespaces: string[]
  forbidden_namespaces: string[]
  required_packages: string[]
  file_globs: string[]
  forbidden_file_globs: string[]
  project_properties: Record<string, string>
  config_markers: string[]
  confidence_weight: number
  notes: string | null
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
  version: number
  target_state_count: number
  updated_at: string
}

export interface PatternDetail {
  id: string
  name: string
  summary: string
  description: string | null
  legacy_stack: string
  category: string
  detection_rules: DetectionRules
  typical_indicators: string | null
  known_risks: string | null
  status: LifecycleStatus
  version: number
  created_at: string
  updated_at: string
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
  engine_support: EngineSupport | null
  playbook_md: string | null
  prerequisites: string | null
  known_limitations: string | null
  status: LifecycleStatus
  version: number
  created_at: string
  updated_at: string
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
}

export interface CoverageSummary {
  engagement_id: string
  total_patterns: number
  approved: number
  in_review: number
  parked: number
  patterns_without_decision: string[]
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
  forcing_factor: string | null
  rationale: string | null
  approver_name: string | null
  approver_role: string | null
  decision_date: string | null
  status: DecisionStatus
  created_at: string
  updated_at: string
}

export interface HealthStatus {
  status: string
  database: 'connected' | 'error'
  version: string
}
