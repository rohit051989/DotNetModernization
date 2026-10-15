/** A repository's conversion plan and its units — 34-CONVERSION-ARCHITECTURE.md
 * C4 and Part E, served by GET /api/repositories/{id}/conversion. */

export type PlanStatus = 'planned' | 'running' | 'completed' | 'partial' | 'stopped'

export type UnitStatus =
  | 'planned'
  | 'applied'
  | 'verified'
  | 'committed'
  | 'not_applicable'
  | 'failed'
  | 'blocked'
  | 'stale'
  | 'awaiting_review'
  | 'awaiting_human'
  | 'excluded'

export type AutomationClass = 'deterministic' | 'assisted' | 'manual'

/** One evidence file: where it is, its sha256 when it was recorded, and a
 * link that serves it only while the file still has that hash. */
export interface EvidenceLink {
  kind: string
  path: string
  sha256: string
  url: string
  project: string | null
}

/** One unit-test project's results: counts and the names of failing tests. */
export interface TestTotals {
  total: number
  passed: number
  failed: number
  skipped: number
  failed_tests: string[]
}

export interface TestRun {
  /** The commit the tests ran at: the legacy commit for the baseline, the
   * branch tip for the latest results. */
  commit: string | null
  /** The unit whose run this is; null for the baseline. */
  sequence: number | null
  framework: string | null
  tests: Record<string, TestTotals>
  total: number
  passed: number
  evidence: EvidenceLink[]
}

export interface UnitDependency {
  sequence: number
  reason: string
}

export interface ConversionUnit {
  sequence: number
  unit_id: string
  recipe_id: string
  step_id: string
  approach_id: string
  approach_version: string
  automation_class: AutomationClass
  /** What the unit does, in a line: "Ardalis.GuardClauses 4.0.1 -> 5.0.0". */
  title: string
  /** For packages that move as one unit: why they only resolve together. */
  together_because: string | null
  status: UnitStatus
  status_reason: string | null
  order_reason: string
  depends_on: UnitDependency[]
  commit_sha: string | null
  /** passed/total per test project, for a unit that ran its tests. */
  tests: Record<string, string> | null
  evidence: EvidenceLink[]
}

export interface ConversionPlanSummary {
  id: string
  status: PlanStatus
  created_at: string
}

export interface RepositoryConversion {
  plan: {
    id: string
    status: PlanStatus
    status_reason: string | null
    branch: string
    worktree_path: string
    legacy_commit: string
    from_framework: string | null
    target_framework: string
    /** The framework the branch tip builds for: target_framework once the retarget is committed. */
    tip_framework: string | null
    tip_commit: string | null
    created_at: string
    completed_at: string | null
    exclusions: { package_id: string; reason: string }[]
  }
  counts: Partial<Record<UnitStatus, number>>
  automation: Partial<Record<AutomationClass, number>>
  baseline: (TestRun & { passed_baseline: boolean; failure: string | null }) | null
  /** The latest committed unit's test run: the "after". Null until a unit commits. */
  latest: TestRun | null
  units: ConversionUnit[]
  /** Every plan for this repository, newest first. */
  plans: ConversionPlanSummary[]
}

/** The repository's current conversion (36-COPILOT-ENHANCED-CONVERSION Part N). */
export type ConversionState = 'prepared' | 'run' | 'verified'

export interface JobRef {
  job_execution_id: string
  batch_status: string
  exit_status: string | null
  exit_message: string | null
}

export interface PrepareAttempt {
  at: string | null
  status: string | null
  message: string | null
  number: number | null
  jobExecutionId: string | null
}

export interface ConversionVerification {
  verdict: string
  reasons: string[]
  verifiedAt: string
  tip: string
  markdown: string
  current: boolean
}

export interface CurrentConversion {
  number: number | null
  state: ConversionState | null
  branch: string | null
  worktree: string | null
  baseline: string | null
  head: string | null
  commits_beyond_inputs: number
  uncommitted: string[]
  runbook_path: string | null
  runbook: string | null
  opening_message: string | null
  prepared_at: string | null
  package_step: { seconds?: number; cycles?: number; skipped?: string; flaky?: { test: string; project: string }[] }
  left_for_agent: { items?: { item: string; resolution: string | null; places: number }[] }
  verify_refusal: string | null
  verification: ConversionVerification | null
  verification_job: JobRef | null
  last_prepare: PrepareAttempt | null
  discovery_job: JobRef | null
}
