import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { getAccessRequest, getMachine, requestAccess, signIn, type AccessRequestStatus, type MachineInfo, type Me } from '../api/auth'
import { ApiError } from '../api/client'

const input = 'mt-1 w-full rounded border border-neutral-300 px-2 py-1.5 text-sm'

/** Signing in (04-FRONTEND-SPEC.md, "Sign-in and roles"). The password, the Windows account this platform runs under,
 * and this machine must all match the person's registration; the page shows the account and machine it will check.
 * A password set by an admin is replaced here, at the first sign-in after it was set. Someone not registered asks for
 * access here, and a registered user asks to add this machine; the page says how their request stands. */
export function SignInPage({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [machine, setMachine] = useState<MachineInfo | null>(null)
  const [request, setRequest] = useState<AccessRequestStatus | null>(null)
  const [asking, setAsking] = useState(false)
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [again, setAgain] = useState('')
  const [mustChange, setMustChange] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    getMachine().then(setMachine, () => setMachine(null))
    getAccessRequest().then(setRequest, () => setRequest(null))
  }, [])
  useEffect(load, [load])

  useEffect(() => {
    if (request?.status === 'approved' && !login) setLogin(request.login)
  }, [request, login])

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

  const pending = request?.status === 'pending'
  const forMachine = machine?.registration === 'other_machines'
  const canAsk = !!machine && !machine.first_admin_needed && machine.registration !== 'this_machine' && !pending

  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 px-4">
      <div className="w-full max-w-sm space-y-4 rounded border border-neutral-200 bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold text-neutral-900">Modernization Platform</h1>
        {machine && (
          <p className="text-xs text-neutral-500">
            {asking ? 'Asking' : 'Signing in'} on <span className="font-mono text-neutral-700">{machine.hostname}</span>, where this platform runs as{' '}
            <span className="font-mono text-neutral-700">{machine.windows_account}</span>. Your registration must name both.
          </p>
        )}
        {machine?.first_admin_needed && (
          <p role="note" className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
            Nobody is registered yet. The first admin is created once, on this machine, from <span className="font-mono">backend\</span>:
            <code className="mt-1 block break-all font-mono">.venv\Scripts\python.exe -m app.users create-first-admin --login &lt;name&gt; --name "&lt;full name&gt;"</code>
          </p>
        )}
        <RequestStatus request={request} />
        {asking ? (
          <RequestForm
            forMachine={forMachine}
            hostname={machine?.hostname ?? ''}
            onDone={(made) => {
              setRequest(made)
              setAsking(false)
            }}
            onCancel={() => setAsking(false)}
          />
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <label className="block text-sm text-neutral-700">
              Sign-in name
              <input autoFocus required value={login} onChange={(e) => setLogin(e.target.value)} autoComplete="username" className={input} />
            </label>
            <label className="block text-sm text-neutral-700">
              Password
              <input required type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" className={input} />
            </label>
            {mustChange && (
              <>
                <label className="block text-sm text-neutral-700">
                  New password (12 characters or more)
                  <input required type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" className={input} />
                </label>
                <label className="block text-sm text-neutral-700">
                  New password, again
                  <input required type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" className={input} />
                </label>
              </>
            )}
            {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
            <button type="submit" disabled={busy}
              className="w-full rounded bg-violet-600 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-60">
              {busy ? 'Signing in…' : mustChange ? 'Set the new password and sign in' : 'Sign in'}
            </button>
            {canAsk && (
              <p className="text-center text-xs text-neutral-500">
                {forMachine ? 'Registered, but not for this machine? ' : 'Not registered? '}
                <button type="button" onClick={() => setAsking(true)} className="font-medium text-violet-700 hover:underline">
                  {forMachine ? 'Ask to add this machine' : 'Request access'}
                </button>
              </p>
            )}
          </form>
        )}
        <p className="text-[11px] text-neutral-400">
          Matching your Windows account and machine deters shared credentials. It is not a hard security boundary: the
          platform runs on your own machine.
        </p>
      </div>
    </div>
  )
}

/** How this machine's request stands: pending, rejected and why, or approved. */
function RequestStatus({ request }: { request: AccessRequestStatus | null }) {
  if (!request) return null
  const what = request.kind === 'machine' ? `to add ${request.hostname} to your registration` : 'for access'
  if (request.status === 'pending') {
    return (
      <p role="status" className="rounded border border-sky-200 bg-sky-50 p-2 text-xs text-sky-900">
        Your request {what} is pending, since {new Date(request.requested_at).toLocaleString()}. An admin approves or rejects it;
        until then you cannot sign in{request.kind === 'machine' ? ' on this machine' : ''}. Your sign-in name will be{' '}
        <span className="font-mono">{request.login}</span>.
      </p>
    )
  }
  if (request.status === 'rejected') {
    return (
      <p role="status" className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-900">
        Your request {what} was rejected{request.decided_at ? ` on ${new Date(request.decided_at).toLocaleString()}` : ''}
        {request.reason ? `: ${request.reason}` : ', with no reason given'}. You may ask again.
      </p>
    )
  }
  return (
    <p role="status" className="rounded border border-emerald-200 bg-emerald-50 p-2 text-xs text-emerald-900">
      Your request {what} was approved: sign in as <span className="font-mono">{request.login}</span>.
    </p>
  )
}

/** Asking for access: a name and a chosen password; or, to add this machine, the current password. The Windows
 * account and machine are this platform's, never typed. */
function RequestForm({ forMachine, hostname, onDone, onCancel }: { forMachine: boolean; hostname: string; onDone: (made: AccessRequestStatus) => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [again, setAgain] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    if (!forMachine && password !== again) {
      setError('The two passwords differ.')
      return
    }
    setBusy(true)
    try {
      onDone(await requestAccess(name.trim(), password))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not send the request.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4" aria-label="Request access">
      <p className="text-xs text-neutral-600">
        {forMachine
          ? `You are registered on other machines. Give your password to ask an admin to add this one (${hostname}).`
          : 'Give your name and choose a password. An admin approves your request; you then sign in with your Windows user name and this password.'}
      </p>
      {!forMachine && (
        <label className="block text-sm text-neutral-700">
          Your full name
          <input autoFocus required value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" className={input} />
        </label>
      )}
      <label className="block text-sm text-neutral-700">
        {forMachine ? 'Your password' : 'Choose a password (12 characters or more)'}
        <input required type="password" value={password} onChange={(e) => setPassword(e.target.value)}
          autoComplete={forMachine ? 'current-password' : 'new-password'} className={input} />
      </label>
      {!forMachine && (
        <label className="block text-sm text-neutral-700">
          The password, again
          <input required type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" className={input} />
        </label>
      )}
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={busy}
          className="flex-1 rounded bg-violet-600 py-2 text-sm font-medium text-white hover:bg-violet-700 disabled:opacity-60">
          {busy ? 'Sending…' : forMachine ? 'Ask to add this machine' : 'Request access'}
        </button>
        <button type="button" onClick={onCancel} className="rounded border border-neutral-300 px-3 text-sm text-neutral-700 hover:bg-neutral-50">
          Back
        </button>
      </div>
    </form>
  )
}
