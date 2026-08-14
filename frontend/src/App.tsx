import { useEffect, useState } from 'react'
import { listEngagements } from './api/catalog'
import type { Engagement } from './types/catalog'
import { AppShell } from './components/AppShell'
import { CatalogPage } from './pages/CatalogPage'
import { ToastProvider } from './components/Toast'

function App() {
  const [selectedEngagementId, setSelectedEngagementId] = useState<string | null>(null)
  const [engagements, setEngagements] = useState<Engagement[]>([])

  useEffect(() => {
    listEngagements()
      .then(setEngagements)
      .catch(() => setEngagements([]))
  }, [])

  return (
    <ToastProvider>
      <AppShell
        engagements={engagements}
        selectedEngagementId={selectedEngagementId}
        onSelectEngagement={setSelectedEngagementId}
      >
        <CatalogPage engagements={engagements} selectedEngagementId={selectedEngagementId} />
      </AppShell>
    </ToastProvider>
  )
}

export default App
