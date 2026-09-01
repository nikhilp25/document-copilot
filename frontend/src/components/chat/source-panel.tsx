/**
 * The passage behind one citation.
 *
 * Two layers, deliberately in this order. The quote comes from the citation
 * itself, so it is on screen the instant the analyst clicks and stays there
 * even if the fetch fails — the excerpt is the claim's evidence and must never
 * depend on a second request. The surrounding filing text is fetched, and is
 * what turns "it says this" into "and here is what it says around it": chunks
 * can start mid-argument, and some carry table-serialisation noise that reads
 * as nonsense in isolation.
 *
 * A 404 means the corpus was re-ingested after this answer was written. The
 * quote was snapshotted with the message, so it is still exactly what the
 * filing said; only the chunk it was read from has a new id.
 */

import { ExternalLink, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Skeleton } from '@/components/ui/skeleton'
import { getPassage, type Passage } from '@/lib/api'
import {
  filingLabel,
  formatFilingDate,
  sectionLabel,
  type CitationData,
} from '@/lib/citations'
import { describeError, signOutIfExpired } from '@/lib/errors'
import { ApiError } from '@/lib/http'

interface SourcePanelProps {
  citation: CitationData
  onClose: () => void
}

/** Tagged with its chunk so a result for the previous citation can't land. */
type LoadResult =
  | { chunkId: string; status: 'loaded'; passage: Passage }
  | { chunkId: string; status: 'failed'; error: string }

export function SourcePanel({ citation, onClose }: SourcePanelProps) {
  const [result, setResult] = useState<LoadResult | null>(null)
  const { chunkId } = citation

  useEffect(() => {
    const controller = new AbortController()

    void (async () => {
      try {
        const passage = await getPassage(chunkId, controller.signal)
        setResult({ chunkId, status: 'loaded', passage })
      } catch (cause) {
        if (controller.signal.aborted) {
          return
        }
        signOutIfExpired(cause)
        setResult({ chunkId, status: 'failed', error: describeFailure(cause) })
      }
    })()

    return () => controller.abort()
  }, [chunkId])

  const loaded = result?.chunkId === chunkId ? result : null
  const section = sectionLabel(citation.section)

  return (
    <aside
      aria-label={`Source ${citation.index}`}
      className="bg-background flex w-[26rem] shrink-0 flex-col border-l"
    >
      <div className="flex items-start justify-between gap-2 p-4">
        <div className="grid gap-1">
          <p className="text-muted-foreground text-xs font-medium">
            Source {citation.index}
          </p>
          <h2 className="text-sm font-semibold">
            {citation.companyName ?? citation.ticker}
          </h2>
          <p className="text-muted-foreground text-xs">
            {filingLabel(citation)} · filed {formatFilingDate(citation.filingDate)}
          </p>
          {/* `page` is NULL corpus-wide, so the Item section is what locates a
              passage for the reader. */}
          {section && <p className="text-xs">{section}</p>}
        </div>

        <Button variant="ghost" size="icon-sm" onClick={onClose} aria-label="Close source">
          <X />
        </Button>
      </div>

      <Separator />

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="grid gap-2">
          <p className="text-muted-foreground text-xs font-medium">Cited excerpt</p>
          <blockquote className="border-primary/50 border-l-2 pl-3 text-sm whitespace-pre-wrap">
            {citation.quote}
          </blockquote>
        </div>

        <Separator className="my-4" />

        <div className="grid gap-2">
          <p className="text-muted-foreground text-xs font-medium">In the filing</p>
          {loaded === null ? (
            <div className="grid gap-2">
              <Skeleton className="h-3" />
              <Skeleton className="h-3" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ) : loaded.status === 'failed' ? (
            <p className="text-muted-foreground text-xs">
              {loaded.error} The excerpt above was saved with the answer and is
              unaffected.
            </p>
          ) : (
            <PassageText passage={loaded.passage} quote={citation.quote} />
          )}
        </div>
      </div>

      <Separator />

      <div className="p-4">
        <Button variant="outline" size="sm" className="w-full" asChild>
          <a href={citation.sourceUrl} target="_blank" rel="noreferrer noopener">
            <ExternalLink />
            Open the filing on SEC.gov
          </a>
        </Button>
      </div>
    </aside>
  )
}

/**
 * Why the filing text is missing, in this panel's terms.
 *
 * `describeError`'s 404 copy is about threads — "that conversation no longer
 * exists" — which is both wrong here and alarming, because it suggests the
 * citation was bogus. A 404 on a chunk id means the corpus was re-ingested.
 */
function describeFailure(cause: unknown): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return 'This passage has been re-indexed since the answer was written, so the filing text around it is no longer at the same location.'
  }
  return `The surrounding filing text could not be loaded: ${describeError(cause)}`
}

/** The cited chunk with its quote marked, between its dimmed neighbours. */
function PassageText({ passage, quote }: { passage: Passage; quote: string }) {
  return (
    <div className="grid gap-3 text-sm leading-relaxed whitespace-pre-wrap">
      {passage.contextBefore && (
        <p className="text-muted-foreground/70">{passage.contextBefore}</p>
      )}
      <p>{marked(passage.content, quote)}</p>
      {passage.contextAfter && (
        <p className="text-muted-foreground/70">{passage.contextAfter}</p>
      )}
    </div>
  )
}

/**
 * The chunk with the quoted span highlighted.
 *
 * Whitespace-insensitive, matching the backend validator: chunk text carries
 * reconstructed headings and serialized tables, so a quote copied out of it
 * agrees on the words but rarely on the line breaks. The words and their order
 * still have to match exactly, which is what the `\s+` joins preserve.
 *
 * If no span matches, the chunk renders unmarked rather than being altered to
 * fit — the excerpt above it is the citation either way.
 */
function marked(content: string, quote: string) {
  const words = quote.trim().split(/\s+/).map(escapeRegExp)

  if (words.length === 0) {
    return content
  }

  const match = new RegExp(words.join('\\s+')).exec(content)

  if (match === null) {
    return content
  }
  return (
    <>
      {content.slice(0, match.index)}
      <mark className="bg-primary/20 text-foreground rounded px-0.5">{match[0]}</mark>
      {content.slice(match.index + match[0].length)}
    </>
  )
}

/** A quote is filing prose, and filing prose contains `$`, `(`, `.` and `*`. */
function escapeRegExp(word: string): string {
  return word.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
