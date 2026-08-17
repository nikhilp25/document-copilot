/**
 * One thread's live conversation.
 *
 * `useChat` reads `initialMessages` once, at mount, so the route renders this
 * with `key={threadId}` — without that, switching threads would leave the
 * previous conversation's messages on screen. Everything after mount is the AI
 * SDK's: it owns the optimistic user message, the streamed assistant message,
 * and the status the input and indicator read.
 */

import { useChat } from '@ai-sdk/react'
import type { UIMessage } from 'ai'
import { useMemo } from 'react'

import { ChatInput } from '@/components/chat/chat-input'
import { MessageList } from '@/components/chat/message-list'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { chatTransport } from '@/lib/api'
import { describeError } from '@/lib/errors'

interface ChatPanelProps {
  threadId: string
  initialMessages: UIMessage[]
  /** The thread was just renamed or reordered by a completed turn. */
  onTurnComplete: () => void
}

export function ChatPanel({ threadId, initialMessages, onTurnComplete }: ChatPanelProps) {
  const transport = useMemo(() => chatTransport(threadId), [threadId])

  const { messages, sendMessage, status, error, stop, clearError } = useChat({
    id: threadId,
    messages: initialMessages,
    transport,
    // The backend titles an untitled thread from its first question, so the
    // sidebar entry only becomes recognisable once a turn lands.
    onFinish: onTurnComplete,
  })

  const busy = status === 'submitted' || status === 'streaming'

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <MessageList messages={messages} status={status} />

      {error && (
        <div className="mx-auto w-full max-w-4xl px-6 pb-3">
          <Alert variant="destructive">
            <AlertDescription className="flex items-center justify-between gap-4">
              <span>{describeError(error)}</span>
              {/* The question is already in the transcript and already
                  persisted, so recovery is just asking again. */}
              <Button variant="outline" size="sm" onClick={clearError}>
                Dismiss
              </Button>
            </AlertDescription>
          </Alert>
        </div>
      )}

      <ChatInput onSend={(text) => void sendMessage({ text })} onStop={stop} busy={busy} />
    </div>
  )
}
