/**
 * Gate for routes that require a signed-in analyst.
 *
 * This is a convenience, not a security boundary — the browser bundle is public
 * and every protected route's data comes from FastAPI, which verifies the JWT
 * on its own. What this buys us is not flashing a chat shell at a signed-out
 * user before the API returns 401.
 */

import { Navigate, Outlet, useLocation } from 'react-router-dom'

import { useAuth } from '@/lib/auth-context'

export function ProtectedRoute() {
  const { session, loading } = useAuth()
  const location = useLocation()

  // Reading the stored session is asynchronous. Redirecting during that window
  // would bounce every returning user to the login page on a hard refresh.
  if (loading) {
    return (
      <div className="text-muted-foreground grid min-h-svh place-items-center text-sm">
        Loading…
      </div>
    )
  }

  if (!session) {
    // `from` lets the login page return the user where they were headed.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
