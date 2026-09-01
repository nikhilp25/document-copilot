/**
 * One conversation, deep-linkable at `/chat/:threadId`.
 *
 * History loads here rather than inside the chat panel because `useChat` takes
 * its starting messages at mount — the panel can only be created once we have
 * them, which is also what makes a reload show the full transcript.
 */

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { ChatPanel } from '@/components/chat/chat-panel'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { getThread, toUIMessages } from '@/lib/api'
import type { ChatMessage } from '@/lib/citations'
import { describeError, signOutIfExpired } from '@/lib/errors'
import { useChatOutletContext } from '@/pages/chat/outlet-context'

/**
 * A load result, tagged with the thread it belongs to.
 *
 * The tag is what makes navigation safe: rather than clearing state when the
 * route param changes, a result for a different thread simply doesn't match
 * and the page reads as loading again.
 */
type LoadResult =
  | { threadId: string; status: 'loaded'; messages: ChatMessage[] }
  | { threadId: string; status: 'failed'; error: string }

export function ChatThreadPage() {
  const { threadId } = useParams<{ threadId: string }>()
  const { refreshThreads } = useChatOutletContext()
  const [result, setResult] = useState<LoadResult | null>(null)

  useEffect(() => {
    if (!threadId) {
      return
    }

    const controller = new AbortController()

    void (async () => {
      try {
        const detail = await getThread(threadId, controller.signal)
        setResult({ threadId, status: 'loaded', messages: toUIMessages(detail.messages) })
      } catch (cause) {
        if (controller.signal.aborted) {
          return
        }
        signOutIfExpired(cause)
        setResult({ threadId, status: 'failed', error: describeError(cause) })
      }
    })()

    return () => controller.abort()
  }, [threadId])

  const loaded = result?.threadId === threadId ? result : null

  if (loaded?.status === 'failed') {
    return (
      <div className="p-6">
        <Alert variant="destructive">
          <AlertDescription>{loaded.error}</AlertDescription>
        </Alert>
      </div>
    )
  }

  if (!threadId || !loaded) {
    return (
      <div className="text-muted-foreground grid flex-1 place-items-center text-sm">
        Loading conversation…
      </div>
    )
  }

  return (
    <ChatPanel
      // Forces a fresh `useChat` per thread; see the panel's docstring.
      key={threadId}
      threadId={threadId}
      initialMessages={loaded.messages}
      onTurnComplete={refreshThreads}
    />
  )
}
