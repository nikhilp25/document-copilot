/**
 * One turn in the transcript.
 *
 * Only text parts render. The stream carries citation parts from Phase 6
 * onward, and those become chips with their own component in Phase 7 — showing
 * them as prose here would be exactly the untrustworthy rendering the product
 * exists to avoid.
 */

import type { UIMessage } from 'ai'

import { cn } from '@/lib/utils'

export function MessageBubble({ message }: { message: UIMessage }) {
  const text = message.parts
    .filter((part) => part.type === 'text')
    .map((part) => part.text)
    .join('')

  const isUser = message.role === 'user'

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          // `whitespace-pre-wrap` because the backend sends plain text and an
          // analyst's question may well have line breaks in it.
          'max-w-[46rem] rounded-lg px-4 py-3 text-sm whitespace-pre-wrap',
          isUser ? 'bg-primary text-primary-foreground' : 'bg-muted',
        )}
      >
        {text}
      </div>
    </div>
  )
}
