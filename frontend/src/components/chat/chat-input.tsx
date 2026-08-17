/**
 * The question box.
 *
 * Enter sends and Shift+Enter breaks the line, which is what a chat UI has
 * trained everyone to expect — but the surrounding `<form>` still submits
 * normally, so the button works and the field stays keyboard-accessible.
 */

import { ArrowUp, Square } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface ChatInputProps {
  /** Resolves when the turn is accepted; the field clears optimistically. */
  onSend: (text: string) => void
  onStop: () => void
  busy: boolean
}

export function ChatInput({ onSend, onStop, busy }: ChatInputProps) {
  const [text, setText] = useState('')
  const trimmed = text.trim()

  function submit(event: React.FormEvent) {
    event.preventDefault()

    if (!trimmed || busy) {
      return
    }
    onSend(trimmed)
    setText('')
  }

  return (
    <form onSubmit={submit} className="mx-auto w-full max-w-4xl px-6 pb-6">
      <div className="bg-background focus-within:ring-ring/50 flex items-end gap-2 rounded-lg border p-2 focus-within:ring-[3px]">
        <Textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              submit(event)
            }
          }}
          placeholder="Ask about revenue, risk factors, segment margins…"
          rows={1}
          // The border and ring live on the wrapper so the button sits inside
          // the same focus outline as the field.
          className="max-h-40 min-h-10 resize-none border-0 bg-transparent shadow-none focus-visible:ring-0 dark:bg-transparent"
        />

        {busy ? (
          <Button type="button" size="icon" variant="secondary" onClick={onStop}>
            <Square />
            <span className="sr-only">Stop generating</span>
          </Button>
        ) : (
          <Button type="submit" size="icon" disabled={!trimmed}>
            <ArrowUp />
            <span className="sr-only">Send</span>
          </Button>
        )}
      </div>
    </form>
  )
}
