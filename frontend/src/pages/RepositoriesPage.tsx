import { useState } from 'react'
import { EmptyState } from '../components/EmptyState'
import { RepositoryList } from './repositories/RepositoryList'
import { RepositoryDetailPanel } from './repositories/RepositoryDetailPanel'

interface RepositoriesPageProps {
  engagementId: string
  engagementName: string
}

/** Engagement-scoped. Hidden entirely in Master Catalog view — see
 * 15-REPOSITORY-INGEST-UI.md Part F. App.tsx never mounts this component
 * without an engagement selected. */
export function RepositoriesPage({ engagementId, engagementName }: RepositoriesPageProps) {
  const [selectedRepositoryId, setSelectedRepositoryId] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  function handleChanged() {
    setRefreshToken((token) => token + 1)
  }

  function handleRemoved() {
    setSelectedRepositoryId(null)
    handleChanged()
  }

  return (
    <div className="flex h-full">
      <RepositoryList
        engagementId={engagementId}
        engagementName={engagementName}
        selectedRepositoryId={selectedRepositoryId}
        onSelectRepository={setSelectedRepositoryId}
        refreshToken={refreshToken}
        onChanged={handleChanged}
      />
      <div className="flex-1 overflow-y-auto">
        {selectedRepositoryId ? (
          <RepositoryDetailPanel
            repositoryId={selectedRepositoryId}
            refreshToken={refreshToken}
            onChanged={handleChanged}
            onDeleted={handleRemoved}
          />
        ) : (
          <EmptyState
            title="Select a repository"
            description="Choose a repository from the list on the left to see its details, or register a new one."
          />
        )}
      </div>
    </div>
  )
}
