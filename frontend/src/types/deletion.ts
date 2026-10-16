/** A hard delete's plan (app/deletion/service.py): exactly what would go. */
export interface DeletionPlan {
  kind: 'repository' | 'engagement'
  engagement: string
  repository?: string
  repositories?: string[]
  name: string
  confirm: string
  rows: Record<string, number>
  folders: { path: string; files: number; bytes: number }[]
  checkouts: {
    checkout: string
    /** The repository itself is never deleted: said plainly, for this checkout or clone. */
    stays: string
    available: boolean
    worktrees: { path: string; branch: string | null }[]
    branches: { branch: string; source: string; commits_only_here: number }[]
    kept: { branch: string; source: string; why: string }[]
    run: { repository: string; number: number; branch: string; agent_commits: number }[]
  }[]
  running: { job: string; execution: string; status: string; since: string }[]
  kept_shared: string
  estate_note?: string
}

export interface DeletionSummary {
  rows: Record<string, number>
  folders: string[]
  worktrees: string[]
  branches: string[]
  deleted_at: string
}
