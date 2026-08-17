/**
 * The chat shell: sidebar on the left, the active thread on the right.
 *
 * This route owns the thread list because two children need it — the sidebar
 * renders it, and the thread route invalidates it when a completed turn names
 * an untitled thread.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Outlet, useNavigate } from 'react-router-dom'

import { ThreadSidebar } from '@/components/chat/thread-sidebar'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { createThread, listThreads, type Thread } from '@/lib/api'
import { describeError, signOutIfExpired } from '@/lib/errors'
import type { ChatOutletContext } from '@/pages/chat/outlet-context'

export function ChatLayout() {
  // Null means "not loaded yet" — distinct from an analyst with no threads,
  // which the sidebar has its own empty state for.
  const [threads, setThreads] = useState<Thread[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [creating, setCreating] = useState(false)
  // Bumped to re-run the load below. A counter rather than a callback so the
  // fetch lives in exactly one place and always cancels its predecessor.
  const [reload, setReload] = useState(0)
  const navigate = useNavigate()

  useEffect(() => {
    const controller = new AbortController()

    void (async () => {
      try {
        setThreads(await listThreads(controller.signal))
        setError(null)
      } catch (cause) {
        if (controller.signal.aborted) {
          return
        }
        signOutIfExpired(cause)
        setError(describeError(cause))
      }
    })()

    return () => controller.abort()
  }, [reload])

  const refreshThreads = useCallback(() => setReload((count) => count + 1), [])

  async function handleNewChat() {
    setCreating(true)
    try {
      const thread = await createThread()
      // Prepended rather than refetched: the new thread is the newest by
      // definition, and the analyst is about to be looking at it.
      setThreads((current) => [thread, ...(current ?? [])])
      setError(null)
      void navigate(`/chat/${thread.id}`)
    } catch (cause) {
      signOutIfExpired(cause)
      setError(describeError(cause))
    } finally {
      setCreating(false)
    }
  }

  const context = useMemo<ChatOutletContext>(() => ({ refreshThreads }), [refreshThreads])

  return (
    <div className="flex h-svh">
      <ThreadSidebar
        threads={threads}
        creating={creating}
        onNewChat={() => void handleNewChat()}
      />

      <main className="flex min-w-0 flex-1 flex-col">
        {error && (
          <div className="p-4">
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          </div>
        )}

        <Outlet context={context} />
      </main>
    </div>
  )
}
