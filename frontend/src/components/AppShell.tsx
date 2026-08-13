import { useEffect, useState, type ReactNode } from 'react'
import { getHealth, listEngagements } from '../api/catalog'
import type { Engagement } from '../types/catalog'
import { TabBar } from './TabBar'

const HEALTH_POLL_INTERVAL_MS = 30_000

interface AppShellProps {
  children: ReactNode
  selectedEngagementId: string | null
  onSelectEngagement: (engagementId: string) => void
}

export function AppShell({ children, selectedEngagementId, onSelectEngagement }: AppShellProps) {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [engagements, setEngagements] = useState<Engagement[]>([])

  useEffect(() => {
    let cancelled = false

    async function pollHealth() {
      try {
        const result = await getHealth()
        if (!cancelled) setHealthy(result.status === 'ok' && result.database === 'connected')
      } catch {
        if (!cancelled) setHealthy(false)
      }
    }

    pollHealth()
    const interval = setInterval(pollHealth, HEALTH_POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    listEngagements()
      .then(setEngagements)
      .catch(() => setEngagements([]))
  }, [])

  return (
    <div className="flex min-h-screen flex-col bg-neutral-50">
      <header className="flex items-center justify-between border-b border-neutral-200 bg-white px-6 py-4">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-neutral-900">Modernization Platform</h1>
          <HealthPill healthy={healthy} />
        </div>
        <label className="flex items-center gap-2 text-sm text-neutral-600">
          Engagement
          <select
            className="rounded border border-neutral-300 bg-white px-2 py-1.5 text-sm text-neutral-900"
            value={selectedEngagementId ?? ''}
            onChange={(event) => onSelectEngagement(event.target.value)}
          >
            {engagements.length === 0 && <option value="">No engagements</option>}
            {engagements.map((engagement) => (
              <option key={engagement.id} value={engagement.id}>
                {engagement.client_name}
              </option>
            ))}
          </select>
        </label>
      </header>
      <TabBar />
      <main className="flex-1 overflow-auto">{children}</main>
    </div>
  )
}

function HealthPill({ healthy }: { healthy: boolean | null }) {
  if (healthy === null) {
    return (
      <span className="rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs font-medium text-neutral-500">
        checking…
      </span>
    )
  }

  return healthy ? (
    <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-700">
      connected
    </span>
  ) : (
    <span className="rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-700">
      unreachable
    </span>
  )
}
