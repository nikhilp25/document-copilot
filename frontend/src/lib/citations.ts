/**
 * The typed shape of what the backend streams alongside an answer.
 *
 * `UIMessage`'s data parts are `Record<string, unknown>` by default, so every
 * component reading a citation would otherwise be casting. Naming the two part
 * kinds here once — `data-citation`, `data-status` — makes `ChatMessage` the
 * type the whole chat UI speaks, and a backend field rename a compile error
 * rather than an empty chip.
 *
 * The field names are camelCase because the orchestrator's `_chip()` already
 * translated them; this mirrors that function and nothing else.
 */

import type { UIMessage } from 'ai'

/** One passage backing one claim, as it arrives on the wire. */
export interface CitationData {
  /** 1-based, and matched by a `[n]` marker in the answer text. */
  index: number
  /** Verbatim from the filing — the product's whole promise. Never reflow it. */
  quote: string
  chunkId: string
  documentId: string
  ticker: string
  companyName: string | null
  formType: string
  fiscalYear: number
  /** ISO date, `YYYY-MM-DD`. */
  filingDate: string
  accessionNumber: string
  sourceUrl: string
  /** `page` is NULL corpus-wide, so this is what actually locates a passage. */
  section: string | null
  page: number | null
}

/** Progress while the agent works. Transient: never part of the transcript. */
export interface StatusData {
  label: string
}

export type ChatMessage = UIMessage<
  unknown,
  { citation: CitationData; status: StatusData }
>

/**
 * The citations on one message, in marker order.
 *
 * Sorted rather than trusted: the parts arrive in the order the backend wrote
 * them, but a `[3]` in the prose has to open the third citation whatever the
 * array looks like.
 */
export function citationsOf(message: ChatMessage): CitationData[] {
  return message.parts
    .filter((part) => part.type === 'data-citation')
    .map((part) => part.data)
    .sort((left, right) => left.index - right.index)
}

/**
 * Identity for "which citation is open".
 *
 * Index and chunk together, because one passage can legitimately support two
 * different claims — keying on the chunk alone would light up both markers
 * while the panel header names only one of them.
 */
export function citationKey(citation: CitationData): string {
  return `${citation.index}:${citation.chunkId}`
}

/** "NVDA · 10-K FY2025" — the filing, short enough for a chip. */
export function filingLabel(citation: CitationData): string {
  return `${citation.ticker} · ${citation.formType} FY${citation.fiscalYear}`
}

const ITEM = /^(item\s+\d+[a-z]?)\b/i

/**
 * The section, trimmed to what is reliably right.
 *
 * Ingestion reconstructs headings from CSS-styled text, so the title half can
 * come through mangled ("Item 1. B USINESS") while the item number is exact.
 * A chip shows the part that survived; the panel shows the heading in full.
 */
export function sectionLabel(section: string | null): string | null {
  if (!section) {
    return null
  }

  const heading = section.trim().replace(/\s+/g, ' ')
  const item = ITEM.exec(heading)

  return item ? item[1].replace(/^i/, 'I') : heading
}

/**
 * A filing date an analyst can read.
 *
 * Pinned to UTC: the backend sends a bare `YYYY-MM-DD`, which parses as UTC
 * midnight, and rendering that in a western timezone would show the day before
 * the filing was filed.
 */
export function formatFilingDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`)

  if (Number.isNaN(date.getTime())) {
    return iso
  }
  return date.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}
