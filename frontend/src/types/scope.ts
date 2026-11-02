/** A repository's conversion scope (36-COPILOT-ENHANCED-CONVERSION.md Part O): which of its projects its conversions
 * cover. The project is the unit; a solution is a shortcut for its projects. */

export interface ScopeProject {
  /** Relative to the repository: the project's identity in the scope. */
  path: string
  name: string
  /** The solutions that contain it. */
  solutions: string[]
  /** The projects it references. */
  dependsOn: string[]
  /** Work items found in it, counted as the work list counts them. */
  workItems: number
  excluded: boolean
  /** Discovered after the scope was saved: in scope by default. */
  new: boolean
}

export interface ScopeSolution {
  path: string
  name: string
  projects: string[]
}

export interface ConversionScope {
  /** 0 when no scope was ever saved: every project is in scope. */
  version: number
  saved: { by: string; on: string | null; at: string; reason: string | null } | null
  treatment: 'leave_untouched'
  solutions: ScopeSolution[]
  projects: ScopeProject[]
  /** Excluded at the last save, no longer in the repository: dropped out. */
  gone: string[]
  totals: { projects: number; kept: number; excluded: number; workItemsOutOfScope: number; new: number }
  on_save: { reprepares: number | null; keeps: number | null; note: string }
}

export interface ScopeSaved {
  version: number
  newlyExcluded: string[]
  reIncluded: string[]
  reprepare_job_execution_id: string | null
  note: string
}

/** One reason a selection cannot be saved, as the server and the editor both word it. */
export interface ScopeProblem {
  code: 'NOTHING_KEPT' | 'DEPENDENCY_EXCLUDED'
  message: string
  project?: string
  dependency?: string
  through?: string[]
}
