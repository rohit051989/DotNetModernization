// Central results (backend app.results): what the repository page and the estate read from the database, the lists a
// page at a time. Shapes of the summaries; the paged lists' items keep the shapes their views already render.

import type { Page } from '../components/PagedList'
import type { Json } from '../pages/workflow/artifacts/adapters'
import type { RepositoryImpact } from './impact'
import type { CiMaturity, CoverageScan } from './tests'

export interface StoredResult {
  artifact_id: string
  job_execution_id: string
  created_at: string
  /** The artifact's top-level fields other than lists: its summary, counts and versions. */
  head: Json
}

export interface RepositoryResults {
  repository_id: string
  results: Partial<Record<string, StoredResult>>
  /** Where the repository was scanned, when that is another machine: "on Ann's machine (PC-17)". */
  held_on: string | null
  not_copied: number
  not_copied_note: string | null
}

export interface EntryPointSummary {
  repository_id: string
  scanner_version: string
  skip_source: string
  scanned_at: string | null
  entry_point_count: number
  request_entry_point_count: number
  lifecycle_hook_count: number
  count_by_kind: Record<string, number>
  count_by_origin: Record<string, number>
  count_by_verb: Record<string, number>
  no_declared_authentication_count: number
  authorisation_not_assessed_count: number
  auth_declared_scope: string
  capabilities_manifest_version: string | null
  capability_kinds: string[]
  project_count: number
  projects_with_requests: number
  lifecycle_hooks_without_requests: number
}

export interface KindCount {
  entry_class: 'request' | 'lifecycle'
  kind: string
  count: number
}

export interface OutboundSummary {
  repository_id: string
  scanner_version: string
  skip_source: string
  scanned_at: string | null
  invocation_count: number
  unused_count: number
  count_by_mechanism: Record<string, number>
  count_by_verdict: Record<string, number>
  auth_declared_scope: string
  project_count: number
  projects_with_invocations: number
}

export interface MechanismCount {
  mechanism: string
  count: number
  /** 0 incompatible, 1 requires change, 2 unknown, 3 compatible, 9 unused. */
  worst_rank: number
}

export interface BackendSummary {
  repository_id: string
  production_environment: string | null
  operations: number
  applications: number
  count_by_status: Record<string, number>
}

export interface BackendApplication {
  project_id: string
  project_path: string
  operations: number
  counts: Partial<Record<'yes' | 'no' | 'unresolved' | 'not_assessed', number>>
}

export interface SoapSummary {
  repository_id: string
  engagement_id: string
  scanned_at: string | null
  estate_run_at: string | null
  estate_stale: boolean
  estate_note: string | null
  target_wcf_client_version: string | null
  unused_count: number
  calls: number
  environments: number
  need_change: number
  undecided: number
}

export interface ImpactSummary {
  totals: RepositoryImpact['totals']
  client_impact_note: string
  counts: Record<'hotspots' | 'rule_conflicts' | 'work_item_conflicts' | 'work_items' | 'files', number>
}

export interface TestsSummary {
  repository_id: string
  scan: CoverageScan
  summary: Record<string, unknown> & {
    testClasses?: number
    testMethods?: number
    testClassesByType?: Record<string, number>
    sourceFilesByBucket?: Record<string, number>
  }
  ci_maturity: CiMaturity | null
  counts: Record<'test_projects' | 'test_classes' | 'projects' | 'source_files', number>
  /** Every not-measured reason, numbered in the order the tables show them. */
  not_measured_reasons: string[]
  execution: string
}

/** A list nested in a row, its first page sent with the row. */
export type FirstPage<T> = Page<T>
