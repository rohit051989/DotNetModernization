import { useEffect, useState, type ReactNode } from 'react'
import { getHealth } from '../api/catalog'
import { getMe } from '../api/auth'
import { ACCESS_REQUESTS_CHANGED, listOnline, type OnlineEntry } from '../api/users'
import { ADMIN_ONLY, useAuth, useIsAdmin } from '../auth/AuthContext'
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
  const isAdmin = useIsAdmin()

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
            {/* Everyone signed in sees the master catalog and every engagement; only admins change them, and the
                backend enforces it (app.auth.policy). */}
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
          <button
            type="button"
            onClick={() => setCreating(true)}
            disabled={!isAdmin}
            title={isAdmin ? undefined : ADMIN_ONLY}
            className="whitespace-nowrap rounded border border-neutral-300 px-2 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            + New engagement
          </button>
          {isAdmin && <RequestsPill onOpen={() => onSelectTab('users')} />}
          <OnlinePill />
          <UserMenu />
        </div>
      </header>
      <TabBar activeTab={activeTab} onSelectTab={onSelectTab} isMaster={isMaster} isAdmin={isAdmin} />
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

const ONLINE_POLL_INTERVAL_MS = 60_000

/** For admins: access requests waiting for a decision, opening the Users tab. Nothing when none wait. */
function RequestsPill({ onOpen }: { onOpen: () => void }) {
  const [count, setCount] = useState(0)
  useEffect(() => {
    let cancelled = false
    const poll = () => getMe().then((me) => !cancelled && setCount(me.pending_access_requests ?? 0), () => undefined)
    poll()
    const interval = setInterval(poll, ONLINE_POLL_INTERVAL_MS)
    window.addEventListener(ACCESS_REQUESTS_CHANGED, poll)
    return () => {
      cancelled = true
      clearInterval(interval)
      window.removeEventListener(ACCESS_REQUESTS_CHANGED, poll)
    }
  }, [])
  if (count === 0) return null
  return (
    <button type="button" onClick={onOpen} title="Access requests waiting for a decision (Users)"
      className="whitespace-nowrap rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-900 hover:bg-amber-200">
      {count} access request{count === 1 ? '' : 's'}
    </button>
  )
}

/** Who is online, and on which machine: each machine with a running platform, and who is signed in there. */
function OnlinePill() {
  const [online, setOnline] = useState<OnlineEntry[] | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    let cancelled = false
    const poll = () => listOnline().then((found) => !cancelled && setOnline(found), () => !cancelled && setOnline(null))
    poll()
    const interval = setInterval(poll, ONLINE_POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])
  if (online === null) return null
  return (
    <span className="relative">
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        className="whitespace-nowrap rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-800 hover:bg-emerald-100">
        {online.length} online
      </button>
      {open && (
        <span role="dialog" aria-label="Who is online" className="absolute right-0 top-full z-40 mt-1 w-72 rounded border border-neutral-200 bg-white p-2 text-xs shadow-lg">
          {online.length === 0 && <span className="text-neutral-500">No platform is running.</span>}
          {online.map((entry) => (
            <span key={entry.host} className="flex justify-between gap-2 py-0.5">
              <span className="truncate text-neutral-800">{entry.user_name ?? 'nobody signed in'}</span>
              <span className="font-mono text-neutral-500">{entry.host}</span>
            </span>
          ))}
        </span>
      )}
    </span>
  )
}

function UserMenu() {
  const { me, signOut } = useAuth()
  if (!me) return null
  return (
    <span className="flex items-center gap-2 whitespace-nowrap text-xs text-neutral-600">
      <span title={`${me.windows_account} on ${me.hostname}`}>
        {me.name} <span className="text-neutral-400">· {me.role}</span>
      </span>
      <button type="button" onClick={() => void signOut()} className="rounded border border-neutral-300 px-2 py-1 hover:bg-neutral-50">
        Sign out
      </button>
    </span>
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
