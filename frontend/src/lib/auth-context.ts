/**
 * The auth session, shared across the app.
 *
 * Context and hook live here, apart from the provider component, so Vite's fast
 * refresh keeps working — a module that exports both a component and other
 * values loses its refresh boundary.
 */

import type { Session } from '@supabase/supabase-js'
import { createContext, use } from 'react'

export interface AuthState {
  /** Null when signed out. Contains the access token used for API calls. */
  session: Session | null
  /** True until the stored session has been read — routes must not redirect before then. */
  loading: boolean
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const state = use(AuthContext)

  if (!state) {
    throw new Error('useAuth must be called inside <AuthProvider>.')
  }
  return state
}
