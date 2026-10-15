import { useEffect, useState, type ReactNode } from 'react'
import { getHealth } from '../api/catalog'
import type { Engagement } from '../types/catalog'
import { NewEngagementDrawer } from './NewEngagementDrawer'
import { TabBar, type TabKey } from './TabBar'

const HEALTH_POLL_INTERVAL_MS = 30_000
const MASTER_VALUE = ''

interface AppShellProps {
  children: ReactNode
  engagements: Engagement[]
  /** null selects the Master Catalog view. */
  selectedEngagementId: string | null
  onSelectEngagement: (engagementId: string | null) => void
  /** A new engagement was created: add it to the list and select it. */
  onEngagementCreated: (engagement: Engagement) => void
  activeTab: TabKey
  onSelectTab: (tab: TabKey) => void
}

export function AppShell({
  children,
  engagements,
  selectedEngagementId,
  onSelectEngagement,
  onEngagementCreated,
  activeTab,
  onSelectTab,
}: AppShellProps) {
  const [healthy, setHealthy] = useState<boolean | null>(null)
  const [creating, setCreating] = useState(false)

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

  const isMaster = selectedEngagementId === null

  return (
    <div className="flex h-screen flex-col bg-neutral-50">
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-neutral-200 bg-white px-4 py-3 sm:px-6 sm:py-4">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="truncate text-base font-semibold text-neutral-900 sm:text-lg">Modernization Platform</h1>
          <HealthPill healthy={healthy} />
        </div>
        <div className="flex min-w-0 items-center gap-2">
          <ScopePill isMaster={isMaster} />
          <label className="flex min-w-0 items-center gap-2 text-sm text-neutral-600">
            View
            {/* TODO: gate the Master Catalog option behind an admin check once auth
                exists — non-admins should not see it at all (04-FRONTEND-SPEC.md,
                "Future: access control"). */}
            <select
              className={`min-w-0 max-w-[12rem] rounded border px-2 py-1.5 text-sm focus:outline-none sm:max-w-none ${
                isMaster
                  ? 'border-violet-300 bg-violet-50 text-violet-900'
                  : 'border-blue-300 bg-blue-50 text-blue-900'
              }`}
              value={selectedEngagementId ?? MASTER_VALUE}
              onChange={(event) => onSelectEngagement(event.target.value || null)}
            >
              <option value={MASTER_VALUE}>Master Catalog</option>
              {engagements.map((engagement) => (
                <option key={engagement.id} value={engagement.id}>
                  {engagement.client_name}
                </option>
              ))}
            </select>
          </label>
          {/* TODO: gate creating an engagement behind an admin check once auth exists
              (04-FRONTEND-SPEC.md, "Future: access control"). */}
          <button
            type="button"
            onClick={() => setCreating(true)}
            className="whitespace-nowrap rounded border border-neutral-300 px-2 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
          >
            + New engagement
          </button>
        </div>
      </header>
      <TabBar activeTab={activeTab} onSelectTab={onSelectTab} isMaster={isMaster} />
      {/* The one page scroller: bounded, so a page's sticky bars and its
          panes' own scrollers (h-full + overflow-y-auto) work as designed. */}
      <main className="min-h-0 flex-1 overflow-auto">{children}</main>
      {creating && (
        <NewEngagementDrawer
          onClose={() => setCreating(false)}
          onCreated={(engagement) => {
            setCreating(false)
            onEngagementCreated(engagement)
          }}
        />
      )}
    </div>
  )
}

function ScopePill({ isMaster }: { isMaster: boolean }) {
  return isMaster ? (
    <span className="rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-violet-700">
      MASTER
    </span>
  ) : (
    <span className="rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-semibold tracking-wide text-blue-700">
      CLIENT
    </span>
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
