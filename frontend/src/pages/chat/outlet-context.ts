/**
 * What the chat layout hands down to its routes.
 *
 * Threads are titled server-side from the first question, so the sidebar is
 * stale the moment a turn finishes. Rather than have the thread route refetch
 * the list itself, the layout owns that state and passes the refresh down.
 */

import { useOutletContext } from 'react-router-dom'

export interface ChatOutletContext {
  /** Reload the sidebar — call after a turn completes so a new title appears. */
  refreshThreads: () => void
}

export function useChatOutletContext(): ChatOutletContext {
  return useOutletContext<ChatOutletContext>()
}
