import { useState } from 'react'
import { AppShell } from './components/AppShell'
import { CatalogPage } from './pages/CatalogPage'
import { ToastProvider } from './components/Toast'

function App() {
  const [selectedEngagementId, setSelectedEngagementId] = useState<string | null>(null)

  return (
    <ToastProvider>
      <AppShell
        selectedEngagementId={selectedEngagementId}
        onSelectEngagement={setSelectedEngagementId}
      >
        <CatalogPage />
      </AppShell>
    </ToastProvider>
  )
}

export default App
