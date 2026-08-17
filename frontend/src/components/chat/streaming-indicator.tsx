/**
 * Shown between submitting a question and the first text delta arriving.
 *
 * Once deltas land the growing answer is its own progress signal, so the
 * caller stops rendering this.
 */

export function StreamingIndicator() {
  return (
    <div className="bg-muted flex w-fit items-center gap-1.5 rounded-lg px-4 py-3.5">
      <span className="sr-only">Waiting for the assistant…</span>
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          className="bg-muted-foreground/60 size-1.5 animate-bounce rounded-full"
          style={{ animationDelay: `${delay}ms` }}
        />
      ))}
    </div>
  )
}
