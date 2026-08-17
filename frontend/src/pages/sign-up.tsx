/**
 * Email sign-up. No SSO — analysts get an email/password account or nothing.
 */

import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'

import { AuthCard } from '@/components/auth-card'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/lib/auth-context'
import { supabase } from '@/lib/supabase'

/** Supabase's own floor. Enforced here too so the failure is inline, not a round trip. */
const MIN_PASSWORD_LENGTH = 6

export function SignUpPage() {
  const { session } = useAuth()
  const [error, setError] = useState<string | null>(null)
  const [confirmationSentTo, setConfirmationSentTo] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (session) {
    return <Navigate to="/" replace />
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)

    const form = new FormData(event.currentTarget)
    const email = String(form.get('email')).trim()
    const password = String(form.get('password'))
    const confirmPassword = String(form.get('confirmPassword'))

    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setSubmitting(true)
    const { data, error: signUpError } = await supabase.auth.signUp({ email, password })
    setSubmitting(false)

    if (signUpError) {
      setError(signUpError.message)
      return
    }

    // Two shapes come back, depending on whether "Confirm email" is on in the
    // Supabase dashboard: a live session (confirmation off) means the auth
    // listener signs the user in and the redirect above takes over; no session
    // means a confirmation link is in flight and there is nothing to do here
    // but say so.
    if (!data.session) {
      setConfirmationSentTo(email)
    }
  }

  if (confirmationSentTo) {
    return (
      <AuthCard
        title="Check your email"
        description={`We sent a confirmation link to ${confirmationSentTo}. Open it to finish setting up your account.`}
        footer={<Link to="/login">Back to sign in</Link>}
      >
        <p className="text-muted-foreground text-sm">
          The link expires after 24 hours. If it does not arrive, check spam or sign up again.
        </p>
      </AuthCard>
    )
  }

  return (
    <AuthCard
      title="Create an account"
      description="Use your work email to get access to the filing assistant."
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="text-foreground underline underline-offset-4">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="grid gap-4">
        <div className="grid gap-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder="analyst@driftwood.com"
            required
          />
        </div>

        <div className="grid gap-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            required
          />
        </div>

        <div className="grid gap-2">
          <Label htmlFor="confirmPassword">Confirm password</Label>
          <Input
            id="confirmPassword"
            name="confirmPassword"
            type="password"
            autoComplete="new-password"
            minLength={MIN_PASSWORD_LENGTH}
            required
          />
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button type="submit" disabled={submitting} className="w-full">
          {submitting ? 'Creating account…' : 'Create account'}
        </Button>
      </form>
    </AuthCard>
  )
}
