/**
 * The transcript, pinned to the newest turn.
 *
 * Autoscroll follows the message array rather than a scroll event: text deltas
 * arrive every few milliseconds, and re-measuring on each one costs more than
 * scrolling an already-bottomed container. It deliberately does not respect a
 * user who has scrolled up mid-answer — worth adding when answers get long
 * enough for that to bite.
 */

import type { ChatStatus, UIMessage } from 'ai'
import { useEffect, useRef } from 'react'

import { MessageBubble } from '@/components/chat/message-bubble'
import { StreamingIndicator } from '@/components/chat/streaming-indicator'

interface MessageListProps {
  messages: UIMessage[]
  status: ChatStatus
}

export function MessageList({ messages, status }: MessageListProps) {
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto grid max-w-4xl gap-4 px-6 py-8">
        {messages.length === 0 ? (
          <p className="text-muted-foreground py-16 text-center text-sm">
            Ask a question about the filings to start this conversation.
          </p>
        ) : (
          messages.map((message) => <MessageBubble key={message.id} message={message} />)
        )}

        {/* 'submitted' is the gap before the first delta; from 'streaming' on,
            the answer itself shows progress. */}
        {status === 'submitted' && <StreamingIndicator />}

        <div ref={bottom} />
      </div>
    </div>
  )
}
