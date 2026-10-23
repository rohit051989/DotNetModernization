/**
 * The repository page's tabs, in groups (04-FRONTEND-SPEC.md "Repository page"). Only the selected tab's content is
 * shown; each tab has its own address, /repositories/<id>/<tab>, so a refresh stays on it, Back and Forward move between
 * tabs, and a link can open a repository on a tab.
 */

export const TABS = [
  { slug: 'overview', label: 'Overview', group: 'overview' },
  { slug: 'surface', label: 'Surface', group: 'discovery' },
  { slug: 'projects', label: 'Projects & fingerprint', group: 'discovery' },
  { slug: 'dependencies', label: 'Dependencies', group: 'discovery' },
  { slug: 'dependency-graph', label: 'Dependency graph', group: 'discovery' },
  { slug: 'impact', label: 'Impact', group: 'discovery' },
  { slug: 'tests', label: 'Tests', group: 'discovery' },
  { slug: 'work-list', label: 'Work list', group: 'modernization' },
  { slug: 'conversion', label: 'Conversion', group: 'modernization' },
  { slug: 'executions', label: 'Executions', group: 'activity' },
  { slug: 'details', label: 'Details', group: 'activity' },
] as const

export type TabSlug = (typeof TABS)[number]['slug']

export const GROUPS = [
  { key: 'overview', label: 'Overview' },
  { key: 'discovery', label: 'Discovery' },
  { key: 'modernization', label: 'Modernization' },
  { key: 'activity', label: 'Activity' },
] as const

export type GroupKey = (typeof GROUPS)[number]['key']

export const DEFAULT_TAB: TabSlug = 'overview'

export function isTab(value: string | null | undefined): value is TabSlug {
  return TABS.some((t) => t.slug === value)
}

export function groupOf(tab: TabSlug): GroupKey {
  return TABS.find((t) => t.slug === tab)!.group
}

export function tabsOf(group: GroupKey): (typeof TABS)[number][] {
  return TABS.filter((t) => t.group === group)
}

/** The sections the page used to jump to (release 6 and earlier, `#repo-…`), and the tab each now is. A link to an old
 * section opens its tab. */
export const LEGACY_SECTIONS: Record<string, TabSlug> = {
  'repo-overview': 'overview',
  'repo-surface': 'surface',
  'repo-hierarchy': 'dependency-graph',
  'repo-structure': 'projects',
  'repo-dependencies': 'dependencies',
  'repo-worklist': 'work-list',
  'repo-tests': 'tests',
  'repo-impact': 'impact',
  'repo-conversion': 'conversion',
  'repo-executions': 'executions',
  'repo-details': 'details',
}

/** The tab an old `#repo-…` anchor (or a Surface section's own anchor) points at, or null. */
export function tabForLegacyHash(hash: string): TabSlug | null {
  const id = hash.replace(/^#/, '')
  if (LEGACY_SECTIONS[id]) return LEGACY_SECTIONS[id]
  if (id.startsWith('surface:') || id.startsWith('surface-')) return 'surface'
  return null
}

// ---------- remembered in this browser ----------

function storage(kind: 'local' | 'session'): Storage | null {
  try {
    return kind === 'local' ? window.localStorage : window.sessionStorage
  } catch {
    return null
  }
}

/** Each repository's last tab, across visits. */
export function rememberedTab(repositoryId: string): TabSlug | null {
  const value = storage('local')?.getItem(`repo-tab:${repositoryId}`)
  return isTab(value) ? value : null
}

export function rememberTab(repositoryId: string, tab: TabSlug): void {
  try {
    storage('local')?.setItem(`repo-tab:${repositoryId}`, tab)
  } catch {
    // Not remembered: the next visit opens on Overview.
  }
}

/** Each tab's scroll position, for this browser tab's session. */
export function rememberedScroll(repositoryId: string, tab: TabSlug): number {
  return Number(storage('session')?.getItem(`repo-scroll:${repositoryId}:${tab}`) ?? 0) || 0
}

export function rememberScroll(repositoryId: string, tab: TabSlug, top: number): void {
  try {
    storage('session')?.setItem(`repo-scroll:${repositoryId}:${tab}`, String(Math.round(top)))
  } catch {
    // Not remembered.
  }
}

/** The tab to open: the one the address names; else an old section anchor's; else the repository's last tab; else Overview. */
export function initialTab(repositoryId: string, pathTab: string | null, hash: string): TabSlug {
  if (isTab(pathTab)) return pathTab
  return tabForLegacyHash(hash) ?? rememberedTab(repositoryId) ?? DEFAULT_TAB
}
