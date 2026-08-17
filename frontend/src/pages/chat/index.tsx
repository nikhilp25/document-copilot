/**
 * `/chat` with no thread selected.
 *
 * Deliberately not a redirect to the most recent thread: landing inside an old
 * conversation makes it easy to append an unrelated question to it.
 */

export function ChatIndexPage() {
  return (
    <div className="grid flex-1 place-items-center px-6">
      <div className="grid max-w-md gap-2 text-center">
        <h2 className="text-lg font-semibold">Ask the filings</h2>
        <p className="text-muted-foreground text-sm">
          Start a new chat, or pick up a past conversation from the sidebar. Answers are
          grounded in the SEC filing corpus.
        </p>
      </div>
    </div>
  )
}
