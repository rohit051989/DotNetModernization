import { useEffect, useRef } from 'react'

/** Calls `callback` every `intervalMs` while `enabled`. Pauses while the tab
 * is hidden and resumes on visibility (docs/20-WORKFLOW-OBSERVABILITY-UI.md
 * Part D) — never accumulates a background timer that fires while hidden. */
export function usePolling(callback: () => void, intervalMs: number, enabled: boolean) {
  const savedCallback = useRef(callback)
  savedCallback.current = callback

  useEffect(() => {
    if (!enabled) return undefined

    let timer: ReturnType<typeof setTimeout> | null = null
    let stopped = false

    function schedule() {
      if (stopped || document.hidden) return
      timer = setTimeout(tick, intervalMs)
    }

    function tick() {
      timer = null
      if (stopped || document.hidden) return
      savedCallback.current()
      schedule()
    }

    function handleVisibility() {
      if (!document.hidden && !timer && !stopped) {
        schedule()
      }
    }

    schedule()
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [enabled, intervalMs])
}
