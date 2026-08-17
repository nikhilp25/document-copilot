/**
 * Environment configuration, validated at boot.
 *
 * The only module that reads `import.meta.env`. Everything else imports `env`
 * and gets values that are already proven present and well-formed.
 *
 * Validation runs at import time, so a missing or malformed variable fails the
 * app on load with a named error rather than surfacing later as an opaque
 * `fetch` failure or a Supabase client pointed at `undefined`.
 */

declare global {
  interface ImportMetaEnv {
    // Typed as possibly-undefined on purpose: Vite substitutes whatever is in
    // `.env` at build time, and an absent variable is exactly the case these
    // checks exist to catch.
    readonly VITE_API_BASE_URL: string | undefined
    readonly VITE_SUPABASE_URL: string | undefined
    readonly VITE_SUPABASE_ANON_KEY: string | undefined
  }
}

function required(name: string, value: string | undefined): string {
  const trimmed = value?.trim()

  if (!trimmed) {
    throw new Error(
      `Missing ${name}. Copy frontend/.env.example to frontend/.env, fill it in, ` +
        'then restart the dev server — Vite only reads .env at startup.',
    )
  }
  return trimmed
}

/** Absolute http(s) URL, trailing slash removed so callers can join `${base}/path`. */
function requiredUrl(name: string, value: string | undefined): string {
  const raw = required(name, value)

  let parsed: URL
  try {
    parsed = new URL(raw)
  } catch {
    throw new Error(`${name} must be an absolute URL including scheme (got "${raw}").`)
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error(`${name} must be http or https (got "${parsed.protocol}").`)
  }
  return raw.replace(/\/+$/, '')
}

export const env = {
  apiBaseUrl: requiredUrl('VITE_API_BASE_URL', import.meta.env.VITE_API_BASE_URL),
  supabaseUrl: requiredUrl('VITE_SUPABASE_URL', import.meta.env.VITE_SUPABASE_URL),
  supabaseAnonKey: required('VITE_SUPABASE_ANON_KEY', import.meta.env.VITE_SUPABASE_ANON_KEY),
} as const
