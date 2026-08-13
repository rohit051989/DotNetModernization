interface Tab {
  key: string
  label: string
  disabled: boolean
}

const TABS: Tab[] = [
  { key: 'catalog', label: 'Catalog', disabled: false },
  { key: 'repositories', label: 'Repositories', disabled: true },
  { key: 'applications', label: 'Applications', disabled: true },
  { key: 'dependencies', label: 'Dependencies', disabled: true },
  { key: 'waves', label: 'Waves', disabled: true },
  { key: 'dashboard', label: 'Dashboard', disabled: true },
]

export function TabBar() {
  return (
    <nav className="flex gap-1 border-b border-neutral-200 bg-white px-6">
      {TABS.map((tab) =>
        tab.disabled ? (
          <span
            key={tab.key}
            title="Coming in platform build"
            className="cursor-not-allowed select-none border-b-2 border-transparent px-4 py-3 text-sm font-medium text-neutral-400"
          >
            {tab.label}
          </span>
        ) : (
          <span
            key={tab.key}
            className="border-b-2 border-violet-600 px-4 py-3 text-sm font-medium text-neutral-900"
          >
            {tab.label}
          </span>
        ),
      )}
    </nav>
  )
}
