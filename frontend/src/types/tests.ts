// Lifecycle step 8, test-coverage-assessment, phase 1 (32-STEP-008 Part K).

export type TestType = 'unit' | 'integration' | 'functional' | 'smoke' | 'unclassified'
export type TestBucket = 'has_tests' | 'missing_tests' | 'no_testable_logic'

export interface CoverageScan {
  commit_sha: string | null
  cache_state: 'computed' | 'reused' | 'no_commit' | 'uncommitted_changes'
  cache_note: string | null
  scanned_at: string
  reused_from_scanned_at: string | null
  report_sources: { path: string; format: string; attribution: string }[]
}

export interface CiMaturity {
  has_pipeline: boolean
  runs_tests: boolean
  collects_coverage: boolean
  publishes_coverage: boolean
  enforces_coverage_gate: boolean
  pipelines: { path: string; system: string }[]
  evidence: { fact: string; path: string; line: number; text: string }[]
}

export interface TestProject {
  project_path: string
  reason: string
  test_classes: number
  test_classes_by_type: Record<TestType, number>
}

export interface TestClassRow {
  project_path: string
  file_path: string
  class_name: string
  line_start: number
  test_type: TestType
  classification_reason: string
  evidence: { kind: string; value: string; indicates: string; strength: string }[]
  test_count: number
}

export interface ProjectCoverage {
  project_path: string
  files: number
  has_tests: number
  missing_tests: number
  no_testable_logic: number
  unit_line_pct: number | null
  unit_not_measured_reason: string | null
  integration_line_pct: number | null
  integration_not_measured_reason: string | null
}

export interface TestLink {
  test_file: string
  test_class: string
  test_type: TestType
  method: 'type_reference' | 'type_reference+naming' | 'naming_only'
  confidence: number
}

export interface SourceFileRow {
  project_path: string
  file_path: string
  bucket: TestBucket
  testable_members: number
  tests: TestLink[]
  coverage_source: 'existing_report' | 'executed' | 'not_measured'
  line_pct: number | null
  branch_pct: number | null
  /** Always set when not measured: unknown is never shown as 0%. */
  not_measured_reason: string | null
  unit_line_pct: number | null
  unit_not_measured_reason: string | null
  integration_line_pct: number | null
  integration_not_measured_reason: string | null
}

export interface RepositoryTests {
  repository_id: string
  scan: CoverageScan
  summary: {
    testProjects?: number
    testClasses?: number
    testMethods?: number
    testClassesByType?: Record<TestType, number>
    sourceFiles?: number
    sourceFilesByBucket?: Record<TestBucket, number>
    coverageReports?: number
    sourceFilesMeasured?: number
  }
  ci_maturity: CiMaturity | null
  test_projects: TestProject[]
  test_classes: TestClassRow[]
  projects: ProjectCoverage[]
  source_files: SourceFileRow[]
  coverage_reports: { path: string; format: string; attribution: string; attributionReason: string; filesMatched: number; filesInReport: number }[]
  execution: string
}
