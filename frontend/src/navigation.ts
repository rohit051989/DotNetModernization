import type { TabKey } from './components/TabBar'

/** A page deep in the UI asks the app to show a tab (App.tsx listens), as the access-request count asks the header to
 * refresh: tabs are app state, not routes. */
export const OPEN_TAB = 'platform:open-tab'

export function openTab(tab: TabKey) {
  window.dispatchEvent(new CustomEvent<TabKey>(OPEN_TAB, { detail: tab }))
}
