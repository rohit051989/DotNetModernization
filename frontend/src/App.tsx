import { useState } from 'react'
import { AppShell } from './components/AppShell'
import { CatalogPage } from './pages/CatalogPage'

function App() {
  const [selectedEngagementId, setSelectedEngagementId] = useState<string | null>(null)

  return (
    <AppShell
      selectedEngagementId={selectedEngagementId}
      onSelectEngagement={setSelectedEngagementId}
    >
      <CatalogPage engagementId={selectedEngagementId} />
    </AppShell>
  )
}

export default App
