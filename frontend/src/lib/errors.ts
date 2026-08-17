/**
 * Turning a failed request into something an analyst can act on.
 *
 * `ApiError` already separates "the backend said no" from "the backend never
 * heard us"; this maps those onto the status codes the backend actually
 * returns (see the error table in docs/architecture.md) so pages don't each
 * invent their own wording for a 403.
 */

import { ApiError } from '@/lib/http'
import { supabase } from '@/lib/supabase'

/**
 * Drop an expired session so the router bounces to login.
 *
 * An expired token is the one API failure the analyst cannot act on from the
 * page they are on, and the backend's 401 is what decides it — the browser
 * can't tell a revoked session from a valid one until it asks.
 */
export function signOutIfExpired(error: unknown): void {
  if (error instanceof ApiError && error.status === 401) {
    void supabase.auth.signOut()
  }
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.isNetworkError) {
      return 'Could not reach the API. Check that the backend is running and that this origin is in ALLOWED_ORIGINS.'
    }

    switch (error.status) {
      case 401:
        return 'Your session expired. Sign in again to continue.'
      case 403:
        return 'That conversation belongs to another user.'
      case 404:
        return 'That conversation no longer exists.'
      case 502:
        return 'The assistant is unavailable right now. Try again in a moment.'
    }
    // 422s and 500s are our bugs; showing the backend's `detail` beats a
    // generic apology when the person reading it can file the issue.
    return error.message
  }

  return error instanceof Error ? error.message : 'Something went wrong.'
}
