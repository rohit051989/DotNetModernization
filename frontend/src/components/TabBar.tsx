export type TabKey = 'catalog' | 'repositories' | 'applications' | 'dependencies' | 'waves' | 'dashboard'

interface Tab {
  key: TabKey
  label: string
  /** Master-catalog-only tabs (like 'catalog') never hide; engagement-only
   * tabs hide entirely in Master Catalog view rather than just disabling —
   * there is nothing engagement-scoped to show there. */
  engagementOnly: boolean
  implemented: boolean
}

const TABS: Tab[] = [
  { key: 'catalog', label: 'Catalog', engagementOnly: false, implemented: true },
  { key: 'repositories', label: 'Repositories', engagementOnly: true, implemented: true },
  { key: 'applications', label: 'Applications', engagementOnly: true, implemented: false },
  { key: 'dependencies', label: 'Dependencies', engagementOnly: true, implemented: false },
  { key: 'waves', label: 'Waves', engagementOnly: true, implemented: false },
  { key: 'dashboard', label: 'Dashboard', engagementOnly: true, implemented: true },
]

interface TabBarProps {
  activeTab: TabKey
  onSelectTab: (tab: TabKey) => void
  isMaster: boolean
}

export function TabBar({ activeTab, onSelectTab, isMaster }: TabBarProps) {
  const visibleTabs = TABS.filter((tab) => !tab.engagementOnly || !isMaster)

  return (
    <nav className="flex gap-1 border-b border-neutral-200 bg-white px-6">
      {visibleTabs.map((tab) => {
        if (!tab.implemented) {
          return (
            <span
              key={tab.key}
              title="Coming in a future build"
              className="cursor-not-allowed select-none border-b-2 border-transparent px-4 py-3 text-sm font-medium text-neutral-400"
            >
              {tab.label}
            </span>
          )
        }

        const active = tab.key === activeTab
        return (
          <button
            key={tab.key}
            type="button"
            onClick={() => onSelectTab(tab.key)}
            className={`border-b-2 px-4 py-3 text-sm font-medium ${
              active
                ? 'border-violet-600 text-neutral-900'
                : 'border-transparent text-neutral-500 hover:text-neutral-800'
            }`}
          >
            {tab.label}
          </button>
        )
      })}
    </nav>
  )
}
