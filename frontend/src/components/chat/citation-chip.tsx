/**
 * The two clickable forms of a citation.
 *
 * `CitationMarker` replaces the `[n]` the model wrote into the prose;
 * `CitationChip` is the labelled row beneath the answer. Both open the same
 * passage, so they share one component and differ only in what they show —
 * which keeps the marker and the chip from drifting apart on the one thing
 * that has to match, the index.
 */

import { filingLabel, sectionLabel, type CitationData } from '@/lib/citations'
import { cn } from '@/lib/utils'

interface CitationProps {
  citation: CitationData
  /** The panel is open on this citation. */
  active: boolean
  onSelect: (citation: CitationData) => void
}

/** What a screen reader hears in place of a bare number. */
function describe(citation: CitationData): string {
  const section = sectionLabel(citation.section)
  return `Source ${citation.index}: ${filingLabel(citation)}${section ? `, ${section}` : ''}`
}

export function CitationMarker({ citation, active, onSelect }: CitationProps) {
  return (
    <button
      type="button"
      onClick={() => onSelect(citation)}
      aria-label={describe(citation)}
      title={describe(citation)}
      className={cn(
        // Sized to sit inside a line of prose without opening up the leading:
        // an analyst reads the sentence, and the marker is punctuation until
        // they want it.
        'mx-0.5 inline-flex h-[1.15em] min-w-[1.15em] translate-y-[-0.15em] items-center justify-center',
        'rounded px-1 align-baseline text-[0.7em] font-medium tabular-nums',
        'focus-visible:ring-ring cursor-pointer transition-colors focus-visible:ring-2 focus-visible:outline-none',
        active
          ? 'bg-primary text-primary-foreground'
          : 'bg-foreground/10 text-foreground hover:bg-foreground/20',
      )}
    >
      {citation.index}
    </button>
  )
}

export function CitationChip({ citation, active, onSelect }: CitationProps) {
  const section = sectionLabel(citation.section)

  return (
    <button
      type="button"
      onClick={() => onSelect(citation)}
      aria-label={describe(citation)}
      aria-pressed={active}
      className={cn(
        'flex max-w-full items-center gap-1.5 rounded-md border px-2 py-1 text-xs',
        'focus-visible:ring-ring cursor-pointer transition-colors focus-visible:ring-2 focus-visible:outline-none',
        active
          ? 'border-primary bg-primary/10 text-foreground'
          : 'border-border bg-background hover:bg-accent hover:text-accent-foreground',
      )}
    >
      <span className="bg-foreground/10 rounded px-1 font-medium tabular-nums">
        {citation.index}
      </span>
      <span className="font-medium">{filingLabel(citation)}</span>
      {section && (
        <span className="text-muted-foreground truncate">· {section}</span>
      )}
    </button>
  )
}
