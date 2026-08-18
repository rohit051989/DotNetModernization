import { JobsList } from './workflow/JobsList'
import { ExecutionsList } from './workflow/ExecutionsList'
import { ExecutionDetail } from './workflow/ExecutionDetail'

interface WorkflowPageProps {
  engagementId: string
  selectedExecutionId: string | null
  onSelectExecution: (executionId: string | null) => void
  onNavigateToRepositories: () => void
}

/** Engagement-scoped, hidden in Master Catalog view — see
 * 20-WORKFLOW-OBSERVABILITY-UI.md Part B. `selectedExecutionId` is owned by
 * App.tsx (not local state) so it can be driven by a real URL — see
 * Part C and src/routing.ts. */
export function WorkflowPage({ engagementId, selectedExecutionId, onSelectExecution, onNavigateToRepositories }: WorkflowPageProps) {
  if (selectedExecutionId) {
    return <ExecutionDetail executionId={selectedExecutionId} onBack={() => onSelectExecution(null)} />
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <JobsList engagementId={engagementId} onSelectExecution={onSelectExecution} />
      <ExecutionsList
        engagementId={engagementId}
        onSelectExecution={onSelectExecution}
        onNavigateToRepositories={onNavigateToRepositories}
      />
    </div>
  )
}
