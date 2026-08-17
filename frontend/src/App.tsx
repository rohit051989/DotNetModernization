import { useEffect, useState } from 'react'
import { listEngagements } from './api/catalog'
import type { Engagement } from './types/catalog'
import { AppShell } from './components/AppShell'
import type { TabKey } from './components/TabBar'
import { CatalogPage } from './pages/CatalogPage'
import { RepositoriesPage } from './pages/RepositoriesPage'
import { DashboardPage } from './pages/DashboardPage'
import { ToastProvider } from './components/Toast'

function App() {
  const [selectedEngagementId, setSelectedEngagementId] = useState<string | null>(null)
  const [engagements, setEngagements] = useState<Engagement[]>([])
  const [activeTab, setActiveTab] = useState<TabKey>('catalog')

  useEffect(() => {
    listEngagements()
      .then(setEngagements)
      .catch(() => setEngagements([]))
  }, [])

  function handleSelectEngagement(engagementId: string | null) {
    setSelectedEngagementId(engagementId)
    // Repositories/Dashboard are engagement-only — Master Catalog has nothing
    // to show there, so fall back to the one tab that always exists.
    if (engagementId === null && activeTab !== 'catalog') {
      setActiveTab('catalog')
    }
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
        onSelectTab={setActiveTab}
      >
        {activeTab === 'repositories' && selectedEngagementId ? (
          <RepositoriesPage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
            engagementName={engagementName}
          />
        ) : activeTab === 'dashboard' && selectedEngagementId ? (
          <DashboardPage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
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
