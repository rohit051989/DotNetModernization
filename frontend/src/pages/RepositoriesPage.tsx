import { useLayoutEffect, useRef, useState } from 'react'
import { RepositoryList } from './repositories/RepositoryList'
import { RepositoryDetailPage } from './repositories/RepositoryDetailPage'

interface RepositoriesPageProps {
  engagementId: string
  engagementName: string
  /** Owned by App.tsx so /repositories/<id> is a real, reloadable URL. */
  selectedRepositoryId: string | null
  onSelectRepository: (repositoryId: string | null) => void
  onNavigateToExecution: (executionId: string) => void
  onOpenEstateSoap?: (invocationId: string) => void
}

/** Engagement-scoped. Hidden entirely in Master Catalog view — see
 * 15-REPOSITORY-INGEST-UI.md Part F. App.tsx never mounts this component
 * without an engagement selected.
 *
 * The list and a repository's page take the whole width in turn. The list
 * stays mounted while a repository is open — only hidden — so its search,
 * filters and scroll position are exactly as left when Back returns to it. */
export function RepositoriesPage({
  engagementId,
  engagementName,
  selectedRepositoryId,
  onSelectRepository,
  onNavigateToExecution,
  onOpenEstateSoap,
}: RepositoriesPageProps) {
  const [refreshToken, setRefreshToken] = useState(0)

  // AppShell's <main> is the page scroller. A repository's page opens at
  // its top; the list's own position (it scrolls inside its pane) is kept
  // by RepositoryList, and main's is saved here and put back on return —
  // by the back link or the browser's Back.
  const listScrollTop = useRef(0)
  function openRepository(repositoryId: string | null) {
    if (repositoryId && !selectedRepositoryId) listScrollTop.current = document.querySelector('main')?.scrollTop ?? 0
    onSelectRepository(repositoryId)
  }
  useLayoutEffect(() => {
    document.querySelector('main')?.scrollTo({ top: selectedRepositoryId ? 0 : listScrollTop.current })
  }, [selectedRepositoryId])

  function handleChanged() {
    setRefreshToken((token) => token + 1)
  }

  function handleRemoved() {
    onSelectRepository(null)
    handleChanged()
  }

  return (
    <>
      <div className={selectedRepositoryId ? 'hidden' : 'flex h-full'}>
        <RepositoryList
          engagementId={engagementId}
          engagementName={engagementName}
          visible={!selectedRepositoryId}
          selectedRepositoryId={selectedRepositoryId}
          onSelectRepository={openRepository}
          onNavigateToExecution={onNavigateToExecution}
          refreshToken={refreshToken}
          onChanged={handleChanged}
        />
      </div>
      {selectedRepositoryId && (
        <RepositoryDetailPage
          key={selectedRepositoryId}
          repositoryId={selectedRepositoryId}
          refreshToken={refreshToken}
          onBack={() => onSelectRepository(null)}
          onChanged={handleChanged}
          onDeleted={handleRemoved}
          onNavigateToExecution={onNavigateToExecution}
          onOpenEstateSoap={onOpenEstateSoap}
        />
      )}
    </>
  )
}
