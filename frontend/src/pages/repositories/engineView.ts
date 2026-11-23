import { useSyncExternalStore } from 'react'
import type { ConversionEngine } from '../../types/catalog'

/** Which engine's inputs and runbook the Conversion tab shows (36-COPILOT-ENHANCED-CONVERSION Part Q): every conversion
 * is prepared for both, and which one does the work depends on what is installed on this machine, so the choice is
 * remembered per browser, never stored on the repository. GitHub Copilot until one is chosen. */
const STORAGE_KEY = 'conversion:engine-view'
const listeners = new Set<() => void>()
let remembered: ConversionEngine | null = null

function stored(): ConversionEngine | null {
  try {
    const value = window.localStorage.getItem(STORAGE_KEY)
    return value === 'github-copilot' || value === 'claude-code' ? value : null
  } catch {
    return null
  }
}

export function setEngineView(engine: ConversionEngine) {
  try {
    window.localStorage.setItem(STORAGE_KEY, engine)
  } catch {
    // Storage blocked: the choice lasts until the page is reloaded.
  }
  remembered = engine
  listeners.forEach((listener) => listener())
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useEngineView(): ConversionEngine {
  return useSyncExternalStore(subscribe, () => remembered ?? stored() ?? 'github-copilot')
}

/** For tests: forget the remembered choice. */
export function resetEngineViewForTests() {
  remembered = null
}
