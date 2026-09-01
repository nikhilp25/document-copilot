/**
 * One thread's live conversation, and the source panel beside it.
 *
 * `useChat` reads `initialMessages` once, at mount, so the route renders this
 * with `key={threadId}` — without that, switching threads would leave the
 * previous conversation's messages on screen. Everything after mount is the AI
 * SDK's: it owns the optimistic user message, the streamed assistant message,
 * and the status the input and indicator read.
 *
 * Two pieces of state are ours. The selected citation, because the panel is
 * opened from a marker inside a message and closed from the panel itself; and
 * the latest progress line, because `data-status` parts are transient — the
 * SDK hands them to `onData` and never puts them in `messages`, which is what
 * keeps "Searching NVDA…" out of the saved transcript.
 */

import { useChat } from '@ai-sdk/react'
import { useMemo, useState } from 'react'

import { ChatInput } from '@/components/chat/chat-input'
import { MessageList } from '@/components/chat/message-list'
import { SourcePanel } from '@/components/chat/source-panel'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { chatTransport } from '@/lib/api'
import { citationKey, type ChatMessage, type CitationData } from '@/lib/citations'
import { describeError } from '@/lib/errors'

interface ChatPanelProps {
  threadId: string
  initialMessages: ChatMessage[]
  /** The thread was just renamed or reordered by a completed turn. */
  onTurnComplete: () => void
}

export function ChatPanel({ threadId, initialMessages, onTurnComplete }: ChatPanelProps) {
  const transport = useMemo(() => chatTransport(threadId), [threadId])
  const [selected, setSelected] = useState<CitationData | null>(null)
  const [progress, setProgress] = useState<string | null>(null)

  const { messages, sendMessage, status, error, stop, clearError } = useChat<ChatMessage>({
    id: threadId,
    messages: initialMessages,
    transport,
    onData: (part) => {
      if (part.type === 'data-status') {
        setProgress(part.data.label)
      }
    },
    // The backend titles an untitled thread from its first question, so the
    // sidebar entry only becomes recognisable once a turn lands.
    onFinish: () => {
      setProgress(null)
      onTurnComplete()
    },
    onError: () => setProgress(null),
  })

  const busy = status === 'submitted' || status === 'streaming'

  /** Clicking the open citation again closes the panel. */
  function toggleCitation(citation: CitationData) {
    setSelected((current) =>
      current && citationKey(current) === citationKey(citation) ? null : citation,
    )
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <MessageList
          messages={messages}
          status={status}
          progress={progress}
          activeKey={selected && citationKey(selected)}
          onSelectCitation={toggleCitation}
        />

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

        <ChatInput
          onSend={(text) => {
            // A new turn's narration starts empty rather than resuming the
            // last turn's final "Searching…" line.
            setProgress(null)
            void sendMessage({ text })
          }}
          onStop={stop}
          busy={busy}
        />
      </div>

      {selected && (
        <SourcePanel citation={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
