import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { getMe, signOut as signOutCall, type Me } from '../api/auth'
import { SIGNED_OUT_EVENT } from '../api/client'

interface AuthState {
  /** The signed-in person; null when signed out; undefined while it is being asked. */
  me: Me | null | undefined
  setMe: (me: Me | null) => void
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

/** Who is signed in (04-FRONTEND-SPEC.md, "Sign-in and roles"). A call the backend answers SIGNED_OUT, a session that
 * ended or expired, signs the page out, and the sign-in page shows. */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined)

  useEffect(() => {
    let live = true
    getMe().then(
      (found) => live && setMe(found),
      () => live && setMe(null),
    )
    const signedOut = () => setMe(null)
    window.addEventListener(SIGNED_OUT_EVENT, signedOut)
    return () => {
      live = false
      window.removeEventListener(SIGNED_OUT_EVENT, signedOut)
    }
  }, [])

  const signOut = useCallback(async () => {
    try {
      await signOutCall()
    } finally {
      setMe(null)
    }
  }, [])

  return <AuthContext.Provider value={{ me, setMe, signOut }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const state = useContext(AuthContext)
  if (!state) throw new Error('useAuth outside AuthProvider')
  return state
}

/** Whether the signed-in person is an admin, for what the UI enables; the backend enforces it either way. Outside a
 * provider (a component test of something else), true: nothing is disabled. */
export function useIsAdmin(): boolean {
  const state = useContext(AuthContext)
  return state ? state.me?.role === 'admin' : true
}

/** The words shown on a control a developer cannot use. */
export const ADMIN_ONLY = 'Only an admin can do this.'
