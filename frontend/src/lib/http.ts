/**
 * A small `fetch` wrapper: base URL, JSON, bearer token, timeout, typed errors.
 *
 * This module is unconfigured on purpose — `@/lib/api` owns the single instance
 * pointed at our backend. Import `api` from there; import from here only for
 * `ApiError`.
 */

/**
 * A request that did not return a usable response.
 *
 * `status` is null when no response arrived at all — offline, DNS failure, a
 * CORS rejection, or our own timeout. The browser deliberately hides which one
 * (a cross-origin failure is indistinguishable from a network failure by
 * design), so `isNetworkError` is as precise as this can honestly get. UI code
 * uses it to tell "the backend said no" apart from "the backend never heard us".
 */
export class ApiError extends Error {
  readonly status: number | null
  /** Parsed JSON body if the server sent one, else raw text, else null. */
  readonly body: unknown
  readonly isNetworkError: boolean

  constructor(message: string, status: number | null, body: unknown = null, cause?: unknown) {
    super(message, { cause })
    this.name = 'ApiError'
    this.status = status
    this.body = body
    this.isNetworkError = status === null
  }
}

export interface RequestOptions {
  /** JSON-serialized into the request body. */
  body?: unknown
  headers?: Record<string, string>
  /** Caller cancellation. Combined with — not replacing — the timeout. */
  signal?: AbortSignal
  timeoutMs?: number
}

export interface HttpClientOptions {
  baseUrl: string
  /** Resolves the bearer token per request; null when signed out. */
  getToken?: () => Promise<string | null>
  timeoutMs?: number
}

/** Generous enough for a slow retrieval turn, short enough that a hung request surfaces. */
const DEFAULT_TIMEOUT_MS = 30_000

export class HttpClient {
  private readonly baseUrl: string
  private readonly getToken: (() => Promise<string | null>) | undefined
  private readonly timeoutMs: number

  constructor(options: HttpClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '')
    this.getToken = options.getToken
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS
  }

  async request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const url = `${this.baseUrl}${path.startsWith('/') ? path : `/${path}`}`

    const headers = new Headers(options.headers)
    headers.set('Accept', 'application/json')

    // Resolved per request rather than cached: Supabase rotates the access
    // token roughly hourly, and a stale one means a 401 mid-session.
    const token = await this.getToken?.()
    if (token) {
      headers.set('Authorization', `Bearer ${token}`)
    }

    let body: string | undefined
    if (options.body !== undefined) {
      body = JSON.stringify(options.body)
      headers.set('Content-Type', 'application/json')
    }

    const timeoutMs = options.timeoutMs ?? this.timeoutMs
    const timeout = AbortSignal.timeout(timeoutMs)
    const signal = options.signal ? AbortSignal.any([options.signal, timeout]) : timeout

    let response: Response
    try {
      response = await fetch(url, { method, headers, body, signal })
    } catch (cause) {
      // A caller-initiated cancel is not a failure — let the raw AbortError
      // through so effect cleanup and unmounts stay quiet.
      if (options.signal?.aborted) {
        throw cause
      }
      if (timeout.aborted) {
        throw new ApiError(`${method} ${path} timed out after ${timeoutMs}ms.`, null, null, cause)
      }
      throw new ApiError(
        `Could not reach the API at ${this.baseUrl} — network error or CORS rejection.`,
        null,
        null,
        cause,
      )
    }

    const parsed = await readBody(response)

    if (!response.ok) {
      throw new ApiError(errorMessage(method, path, response, parsed), response.status, parsed)
    }
    // No runtime validation by design: the backend is ours, and a schema library
    // at every call site would cost more than it catches. `T` is a claim about
    // the endpoint, not a guarantee.
    return parsed as T
  }

  get<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('GET', path, options)
  }

  post<T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'body'>): Promise<T> {
    return this.request<T>('POST', path, { ...options, body })
  }

  put<T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'body'>): Promise<T> {
    return this.request<T>('PUT', path, { ...options, body })
  }

  patch<T>(path: string, body?: unknown, options?: Omit<RequestOptions, 'body'>): Promise<T> {
    return this.request<T>('PATCH', path, { ...options, body })
  }

  delete<T>(path: string, options?: RequestOptions): Promise<T> {
    return this.request<T>('DELETE', path, options)
  }
}

/** JSON when the body parses as JSON, the raw text when it doesn't, null when empty. */
async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return null
  }

  const text = await response.text()
  if (!text) {
    return null
  }

  try {
    return JSON.parse(text) as unknown
  } catch {
    // HTML error pages from a proxy, plain-text tracebacks, and the like.
    return text
  }
}

function errorMessage(method: string, path: string, response: Response, body: unknown): string {
  const detail = extractDetail(body)
  const prefix = `${method} ${path} failed with ${response.status}`

  return detail ? `${prefix}: ${detail}` : `${prefix} ${response.statusText}`.trimEnd()
}

/** FastAPI puts the human-readable reason in `detail` on every `HTTPException`. */
function extractDetail(body: unknown): string | null {
  if (typeof body === 'string') {
    return body.slice(0, 300)
  }
  if (body && typeof body === 'object' && 'detail' in body) {
    const { detail } = body as { detail: unknown }
    if (typeof detail === 'string') {
      return detail
    }
    // 422 validation errors arrive as a list of objects — readable enough
    // serialized, and only ever a bug on our side.
    if (detail !== undefined) {
      return JSON.stringify(detail).slice(0, 300)
    }
  }
  return null
}
