/**
 * Supabase Client — Phase 11 / Phase 12 Refined
 *
 * Initialises the Supabase browser client using the project URL and
 * publishable anon key from VITE_ environment variables.
 *
 * SECURITY:
 *  - Only VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY are used.
 *  - NO service-role key is ever loaded on the frontend.
 *  - The anon key is safe for browser exposure (RLS protects data).
 *  - Access tokens are NEVER logged or printed to console.
 *  - Tokens are managed by Supabase SDK session storage — no redundant localStorage caching.
 *
 * Phase 12 Refinements:
 *  - Removed redundant localStorage token caching ('interviewiq_access_token')
 *    which was a stale-token vector.
 *  - Simplified getValidAccessToken() to rely on Supabase SDK's session management.
 *  - Added cross-tab synchronization via onAuthStateChange broadcast.
 */

import { createClient } from '@supabase/supabase-js';
import '../services/authFlows'; // Capture callback before SDK initialization clears it.

const supabaseUrl =
  import.meta.env.VITE_SUPABASE_URL || 'https://btzsfpmyleikmsrptilu.supabase.co';
const supabaseAnonKey =
  import.meta.env.VITE_SUPABASE_ANON_KEY ||
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ0enNmcG15bGVpa21zcnB0aWx1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTA5NTMxMDAsImV4cCI6MjEwNjUyOTEwMH0.5r7f4ksdjmS4tmPqDPCu6e1IBoSvKwK2dtfvFnY859U';

if (!supabaseUrl || !supabaseAnonKey) {
  console.error(
    '[Supabase] Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY. ' +
    'Check your .env file.'
  );
}


export const supabase = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: true,
    // storageKey is left as default — Supabase SDK manages its own localStorage key
  },
});

export async function getAuthProviderSettings() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(`${supabaseUrl}/auth/v1/settings`, {
      headers: { apikey: supabaseAnonKey }, signal: controller.signal,
    });
    if (!response.ok) throw new Error('Auth settings unavailable');
    return await response.json();
  } finally { clearTimeout(timer); }
}

// In-memory session cache for fast synchronous checks
let cachedSession = null;
let sessionRestorationPromise = null;

// Initialize session tracking
if (typeof window !== 'undefined') {
  // Restore immediately on load
  sessionRestorationPromise = supabase.auth.getSession().then(({ data: { session } }) => {
    cachedSession = session;
    setGlobalAccessToken(session?.access_token || null);
    return session;
  }).catch(() => null);

  // Keep in-memory cache synchronized on auth state changes (including cross-tab)
  supabase.auth.onAuthStateChange((event, session) => {
    cachedSession = session;
    setGlobalAccessToken(session?.access_token || null);
    if (event === 'SIGNED_OUT') {
      if (typeof window !== 'undefined') {
        window.__SUPABASE_ACCESS_TOKEN__ = null;
      }
    }
  });
}

/**
 * Directly sets the global in-memory access token reference.
 * Used by AuthContext to ensure the API client can access the latest token
 * immediately after login/register without waiting for onAuthStateChange.
 */
export function setGlobalAccessToken(token) {
  if (typeof window !== 'undefined') {
    window.__SUPABASE_ACCESS_TOKEN__ = token || null;
  }
}

/**
 * Returns a valid Supabase access token string or null.
 *
 * Priority:
 *   1. Global window reference (set immediately by AuthContext on login)
 *   2. In-memory cached session (updated by onAuthStateChange)
 *   3. Await pending session restoration (initial page load)
 *   4. Fresh getSession() call to Supabase SDK
 *
 * Never returns a stale/expired token — checks expiry with 30s buffer.
 * Never logs or exposes the token value.
 */
export async function getValidAccessToken() {
  // 1. Direct window global set by AuthContext — check against cached session expiry if known
  if (typeof window !== 'undefined' && window.__SUPABASE_ACCESS_TOKEN__) {
    if (cachedSession?.access_token === window.__SUPABASE_ACCESS_TOKEN__) {
      if (!cachedSession.expires_at || cachedSession.expires_at * 1000 > Date.now() + 30000) {
        return window.__SUPABASE_ACCESS_TOKEN__;
      }
      // Expiring or expired — clear global and refresh below
      window.__SUPABASE_ACCESS_TOKEN__ = null;
    } else {
      return window.__SUPABASE_ACCESS_TOKEN__;
    }
  }

  // 2. In-memory cache with expiry check (30-second buffer)
  if (cachedSession?.access_token) {
    if (!cachedSession.expires_at || cachedSession.expires_at * 1000 > Date.now() + 30000) {
      return cachedSession.access_token;
    }
    // Token is about to expire — fall through to refresh
  }

  // 3. Await in-flight restoration if still pending (initial page load)
  if (sessionRestorationPromise) {
    try {
      const restored = await sessionRestorationPromise;
      if (restored?.access_token) {
        if (!restored.expires_at || restored.expires_at * 1000 > Date.now() + 30000) {
          cachedSession = restored;
          return restored.access_token;
        }
      }
    } catch {
      // Restoration failed — fall through
    }
  }

  // 4. Fresh call to Supabase SDK's getSession() — handles token refresh internally
  try {
    const { data: { session } } = await supabase.auth.getSession();
    if (session?.access_token) {
      if (!session.expires_at || session.expires_at * 1000 > Date.now() + 30000) {
        cachedSession = session;
        setGlobalAccessToken(session.access_token);
        return session.access_token;
      }
      // If getSession returned an expiring/expired session, attempt refreshSession
      const { data: refreshData, error: refreshError } = await supabase.auth.refreshSession();
      if (!refreshError && refreshData?.session?.access_token) {
        cachedSession = refreshData.session;
        setGlobalAccessToken(refreshData.session.access_token);
        return refreshData.session.access_token;
      }
    }
  } catch {
    // Session retrieval failed — user is unauthenticated
  }

  return null;
}

/**
 * Waits for session resolution (up to maxWaitMs) before giving up.
 * Ensures initial page loads or restores don't fire prematurely unauthenticated requests.
 */
export async function waitForSessionResolution(maxWaitMs = 1500) {
  const start = Date.now();
  let token = await getValidAccessToken();
  if (token) return token;

  while (Date.now() - start < maxWaitMs) {
    await new Promise((r) => setTimeout(r, 100));
    token = await getValidAccessToken();
    if (token) return token;
  }
  return null;
}

