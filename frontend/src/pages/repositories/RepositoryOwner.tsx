import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import { assignOwner, listUsers, type User } from '../../api/users'
import { useIsAdmin } from '../../auth/AuthContext'
import { useToast } from '../../components/Toast'
import type { RepositorySummary } from '../../types/repositories'

/** Who owns the repository: they alone (with an admin) rescan it, prepare and verify its conversions, and delete it
 * (app.auth.policy). An admin assigns the owner here; a repository from before sign-in has none until then. */
export function RepositoryOwner({ repo, onChanged }: { repo: RepositorySummary; onChanged: () => void }) {
  const isAdmin = useIsAdmin()
  const { showToast } = useToast()
  const [users, setUsers] = useState<User[] | null>(null)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    if (editing && users === null) listUsers().then(setUsers, () => setUsers([]))
  }, [editing, users])

  async function choose(userId: string) {
    try {
      await assignOwner(repo.id, userId || null)
      showToast('success', userId ? 'Owner assigned.' : 'Owner removed: only admins act on it now.')
      setEditing(false)
      onChanged()
    } catch (err) {
      showToast('error', err instanceof ApiError ? err.message : 'Could not assign the owner.')
    }
  }

  const label = repo.owner_name ? `Owner: ${repo.owner_name}` : 'No owner: admins only'
  return (
    <span className="inline-flex items-center gap-1 text-xs">
      <span
        className={`rounded-full px-2 py-0.5 ${repo.owner_name ? 'bg-neutral-100 text-neutral-700' : 'bg-amber-100 text-amber-800'}`}
        title={repo.registered_host ? `Registered on ${repo.registered_host}` : 'Registered before sign-in existed'}
      >
        {label}
      </span>
      {isAdmin && !editing && (
        <button type="button" onClick={() => setEditing(true)} className="text-violet-700 hover:underline">
          {repo.owner_name ? 'Change' : 'Assign'}
        </button>
      )}
      {isAdmin && editing && (
        <select
          autoFocus
          aria-label="Owner"
          defaultValue={repo.owner_user_id ?? ''}
          onChange={(e) => void choose(e.target.value)}
          onBlur={() => setEditing(false)}
          className="rounded border border-neutral-300 px-1 py-0.5 text-xs"
        >
          <option value="">No owner (admins only)</option>
          {(users ?? []).filter((u) => u.active).map((u) => (
            <option key={u.id} value={u.id}>
              {u.name} ({u.role})
            </option>
          ))}
        </select>
      )}
    </span>
  )
}
