/**
 * Keeps React in sync with the Supabase session.
 *
 * One subscription for the whole app: Supabase persists the session to
 * localStorage and refreshes the access token in the background, and
 * `onAuthStateChange` is how those updates — plus sign-in, sign-out, and
 * confirmation links — reach the component tree.
 */

import type { Session } from '@supabase/supabase-js'
import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'

import { AuthContext } from '@/lib/auth-context'
import { supabase } from '@/lib/supabase'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Reads localStorage and refreshes an expired token before resolving, so
    // a returning user is signed in without a round trip to a login screen.
    void supabase.auth.getSession().then(({ data }) => {
      setSession(data.session)
      setLoading(false)
    })

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
      setLoading(false)
    })

    return () => subscription.unsubscribe()
  }, [])

  const value = useMemo(() => ({ session, loading }), [session, loading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
