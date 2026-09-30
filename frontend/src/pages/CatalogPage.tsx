import { useCallback, useState } from 'react'
import { ItemList } from './catalog/ItemList'
import { ItemDetail } from './catalog/ItemDetail'
import { ExtractorBacklogView } from './catalog/ExtractorBacklogView'
import { SignalIndexView } from './catalog/SignalIndexView'
import { EmptyState } from '../components/EmptyState'
import type { Engagement } from '../types/catalog'

interface CatalogPageProps {
  engagements: Engagement[]
  /** null selects the Master Catalog view; otherwise the client view for that engagement. */
  selectedEngagementId: string | null
}

type MasterSection = 'items' | 'signals' | 'backlog'

/** The item catalog — 28-ITEM-AND-CONVERSION-MODEL.md. Master view: the
 * client-agnostic items, their resolutions and the extractor backlog, all
 * editable. Client view: the same items read-only, plus the engagement's
 * decision per item (which replaces the old lifecycle steps 13–15). */
export function CatalogPage({ engagements, selectedEngagementId }: CatalogPageProps) {
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const [section, setSection] = useState<MasterSection>('items')
  /** The signal highlighted in the Signals sub-tab — set when navigating from an item's Signals section. */
  const [selectedSignal, setSelectedSignal] = useState<string | null>(null)
  const [saveWarnings, setSaveWarnings] = useState<{ itemId: string; warnings: string[] } | null>(null)

  const isMaster = selectedEngagementId === null
  const engagement: Engagement | null = isMaster
    ? null
    : (engagements.find((e) => e.id === selectedEngagementId) ?? {
        // Engagements load asynchronously in App.tsx; until they arrive, a
        // minimal stand-in keeps the view usable. target_platform is unknown,
        // so the client-side Linux hint stays quiet (the server still warns).
        id: selectedEngagementId,
        client_name: selectedEngagementId,
        description: null,
        target_platform: null,
        default_posture: '',
        status: 'active',
        created_at: '',
        updated_at: '',
        deleted_at: null,
        deleted_by: null,
      })

  const handleCatalogChanged = useCallback(() => setRefreshToken((token) => token + 1), [])

  const handleItemSaved = useCallback((itemId: string, warnings: string[]) => {
    setSaveWarnings(warnings.length > 0 ? { itemId, warnings } : null)
    setSelectedItemId(itemId)
    setRefreshToken((token) => token + 1)
  }, [])

  function handleSelectItem(itemId: string) {
    setSelectedItemId(itemId)
    setSection('items')
  }

  function handleSelectSignal(name: string) {
    setSelectedSignal(name)
    setSection('signals')
  }

  // The Signals view is read-only and client-agnostic, so the client view has
  // it too: signal names in an item's detection link there from either view.
  // The extractor backlog is master-only.
  const activeSection: MasterSection = !isMaster && section === 'backlog' ? 'items' : section
  const showBacklog = activeSection === 'backlog'
  const showSignals = activeSection === 'signals'
  const tabs: { key: MasterSection; label: string }[] = [
    { key: 'items', label: 'Items' },
    { key: 'signals', label: 'Signals' },
    ...(isMaster ? [{ key: 'backlog' as const, label: 'Extractor backlog & coverage' }] : []),
  ]

  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-1 border-b border-neutral-200 bg-white px-4">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setSection(tab.key)}
            className={`border-b-2 px-3 py-2 text-sm font-medium ${
              activeSection === tab.key
                ? 'border-violet-600 text-violet-700'
                : 'border-transparent text-neutral-500 hover:text-neutral-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {showSignals ? (
        <div className="flex-1 overflow-y-auto">
          <SignalIndexView
            refreshToken={refreshToken}
            selectedSignal={selectedSignal}
            onSelectSignal={setSelectedSignal}
            onSelectItem={handleSelectItem}
          />
        </div>
      ) : showBacklog ? (
        <div className="flex-1 overflow-y-auto">
          <ExtractorBacklogView
            refreshToken={refreshToken}
            onSelectItem={handleSelectItem}
            onOpenSignals={() => setSection('signals')}
            onSelectSignal={handleSelectSignal}
          />
        </div>
      ) : (
        <div className="flex min-h-0 flex-1">
          <ItemList
            engagementId={selectedEngagementId}
            selectedItemId={selectedItemId}
            onSelectItem={setSelectedItemId}
            refreshToken={refreshToken}
            onItemCreated={handleItemSaved}
          />
          <div className="flex-1 overflow-y-auto">
            {selectedItemId ? (
              <ItemDetail
                key={`${selectedEngagementId ?? 'master'}:${selectedItemId}`}
                itemId={selectedItemId}
                engagement={engagement}
                refreshToken={refreshToken}
                onCatalogChanged={handleCatalogChanged}
                saveWarnings={saveWarnings?.itemId === selectedItemId ? saveWarnings.warnings : []}
                onDismissSaveWarnings={() => setSaveWarnings(null)}
                onItemSaved={handleItemSaved}
                onSelectSignal={handleSelectSignal}
              />
            ) : (
              <EmptyState title="Select an item" description="Choose a catalog item from the list on the left." />
            )}
          </div>
        </div>
      )}
    </div>
  )
}
