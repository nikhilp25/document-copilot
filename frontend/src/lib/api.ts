/**
 * Everything that talks to our FastAPI backend.
 *
 * The `api` client attaches the bearer token, so no component ever handles one
 * and none threads one through props. The thread calls below are the product
 * vocabulary on top of it — pages ask for "this analyst's threads", not for a
 * URL. `chatTransport` is the one exception that bypasses `api`: streaming
 * needs the raw response body, which the JSON client deliberately doesn't
 * expose. It shares the token resolver so there is still only one of those.
 */

import { DefaultChatTransport } from 'ai'

import type { ChatMessage } from '@/lib/citations'
import { env } from '@/lib/env'
import { HttpClient } from '@/lib/http'
import { supabase } from '@/lib/supabase'

async function accessToken(): Promise<string | null> {
  // `getSession` returns the cached session and refreshes it first if the
  // access token has expired, so this is cheap on the common path.
  const { data, error } = await supabase.auth.getSession()

  if (error) {
    // A refresh that fails means the session is gone (revoked, or the refresh
    // token expired). Send the request unauthenticated and let the backend's
    // 401 drive the redirect to login — one place decides what expiry means.
    return null
  }
  return data.session?.access_token ?? null
}

export const api = new HttpClient({
  baseUrl: env.apiBaseUrl,
  getToken: accessToken,
})

/** A conversation in the sidebar. `title` is null until the first turn names it. */
export interface Thread {
  id: string
  title: string | null
  createdAt: string
  updatedAt: string
}

/** One persisted turn. `parts` is the AI SDK wire form, stored verbatim. */
export interface StoredMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  parts: ChatMessage['parts'] | null
  createdAt: string
}

/**
 * A cited chunk with the filing text around it.
 *
 * The citation part already carries the quote, so this is only what the panel
 * cannot get from the transcript: the chunk in full, and its neighbours. They
 * arrive as text rather than as passages because the analyst reads them as
 * context, not as things to click.
 */
export interface Passage {
  chunkId: string
  documentId: string
  ticker: string
  companyName: string | null
  formType: string
  fiscalYear: number
  filingDate: string
  accessionNumber: string
  sourceUrl: string
  section: string | null
  page: number | null
  content: string
  contextBefore: string | null
  contextAfter: string | null
}

export interface ThreadDetail {
  thread: Thread
  messages: StoredMessage[]
}

export function listThreads(signal?: AbortSignal): Promise<Thread[]> {
  return api.get<Thread[]>('/chat/threads', { signal })
}

export function createThread(): Promise<Thread> {
  return api.post<Thread>('/chat/threads')
}

export function getThread(threadId: string, signal?: AbortSignal): Promise<ThreadDetail> {
  // Thread and history in one round trip, so a deep link into a chat doesn't
  // render the header before the messages.
  return api.get<ThreadDetail>(`/chat/threads/${threadId}`, { signal })
}

export function getPassage(chunkId: string, signal?: AbortSignal): Promise<Passage> {
  // 404 when the corpus has been re-ingested since the answer was written: the
  // quote is still true, but the chunk it came from has a new id.
  return api.get<Passage>(`/passages/${chunkId}`, { signal })
}

/**
 * Persisted messages in the shape `useChat` initializes from.
 *
 * `parts` is null only for messages the backend built without a wire form; the
 * flattened `content` is a faithful stand-in for those.
 */
export function toUIMessages(messages: StoredMessage[]): ChatMessage[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    parts: message.parts ?? [{ type: 'text', text: message.content }],
  }))
}

/**
 * The streaming transport for one thread.
 *
 * Headers resolve per request rather than at construction: Supabase rotates the
 * access token roughly hourly, and a token captured when the page loaded is a
 * 401 on a chat left open over lunch.
 */
export function chatTransport(threadId: string): DefaultChatTransport<ChatMessage> {
  return new DefaultChatTransport<ChatMessage>({
    api: `${env.apiBaseUrl}/chat/stream`,
    headers: async (): Promise<Record<string, string>> => {
      const token = await accessToken()
      // Signed out, send nothing: the backend's 401 is what decides that, not
      // a guess made here.
      return token ? { Authorization: `Bearer ${token}` } : {}
    },
    // The transport sends `messages` on its own; the thread is ours to add.
    body: { threadId },
  })
}
