/**
 * One turn in the transcript.
 *
 * An assistant turn is text plus citations, and both halves are rendered here:
 * every `[n]` the model wrote becomes a clickable marker, and the citations
 * repeat as labelled chips underneath. That pairing is the point — the marker
 * says which claim, the chip says which filing, and either one opens the
 * passage. A claim the analyst cannot trace is the failure this product exists
 * to prevent, so nothing else in the message is rendered as prose.
 *
 * A marker whose citation is missing stays literal text. The backend's
 * validator makes that impossible for a fresh answer, but the transcript can
 * hold turns written before it existed, and inventing a chip for them would be
 * exactly the wrong repair.
 */

import { Fragment, type ReactNode } from 'react'

import { CitationChip, CitationMarker } from '@/components/chat/citation-chip'
import {
  citationKey,
  citationsOf,
  type ChatMessage,
  type CitationData,
} from '@/lib/citations'
import { cn } from '@/lib/utils'

interface MessageBubbleProps {
  message: ChatMessage
  /** `citationKey` of the citation the source panel is open on, if any. */
  activeKey: string | null
  onSelectCitation: (citation: CitationData) => void
}

// Mirrors the backend validator's marker pattern, grouped form included:
// models reach for `[1, 2]` unprompted and the validator accepts it, so the
// renderer has to as well or a real citation silently stays literal text.
const MARKER = /\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]/g

export function MessageBubble({
  message,
  activeKey,
  onSelectCitation,
}: MessageBubbleProps) {
  const text = message.parts
    .filter((part) => part.type === 'text')
    .map((part) => part.text)
    .join('')

  const citations = citationsOf(message)
  const byIndex = new Map(citations.map((citation) => [citation.index, citation]))
  const isUser = message.role === 'user'

  return (
    <div className={cn('flex', isUser ? 'justify-end' : 'justify-start')}>
      <div className={cn('grid max-w-[46rem] gap-3', isUser && 'justify-items-end')}>
        <div
          className={cn(
            // `whitespace-pre-wrap` because the backend sends plain text and an
            // analyst's question may well have line breaks in it.
            'rounded-lg px-4 py-3 text-sm whitespace-pre-wrap',
            isUser ? 'bg-primary text-primary-foreground' : 'bg-muted',
          )}
        >
          {isUser
            ? text
            : withMarkers(text, byIndex, activeKey, onSelectCitation)}
        </div>

        {citations.length > 0 && (
          <div className="grid gap-1.5 px-1">
            <p className="text-muted-foreground text-xs font-medium">
              Sources ({citations.length})
            </p>
            <div className="flex flex-wrap gap-1.5">
              {citations.map((citation) => (
                <CitationChip
                  key={citationKey(citation)}
                  citation={citation}
                  active={citationKey(citation) === activeKey}
                  onSelect={onSelectCitation}
                />
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

/** The answer with its `[n]` markers swapped for buttons, prose untouched. */
function withMarkers(
  text: string,
  byIndex: Map<number, CitationData>,
  activeKey: string | null,
  onSelect: (citation: CitationData) => void,
): ReactNode {
  const nodes: ReactNode[] = []
  let cursor = 0

  // `matchAll` rather than `split` on the same pattern: the marker's index has
  // to survive to the button, and the text between markers has to survive
  // character for character.
  for (const match of text.matchAll(MARKER)) {
    const at = match.index

    nodes.push(text.slice(cursor, at))

    // A grouped marker becomes one button per source, so `[1, 2]` opens either
    // passage rather than making the analyst guess which one it meant.
    const indexes = match[1].split(',').map((index) => Number(index.trim()))

    for (const index of indexes) {
      const citation = byIndex.get(index)

      nodes.push(
        citation ? (
          <CitationMarker
            key={`${at}-${citation.index}`}
            citation={citation}
            active={citationKey(citation) === activeKey}
            onSelect={onSelect}
          />
        ) : (
          `[${index}]`
        ),
      )
    }

    cursor = at + match[0].length
  }

  nodes.push(text.slice(cursor))

  return nodes.map((node, index) => <Fragment key={index}>{node}</Fragment>)
}
