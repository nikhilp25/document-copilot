/**
 * The browser Supabase client.
 *
 * Auth only. Chat threads, messages, and citations are read and written through
 * the FastAPI backend (`@/lib/api`), never queried from here — the backend owns
 * grounding and citation validation, and routing data access through it keeps
 * one authorization story instead of two.
 *
 * The anon key is public by design; row-level security and the backend's own
 * checks are what actually protect data.
 */

import { createClient } from '@supabase/supabase-js'

import { env } from '@/lib/env'

// Defaults are what we want in a browser SPA: the session persists to
// localStorage, tokens refresh in the background, and the client consumes the
// tokens in the URL fragment after an email confirmation link.
export const supabase = createClient(env.supabaseUrl, env.supabaseAnonKey)
