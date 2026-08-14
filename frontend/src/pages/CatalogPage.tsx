import { useState } from 'react'
import { PatternList } from './catalog/PatternList'
import { PatternDetail } from './catalog/PatternDetail'
import { ClientPatternList } from './catalog/ClientPatternList'
import { ClientPatternDetail } from './catalog/ClientPatternDetail'
import { EmptyState } from '../components/EmptyState'
import type { Engagement } from '../types/catalog'

interface CatalogPageProps {
  engagements: Engagement[]
  /** null selects the Master Catalog view; otherwise the client view for that engagement. */
  selectedEngagementId: string | null
}

export function CatalogPage({ engagements, selectedEngagementId }: CatalogPageProps) {
  const [selectedPatternId, setSelectedPatternId] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  function handleCatalogChanged() {
    setRefreshToken((token) => token + 1)
  }

  function handlePatternRemoved() {
    setSelectedPatternId(null)
    handleCatalogChanged()
  }

  if (selectedEngagementId === null) {
    return (
      <div className="flex h-full">
        <PatternList
          selectedPatternId={selectedPatternId}
          onSelectPattern={setSelectedPatternId}
          refreshToken={refreshToken}
          onCatalogChanged={handleCatalogChanged}
        />
        <div className="flex-1 overflow-y-auto">
          {selectedPatternId ? (
            <PatternDetail
              patternId={selectedPatternId}
              refreshToken={refreshToken}
              onCatalogChanged={handleCatalogChanged}
              onDeleted={handlePatternRemoved}
            />
          ) : (
            <EmptyState
              title="Select a pattern"
              description="Choose a pattern from the list on the left to see its details."
            />
          )}
        </div>
      </div>
    )
  }

  const engagementName =
    engagements.find((engagement) => engagement.id === selectedEngagementId)?.client_name ??
    selectedEngagementId

  return (
    <div className="flex h-full">
      <ClientPatternList
        engagementId={selectedEngagementId}
        selectedPatternId={selectedPatternId}
        onSelectPattern={setSelectedPatternId}
        refreshToken={refreshToken}
        onCatalogChanged={handleCatalogChanged}
      />
      <div className="flex-1 overflow-y-auto">
        {selectedPatternId ? (
          <ClientPatternDetail
            engagementId={selectedEngagementId}
            engagementName={engagementName}
            patternId={selectedPatternId}
            refreshToken={refreshToken}
            onCatalogChanged={handleCatalogChanged}
            onDeleted={handlePatternRemoved}
          />
        ) : (
          <EmptyState
            title="Select a pattern"
            description="Choose a pattern from the list on the left to see its details."
          />
        )}
      </div>
    </div>
  )
}
