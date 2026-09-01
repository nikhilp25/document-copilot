/**
 * Shown between submitting a question and the first text delta arriving.
 *
 * That gap is long — a cross-section question runs a dozen searches before a
 * word is validated — so the backend narrates it with transient `data-status`
 * parts and this renders the latest one. Without the label it is three dots
 * for a minute, which reads as a hang.
 *
 * Once deltas land the growing answer is its own progress signal, so the
 * caller stops rendering this.
 */

interface StreamingIndicatorProps {
  /** The newest progress line, e.g. "Searching NVDA 2025…". */
  label?: string | null
}

export function StreamingIndicator({ label }: StreamingIndicatorProps) {
  return (
    <div className="bg-muted flex w-fit items-center gap-2.5 rounded-lg px-4 py-3.5">
      <span className="sr-only">Waiting for the assistant…</span>

      <span className="flex items-center gap-1.5">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="bg-muted-foreground/60 size-1.5 animate-bounce rounded-full"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </span>

      {/* `aria-live` so the narration reaches a screen reader as it changes,
          rather than only on the next focus. */}
      {label && (
        <span className="text-muted-foreground text-sm" aria-live="polite">
          {label}
        </span>
      )}
    </div>
  )
}
