/** Minimal, dependency-free URL routing for the deep-linkable resources:
 * an execution detail and a repository detail. Everything else (tab, engagement) stays
 * plain component state, matching the rest of the app — see
 * docs/20-WORKFLOW-OBSERVABILITY-UI.md Part C: "Use real routes ... rather
 * than tab state, so an execution can be linked to and reloaded directly." */

const EXECUTION_PATH_RE = /^\/workflow\/executions\/([^/]+)\/?$/

export function parseExecutionIdFromLocation(): string | null {
  const match = EXECUTION_PATH_RE.exec(window.location.pathname)
  return match ? decodeURIComponent(match[1]) : null
}

export function pushExecutionRoute(executionId: string): void {
  const path = `/workflow/executions/${encodeURIComponent(executionId)}`
  if (window.location.pathname !== path) {
    window.history.pushState({}, '', path)
  }
}

export function pushRootRoute(): void {
  if (window.location.pathname !== '/') {
    window.history.pushState({}, '', '/')
  }
}

const REPOSITORY_PATH_RE = /^\/repositories\/([^/]+)(?:\/([a-z-]+))?\/?$/

/** A repository detail opens as a page of its own, in the same tab, like an
 * execution — so it can be linked to, reloaded and left with Back. Each of its
 * tabs has its own address: /repositories/<id>/<tab> (release 7). */
export function parseRepositoryIdFromLocation(): string | null {
  return parseRepositoryRoute()?.repositoryId ?? null
}

/** The repository and the tab the address names; the tab is null when the address names none. */
export function parseRepositoryRoute(): { repositoryId: string; tab: string | null } | null {
  const match = REPOSITORY_PATH_RE.exec(window.location.pathname)
  return match ? { repositoryId: decodeURIComponent(match[1]), tab: match[2] ?? null } : null
}

export function repositoryPath(repositoryId: string, tab?: string | null): string {
  return `/repositories/${encodeURIComponent(repositoryId)}${tab ? `/${tab}` : ''}`
}

/** Opens a repository. Leaving the tab out lets the page choose (the last tab, else Overview) and replace the address. */
export function pushRepositoryRoute(repositoryId: string, tab?: string | null): void {
  const path = repositoryPath(repositoryId, tab)
  if (window.location.pathname !== path) {
    window.history.pushState({}, '', path)
  }
}

/** The page's own tab changes: `replace` for one the page chose itself (a bare or old address), a new history entry
 * for one the person chose, so Back and Forward move between tabs. */
export function setRepositoryTabRoute(repositoryId: string, tab: string, replace: boolean): void {
  const path = repositoryPath(repositoryId, tab)
  if (window.location.pathname === path && !window.location.hash) return
  if (replace) window.history.replaceState({}, '', path)
  else window.history.pushState({}, '', path)
}
