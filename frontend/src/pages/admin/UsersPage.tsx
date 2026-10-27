import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import { createUser, listUsers, resetPassword, updateUser, type User } from '../../api/users'
import { useToast } from '../../components/Toast'

const EMPTY = { login: '', name: '', windows_account: '', role: 'developer' as const, hosts: '', temporary_password: '' }

function hostList(text: string): string[] {
  return text.split(/[,\s]+/).map((h) => h.trim()).filter(Boolean)
}

/** Users, for admins (docs/VDI-SETUP.md, "Users and sign-in"): who may sign in, under which Windows account, from which
 * machines, with which role. A password set here is temporary: the person chooses their own at their next sign-in. */
export function UsersPage() {
  const { showToast } = useToast()
  const [users, setUsers] = useState<User[] | null>(null)
  const [form, setForm] = useState<{ login: string; name: string; windows_account: string; role: 'admin' | 'developer'; hosts: string; temporary_password: string }>(EMPTY)
  const [error, setError] = useState<string | null>(null)
  const [editingHosts, setEditingHosts] = useState<{ id: string; text: string } | null>(null)

  const reload = useCallback(() => {
    listUsers().then(setUsers, () => setUsers([]))
  }, [])
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
                  <td>
                    <select value={user.role} aria-label={`Role of ${user.name}`}
                      onChange={(e) => void change(user, { role: e.target.value as User['role'] }, `${user.name} is now a ${e.target.value}.`)}
                      className="rounded border border-neutral-300 px-1 py-0.5 text-xs">
                      <option value="developer">developer</option>
                      <option value="admin">admin</option>
                    </select>
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
        <form onSubmit={add} className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {field('name', 'Full name')}
          {field('login', 'Sign-in name')}
          {field('windows_account', 'Windows account (DOMAIN\\user)', { placeholder: 'CORP\\jdoe' })}
          {field('hosts', 'Machines (hostnames, comma-separated)', { placeholder: 'DEVBOX-07' })}
          <label className="block text-xs text-neutral-600">
            Role
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as 'admin' | 'developer' })}
              className="mt-0.5 w-full rounded border border-neutral-300 px-2 py-1 text-sm">
              <option value="developer">developer</option>
              <option value="admin">admin</option>
            </select>
          </label>
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
