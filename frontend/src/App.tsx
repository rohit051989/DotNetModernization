import { useEffect, useState } from 'react'
import { listEngagements } from './api/catalog'
import { getExecution } from './api/workflow'
import type { Engagement } from './types/catalog'
import { AppShell } from './components/AppShell'
import type { TabKey } from './components/TabBar'
import { CatalogPage } from './pages/CatalogPage'
import { RepositoriesPage } from './pages/RepositoriesPage'
import { DashboardPage } from './pages/DashboardPage'
import { WorkflowPage } from './pages/WorkflowPage'
import { ToastProvider } from './components/Toast'
import { parseExecutionIdFromLocation, pushExecutionRoute, pushRootRoute } from './routing'

function App() {
  const [selectedEngagementId, setSelectedEngagementId] = useState<string | null>(null)
  const [engagements, setEngagements] = useState<Engagement[]>([])
  const [activeTab, setActiveTab] = useState<TabKey>('catalog')
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null)

  useEffect(() => {
    listEngagements()
      .then(setEngagements)
      .catch(() => setEngagements([]))
  }, [])

  // Resolve a deep-linked execution URL on load — 20-WORKFLOW-OBSERVABILITY-UI.md
  // Part C: "an execution can be linked to and reloaded directly." The
  // engagement isn't in the URL, so it's resolved from the execution's own
  // parameters.engagement_id.
  useEffect(() => {
    const executionId = parseExecutionIdFromLocation()
    if (!executionId) return
    getExecution(executionId)
      .then((execution) => {
        const engagementId = typeof execution.parameters.engagement_id === 'string' ? execution.parameters.engagement_id : null
        if (engagementId) setSelectedEngagementId(engagementId)
        setActiveTab('workflow')
        setSelectedExecutionId(executionId)
      })
      .catch(() => {
        // Leave the URL as-is; WorkflowPage's "not found" state below handles it
        // once an engagement is selected. Without one, fall back to Catalog.
        setActiveTab('workflow')
        setSelectedExecutionId(executionId)
      })
  }, [])

  useEffect(() => {
    function handlePopState() {
      const executionId = parseExecutionIdFromLocation()
      setSelectedExecutionId(executionId)
      if (executionId) setActiveTab('workflow')
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  function handleSelectEngagement(engagementId: string | null) {
    setSelectedEngagementId(engagementId)
    // Repositories/Dashboard/Workflow are engagement-only — Master Catalog has
    // nothing to show there, so fall back to the one tab that always exists.
    if (engagementId === null && activeTab !== 'catalog') {
      setActiveTab('catalog')
    }
  }

  function handleSelectTab(tab: TabKey) {
    setActiveTab(tab)
    if (tab !== 'workflow' && selectedExecutionId) {
      setSelectedExecutionId(null)
      pushRootRoute()
    }
  }

  function handleNavigateToExecution(executionId: string) {
    setActiveTab('workflow')
    setSelectedExecutionId(executionId)
    pushExecutionRoute(executionId)
  }

  function handleSelectExecution(executionId: string | null) {
    setSelectedExecutionId(executionId)
    if (executionId) pushExecutionRoute(executionId)
    else pushRootRoute()
  }

  const engagementName =
    engagements.find((engagement) => engagement.id === selectedEngagementId)?.client_name ??
    selectedEngagementId ??
    ''

  return (
    <ToastProvider>
      <AppShell
        engagements={engagements}
        selectedEngagementId={selectedEngagementId}
        onSelectEngagement={handleSelectEngagement}
        activeTab={activeTab}
        onSelectTab={handleSelectTab}
      >
        {selectedExecutionId ? (
          // A deep-linked execution renders regardless of engagement/tab
          // state — 20-WORKFLOW-OBSERVABILITY-UI.md Part E: "Execution not
          // found — clear message ..., not a blank screen" must work even
          // when the execution (and so its engagement) never resolved.
          <WorkflowPage
            engagementId={selectedEngagementId ?? ''}
            selectedExecutionId={selectedExecutionId}
            onSelectExecution={handleSelectExecution}
            onNavigateToRepositories={() => setActiveTab('repositories')}
          />
        ) : activeTab === 'repositories' && selectedEngagementId ? (
          <RepositoriesPage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
            engagementName={engagementName}
            onNavigateToExecution={handleNavigateToExecution}
          />
        ) : activeTab === 'dashboard' && selectedEngagementId ? (
          <DashboardPage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
            onNavigateToRepositories={() => setActiveTab('repositories')}
            onNavigateToExecution={handleNavigateToExecution}
          />
        ) : activeTab === 'workflow' && selectedEngagementId ? (
          <WorkflowPage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
            selectedExecutionId={selectedExecutionId}
            onSelectExecution={handleSelectExecution}
            onNavigateToRepositories={() => setActiveTab('repositories')}
          />
        ) : (
          <CatalogPage engagements={engagements} selectedEngagementId={selectedEngagementId} />
        )}
      </AppShell>
    </ToastProvider>
  )
}

export default App
