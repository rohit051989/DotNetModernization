/** Minimal, dependency-free URL routing for the one deep-linkable resource
 * this app has: an execution detail. Everything else (tab, engagement) stays
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
