/**
 * Shared frame for the sign-in and sign-up pages: centered card, title, and a
 * slot for the form. Both pages are otherwise different enough to stay separate.
 */

import type { ReactNode } from 'react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

interface AuthCardProps {
  title: string
  description: string
  children: ReactNode
  /** Sign-in / sign-up cross-link. */
  footer: ReactNode
}

export function AuthCard({ title, description, children, footer }: AuthCardProps) {
  return (
    <div className="grid min-h-svh place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </CardHeader>
          <CardContent>{children}</CardContent>
        </Card>
        <p className="text-muted-foreground mt-6 text-center text-sm">{footer}</p>
      </div>
    </div>
  )
}
