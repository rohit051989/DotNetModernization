import { useEffect, useState, type FormEvent } from 'react'
import { getMachine, signIn, type MachineInfo, type Me } from '../api/auth'
import { ApiError } from '../api/client'

/** Signing in (04-FRONTEND-SPEC.md, "Sign-in and roles"). The password, the Windows account this platform runs under,
 * and this machine must all match the person's registration; the page shows the account and machine it will check.
 * A password set by an admin is replaced here, at the first sign-in after it was set. */
export function SignInPage({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [machine, setMachine] = useState<MachineInfo | null>(null)
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [again, setAgain] = useState('')
  const [mustChange, setMustChange] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getMachine().then(setMachine, () => setMachine(null))
  }, [])

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (mustChange && newPassword !== again) {
      setError('The two new passwords differ.')
      return
    }
    setBusy(true)
    try {
      onSignedIn(await signIn(login.trim(), password, mustChange ? newPassword : undefined))
    } catch (err) {
      if (err instanceof ApiError && err.code === 'PASSWORD_CHANGE_REQUIRED') {
        setMustChange(true)
        setError(err.message)
      } else {
        setError(err instanceof Error ? err.message : 'Could not sign in.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded border border-neutral-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold text-neutral-900">Modernization Platform</h1>
        {machine && (
          <p className="text-xs text-neutral-500">
            Signing in on <span className="font-mono text-neutral-700">{machine.hostname}</span>, where this platform runs as{' '}
            <span className="font-mono text-neutral-700">{machine.windows_account}</span>. Your registration must name both.
          </p>
        )}
        {machine?.first_admin_needed && (
          <p role="note" className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
            Nobody is registered yet. The first admin is created once, on this machine, from <span className="font-mono">backend\</span>:
            <code className="mt-1 block break-all font-mono">.venv\Scripts\python.exe -m app.users create-first-admin --login &lt;name&gt; --name "&lt;full name&gt;"</code>
          </p>
        )}
        <label className="block text-sm text-neutral-700">
          Sign-in name
          <input autoFocus required value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username"
            className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm" />
        </label>
        <label className="block text-sm text-neutral-700">
          Password
          <input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
            className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm" />
        </label>
        {mustChange && (
          <>
            <label className="block text-sm text-neutral-700">
              New password (12 characters or more)
              <input required type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password"
                className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm" />
            </label>
            <label className="block text-sm text-neutral-700">
              New password, again
              <input required type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password"
                className="mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm" />
            </label>
          </>
        )}
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <button type="submit" disabled={busy}
          className="w-full rounded bg-violet-600 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-60">
          {busy ? 'Signing in…' : mustChange ? 'Set the new password and sign in' : 'Sign in'}
        </button>
        <p className="text-[11px] text-neutral-400">
          Matching your Windows account and machine deters shared credentials. It is not a hard security boundary: the
          platform runs on your own machine.
        </p>
      </form>
    </div>
  )
}
