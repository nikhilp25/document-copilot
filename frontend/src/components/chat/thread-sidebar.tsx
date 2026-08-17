/**
 * Past conversations, newest activity first.
 *
 * Presentational on purpose — the layout owns the thread list and the "new
 * chat" request, because the thread route needs to refresh that same list when
 * a turn names an untitled thread.
 */

import { MessageSquarePlus } from 'lucide-react'
import { NavLink } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import type { Thread } from '@/lib/api'
import { useAuth } from '@/lib/auth-context'
import { cn } from '@/lib/utils'
import { supabase } from '@/lib/supabase'

interface ThreadSidebarProps {
  /** Null while the first load is in flight. */
  threads: Thread[] | null
  creating: boolean
  onNewChat: () => void
}

export function ThreadSidebar({ threads, creating, onNewChat }: ThreadSidebarProps) {
  const { session } = useAuth()

  return (
    <aside className="bg-sidebar flex h-svh w-72 shrink-0 flex-col border-r">
      <div className="grid gap-3 p-4">
        <h1 className="text-sm font-semibold">Document Copilot</h1>
        <Button onClick={onNewChat} disabled={creating} size="sm" className="w-full">
          <MessageSquarePlus />
          {creating ? 'Starting…' : 'New chat'}
        </Button>
      </div>

      <Separator />

      <nav className="min-h-0 flex-1 overflow-y-auto p-2">
        {threads === null ? (
          <div className="grid gap-1 p-1">
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
            <Skeleton className="h-8" />
          </div>
        ) : threads.length === 0 ? (
          <p className="text-muted-foreground p-3 text-sm">
            No conversations yet. Start one to ask about the filings.
          </p>
        ) : (
          <ul className="grid gap-0.5">
            {threads.map((thread) => (
              <li key={thread.id}>
                <NavLink
                  to={`/chat/${thread.id}`}
                  className={({ isActive }) =>
                    cn(
                      'hover:bg-accent hover:text-accent-foreground block truncate rounded-md px-3 py-2 text-sm',
                      isActive && 'bg-accent text-accent-foreground font-medium',
                    )
                  }
                >
                  {/* Titles are derived from the first question, so an untitled
                      thread is one nobody has asked anything in yet. */}
                  {thread.title ?? 'New conversation'}
                </NavLink>
              </li>
            ))}
          </ul>
        )}
      </nav>

      <Separator />

      <div className="grid gap-2 p-4">
        <p className="text-muted-foreground truncate text-xs">{session?.user.email}</p>
        <Button variant="outline" size="sm" onClick={() => void supabase.auth.signOut()}>
          Sign out
        </Button>
      </div>
    </aside>
  )
}
