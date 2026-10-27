import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import {
  ACCESS_REQUESTS_CHANGED,
  approveAccessRequest,
  createUser,
  listAccessRequests,
  listUsers,
  promoteUser,
  rejectAccessRequest,
  resetPassword,
  updateUser,
  type AccessRequest,
  type User,
} from '../../api/users'
import { LimitedList } from '../../components/LimitedList'
import { useToast } from '../../components/Toast'

const EMPTY = { login: '', name: '', windows_account: '', hosts: '', temporary_password: '' }

function hostList(text: string): string[] {
  return text.split(/[,\s]+/).map((h) => h.trim()).filter(Boolean)
}

/** Users, for admins (docs/VDI-SETUP.md, "Users and sign-in"): the access requests waiting for a decision, then who may
 * sign in, under which Windows account, from which machines, with which role. Approving a request, or registering
 * someone here, makes a developer; Make admin is the one way to make an admin, and is recorded. A password set here is
 * temporary: the person chooses their own at their next sign-in. */
export function UsersPage() {
  const { showToast } = useToast()
  const [users, setUsers] = useState<User[] | null>(null)
  const [requests, setRequests] = useState<AccessRequest[] | null>(null)
  const [form, setForm] = useState<{ login: string; name: string; windows_account: string; hosts: string; temporary_password: string }>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const [editingHosts, setEditingHosts] = useState<{ id: string; text: string } | null>(null)

  const reload = useCallback(() => {
    listUsers().then(setUsers, () => setUsers([]))
    listAccessRequests().then(setRequests, () => setRequests([]))
  }, [])

  async function decide(request: AccessRequest, approve: boolean) {
    let reason: string | null = null
    if (!approve) {
      const given = window.prompt(`Reject ${request.name}'s request. A reason, shown on their sign-in page (optional):`)
      if (given === null) return
      reason = given.trim() || null
    }
    try {
      if (approve) await approveAccessRequest(request.id)
      else await rejectAccessRequest(request.id, reason)
      showToast('success', approve
        ? request.kind === 'machine' ? `${request.hostname} added to ${request.name}'s machines.` : `${request.name} can sign in as ${request.login}, as a developer.`
        : `${request.name}'s request rejected.`)
      reload()
      // The header's count (AppShell) updates now, not at its next poll.
      window.dispatchEvent(new Event(ACCESS_REQUESTS_CHANGED))
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not decide the request.')
    }
  }

  async function promote(user: User) {
    if (!window.confirm(`Make ${user.name} an admin? Admins change everything: the master catalog, users, every repository.`)) return
    try {
      await promoteUser(user.id)
      showToast('success', `${user.name} is an admin now.`)
      reload()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not make them an admin.')
    }
  }
  useEffect(reload, [reload])

  async function add(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      const created = await createUser({ ...form, hosts: hostList(form.hosts) })
      showToast('success', `Registered ${created.name}. They choose their own password at their first sign-in.`)
      setForm(EMPTY)
      reload()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not register the user.')
    }
  }

  async function change(user: User, payload: Parameters<typeof updateUser>[1], done: string) {
    try {
      await updateUser(user.id, payload)
      showToast('success', done)
      reload()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not change the user.')
    }
  }

  async function reset(user: User) {
    const temporary = window.prompt(`A temporary password for ${user.name} (12 characters or more). It works once: they choose their own at their next sign-in.`)
    if (!temporary) return
    try {
      await resetPassword(user.id, temporary)
      showToast('success', `${user.name}'s password is reset; their sessions have ended.`)
      reload()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not reset the password.')
    }
  }

  const field = (name: keyof typeof EMPTY, label: string, extra: Record<string, unknown> = {}) => (
    <label className="block text-xs text-neutral-600">
      {label}
      <input required value={form[name]} onChange={(e) => setForm({ ...form, [name]: e.target.value })} {...extra}
        className="mt-0.5 w-full rounded border border-neutral-300 px-2 py-1 text-sm" />
    </label>
  )

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <AccessRequests requests={requests} onDecide={decide} />
      <section>
        <h2 className="text-base font-semibold text-neutral-900">Users</h2>
        <p className="text-xs text-neutral-500">
          A person signs in with their name and password, on a machine listed here, from a platform running under their
          own Windows account. Admins do everything; a developer registers repositories and acts on the ones they own.
        </p>
        {users === null ? (
          <p className="mt-3 text-sm text-neutral-400">Loading…</p>
        ) : (
          <table className="mt-3 w-full text-left text-sm">
            <thead className="text-xs text-neutral-500">
              <tr>
                <th className="py-1">Name</th><th>Sign-in</th><th>Windows account</th><th>Machines</th><th>Role</th><th>Owns</th><th />
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className={`border-t border-neutral-100 align-top ${user.active ? '' : 'text-neutral-400'}`}>
                  <td className="py-1.5">
                    {user.name}
                    {!user.active && <span className="ml-1 text-xs">(deactivated)</span>}
                    {user.must_change_password && <span className="ml-1 text-xs text-amber-700">(new password due)</span>}
                  </td>
                  <td className="font-mono text-xs">{user.login}</td>
                  <td className="font-mono text-xs">{user.windows_account}</td>
                  <td className="text-xs">
                    {editingHosts?.id === user.id ? (
                      <form onSubmit={(e) => { e.preventDefault(); void change(user, { hosts: hostList(editingHosts.text) }, `${user.name}'s machines saved.`); setEditingHosts(null) }}>
                        <input autoFocus value={editingHosts.text} onChange={(e) => setEditingHosts({ id: user.id, text: e.target.value })}
                          className="w-40 rounded border border-neutral-300 px-1 py-0.5 font-mono" aria-label={`Machines for ${user.name}`} />
                      </form>
                    ) : (
                      <button type="button" className="font-mono hover:underline" title="Change the machines"
                        onClick={() => setEditingHosts({ id: user.id, text: user.hosts.join(', ') })}>
                        {user.hosts.join(', ')}
                      </button>
                    )}
                  </td>
                  <td className="text-xs">
                    {user.role}
                    {user.role === 'developer' && user.active && (
                      <button type="button" className="ml-2 text-violet-700 hover:underline" onClick={() => void promote(user)}>
                        Make admin
                      </button>
                    )}
                    {user.role === 'admin' && (
                      <button type="button" className="ml-2 text-neutral-600 hover:underline"
                        onClick={() => void change(user, { role: 'developer' }, `${user.name} is a developer now.`)}>
                        Make developer
                      </button>
                    )}
                  </td>
                  <td className="text-xs">{user.repositories_owned}</td>
                  <td className="space-x-2 whitespace-nowrap text-xs">
                    <button type="button" className="text-violet-700 hover:underline" onClick={() => void reset(user)}>Reset password</button>
                    <button type="button" className="text-neutral-600 hover:underline"
                      onClick={() => void change(user, { active: !user.active }, `${user.name} ${user.active ? 'deactivated' : 'reactivated'}.`)}>
                      {user.active ? 'Deactivate' : 'Reactivate'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      <section className="rounded border border-neutral-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-neutral-900">Register a user</h3>
        <p className="text-xs text-neutral-500">
          Usually people ask for access from the sign-in page of their own platform instead. Either way they are registered as
          a developer; Make admin, above, makes an admin.
        </p>
        <form onSubmit={add} className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {field('name', 'Full name')}
          {field('login', 'Sign-in name')}
          {field('windows_account', 'Windows account (DOMAIN\\user)', { placeholder: 'CORP\\jdoe' })}
          {field('hosts', 'Machines (hostnames, comma-separated)', { placeholder: 'DEVBOX-07' })}
          {field('temporary_password', 'Temporary password (12+ characters)', { type: 'password', autoComplete: 'new-password' })}
          {error && <p role="alert" className="text-sm text-red-700 sm:col-span-3">{error}</p>}
          <div className="sm:col-span-3">
            <button type="submit" className="rounded bg-violet-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-violet-700">
              Register
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}

/** The requests from people's own sign-in pages: pending ones to decide, then the decided ones. */
function AccessRequests({ requests, onDecide }: { requests: AccessRequest[] | null; onDecide: (request: AccessRequest, approve: boolean) => void }) {
  if (requests === null) return null
  const pending = requests.filter((r) => r.status === 'pending')
  const decided = requests.filter((r) => r.status !== 'pending')
  return (
    <section aria-label="Access requests">
      <h2 className="text-base font-semibold text-neutral-900">
        Access requests <span className="font-normal text-neutral-500">({pending.length} pending)</span>
      </h2>
      <p className="text-xs text-neutral-500">
        Asked from the sign-in page of each person's own platform: their Windows account and machine come from that machine.
        Approving registers them as a developer, or adds the machine to their registration.
      </p>
      {pending.length === 0 ? (
        <p className="mt-2 text-sm text-neutral-400">No request is waiting.</p>
      ) : (
        <ul className="mt-2 divide-y divide-neutral-100 rounded border border-neutral-200 bg-white">
          {pending.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
              <span>
                <span className="font-medium text-neutral-900">{r.name}</span>{' '}
                <span className="text-neutral-500">
                  {r.kind === 'machine' ? `asks to add ${r.hostname}` : `asks for access, as ${r.login}`} · <span className="font-mono text-xs">{r.windows_account}</span> on{' '}
                  <span className="font-mono text-xs">{r.hostname}</span> · {new Date(r.requested_at).toLocaleString()}
                </span>
              </span>
              <span className="space-x-2 text-xs">
                <button type="button" onClick={() => onDecide(r, true)} className="rounded bg-violet-600 px-2 py-1 font-medium text-white hover:bg-violet-700">
                  Approve
                </button>
                <button type="button" onClick={() => onDecide(r, false)} className="rounded border border-neutral-300 px-2 py-1 text-neutral-700 hover:bg-neutral-50">
                  Reject
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      {decided.length > 0 && (
        <details className="mt-2 text-xs text-neutral-600">
          <summary className="cursor-pointer">Decided ({decided.length})</summary>
          <LimitedList items={decided} name={(r) => [r.name, r.windows_account, r.hostname]} noun="requests" className="mt-1">
            {(visible) => (
              <ul className="space-y-0.5">
                {visible.map((r) => (
                  <li key={r.id}>
                    {r.name} ({r.kind === 'machine' ? `add ${r.hostname}` : 'access'}): <span className="font-medium">{r.status}</span>
                    {r.decided_by && ` by ${r.decided_by}`}
                    {r.decided_at && `, ${new Date(r.decided_at).toLocaleString()}`}
                    {r.reason && ` — ${r.reason}`}
                  </li>
                ))}
              </ul>
            )}
          </LimitedList>
        </details>
      )}
    </section>
  )
}
