import { useState } from 'react'
import { JobsList } from './workflow/JobsList'
import { EngagementPolicySection } from './workflow/EngagementPolicySection'
import { ExecutionsList } from './workflow/ExecutionsList'
import { ExecutionDetail } from './workflow/ExecutionDetail'
import { JobDefinitionViewer } from './workflow/definition/JobDefinitionViewer'

interface WorkflowPageProps {
  engagementId: string
  selectedExecutionId: string | null
  onSelectExecution: (executionId: string | null) => void
  onNavigateToRepositories: () => void
}

/** Engagement-scoped, hidden in Master Catalog view — see
 * 20-WORKFLOW-OBSERVABILITY-UI.md Part B. `selectedExecutionId` is owned by
 * App.tsx (not local state) so it can be driven by a real URL — see
 * Part C and src/routing.ts. `selectedJobName` (the definition viewer,
 * 22-STEP-SEQUENCING-AND-POLICY.md Part E) stays local: it's a same-page
 * disclosure, not a distinct navigable view. */
export function WorkflowPage({ engagementId, selectedExecutionId, onSelectExecution, onNavigateToRepositories }: WorkflowPageProps) {
  const [selectedJobName, setSelectedJobName] = useState<string | null>(null)

  if (selectedExecutionId) {
    return <ExecutionDetail executionId={selectedExecutionId} onBack={() => onSelectExecution(null)} />
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-6">
      <JobsList
        engagementId={engagementId}
        selectedJobName={selectedJobName}
        onSelectExecution={onSelectExecution}
        onSelectJob={(jobName) => setSelectedJobName((current) => (current === jobName ? null : jobName))}
      />
      <EngagementPolicySection key={engagementId} engagementId={engagementId} />
      {selectedJobName && <JobDefinitionViewer jobName={selectedJobName} engagementId={engagementId} />}
      <ExecutionsList
        engagementId={engagementId}
        onSelectExecution={onSelectExecution}
        onNavigateToRepositories={onNavigateToRepositories}
      />
    </div>
  )
}
