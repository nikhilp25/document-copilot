/**
 * The transcript, pinned to the newest turn.
 *
 * Autoscroll follows the message array rather than a scroll event: text deltas
 * arrive every few milliseconds, and re-measuring on each one costs more than
 * scrolling an already-bottomed container. It deliberately does not respect a
 * user who has scrolled up mid-answer — worth adding when answers get long
 * enough for that to bite.
 */

import type { ChatStatus } from 'ai'
import { useEffect, useRef } from 'react'

import { MessageBubble } from '@/components/chat/message-bubble'
import { StreamingIndicator } from '@/components/chat/streaming-indicator'
import type { ChatMessage, CitationData } from '@/lib/citations'

interface MessageListProps {
  messages: ChatMessage[]
  status: ChatStatus
  /** The newest `data-status` line from the running turn, if any. */
  progress: string | null
  /** `citationKey` of the citation the source panel is open on. */
  activeKey: string | null
  onSelectCitation: (citation: CitationData) => void
}

export function MessageList({
  messages,
  status,
  progress,
  activeKey,
  onSelectCitation,
}: MessageListProps) {
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: 'end' })
  }, [messages])

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto grid max-w-4xl gap-6 px-6 py-8">
        {messages.length === 0 ? (
          <p className="text-muted-foreground py-16 text-center text-sm">
            Ask a question about the filings to start this conversation.
          </p>
        ) : (
          messages.map((message) => (
            <MessageBubble
              key={message.id}
              message={message}
              activeKey={activeKey}
              onSelectCitation={onSelectCitation}
            />
          ))
        )}

        {/* 'submitted' is the gap before the first delta; from 'streaming' on,
            the answer itself shows progress. */}
        {status === 'submitted' && <StreamingIndicator label={progress} />}

        <div ref={bottom} />
      </div>
    </div>
  )
}
