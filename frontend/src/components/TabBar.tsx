export type TabKey = 'catalog' | 'repositories' | 'pattern-candidates' | 'applications' | 'dependencies' | 'waves' | 'dashboard' | 'workflow' | 'admin'

interface Tab {
  key: TabKey
  label: string
  /** Master-catalog-only tabs (like 'catalog') never hide; engagement-only
   * tabs hide entirely in Master Catalog view rather than just disabling —
   * there is nothing engagement-scoped to show there. */
  engagementOnly: boolean
  /** The mirror image: hidden whenever an engagement IS selected —
   * 23-WORKFLOW-ADMINISTRATION.md Part C: "New tab, visible only in Master
   * Catalog view." There is nothing to gate behind auth yet
   * (04-FRONTEND-SPEC.md "Future: access control"); see the TODO on the tab
   * itself and at the global policy mutations. */
  masterOnly: boolean
  implemented: boolean
}

const TABS: Tab[] = [
  { key: 'catalog', label: 'Catalog', engagementOnly: false, masterOnly: false, implemented: true },
  // TODO: gate this tab behind an admin check once auth exists — non-admins
  // should not see it at all (04-FRONTEND-SPEC.md, "Future: access control").
  { key: 'admin', label: 'Workflow Administration', engagementOnly: false, masterOnly: true, implemented: true },
  { key: 'repositories', label: 'Repositories', engagementOnly: true, masterOnly: false, implemented: true },
  // Step 5's output, and the surface step 6's decision actions will land
  // on (26-STEP-005-PATTERN-DISCOVERY.md).
  { key: 'pattern-candidates', label: 'Pattern Candidates', engagementOnly: true, masterOnly: false, implemented: true },
  { key: 'applications', label: 'Applications', engagementOnly: true, masterOnly: false, implemented: false },
  { key: 'dependencies', label: 'Dependencies', engagementOnly: true, masterOnly: false, implemented: false },
  { key: 'waves', label: 'Waves', engagementOnly: true, masterOnly: false, implemented: false },
  { key: 'dashboard', label: 'Dashboard', engagementOnly: true, masterOnly: false, implemented: true },
  { key: 'workflow', label: 'Workflow', engagementOnly: true, masterOnly: false, implemented: true },
]

interface TabBarProps {
  activeTab: TabKey
  onSelectTab: (tab: TabKey) => void
  isMaster: boolean
}

export function TabBar({ activeTab, onSelectTab, isMaster }: TabBarProps) {
  const visibleTabs = TABS.filter((tab) => (!tab.engagementOnly || !isMaster) && (!tab.masterOnly || isMaster))

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
