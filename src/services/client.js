/**
 * Centralized API Client — Phase 11 Updated
 *
 * Provides a small reusable HTTP client around fetch.
 * All backend requests should go through this module so
 * the base URL is configured in one place.
 *
 * Phase 11: Automatically attaches the Supabase JWT as
 * Authorization: Bearer <token> for authenticated requests.
 *
 * Configuration:
 *   Set VITE_API_BASE_URL in .env (defaults to http://localhost:8000/api/v1)
 */

import { supabase, waitForSessionResolution } from '../lib/supabase';
import { timingSpan, timingEvent } from './performance.js';

const BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

/**
 * Get the current Supabase access token (if authenticated).
 * Waits reliably for session initialization if the client is still restoring.
 * Returns null only if genuinely unauthenticated.
 */
async function getAccessToken() {
  return waitForSessionResolution(1500);
}


/**
 * Make an HTTP request to the backend API.
 *
 * @param {string} endpoint - API path (e.g. '/health')
 * @param {object} options  - fetch options (method, body, headers, etc.)
 * @returns {Promise<object>} Parsed JSON response
 * @throws {Error} On network failure or non-OK HTTP status
 */
async function request(endpoint, options = {}) {
  const url = `${BASE_URL}${endpoint}`;

  // Get the auth token and attach it
  const finishAuth = timingSpan('client.auth_wait');
  const token = await getAccessToken();
  finishAuth();

  // Safe diagnostic logging (no tokens or secrets printed)
  // Timing never decodes or logs the user's JWT/identity.

  // Build headers: start with defaults, merge caller headers, then set auth last
  const { headers: optionHeaders, _retry, responseType, timeoutMs = 180000, signal, ...restOptions } = options;
  const headers = {
    'Content-Type': 'application/json',
    ...optionHeaders,
  };

  // Attach Authorization header if we have a token (always wins)
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  } else if (endpoint.includes('/resume/parse') || endpoint.includes('/job/parse') || endpoint.includes('/interview/start')) {
    // Critical persistence endpoints: perform an immediate fallback resolution
    const retriedToken = await waitForSessionResolution(1500);
    if (retriedToken) {
      headers['Authorization'] = `Bearer ${retriedToken}`;
    }
  }


  const config = {
    headers,
    ...restOptions,
  };

  // Remove Content-Type for FormData (browser sets it with boundary)
  if (config.body instanceof FormData) {
    delete config.headers['Content-Type'];
  }

  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) controller.abort();
  else signal?.addEventListener('abort', abort, { once: true });
  const timeout = setTimeout(abort, timeoutMs);
  config.signal = controller.signal;
  let response;
  let data;
  const stage = ({ '/audio/transcribe': 'transcription', '/evaluation/evaluate': 'evaluation', '/interview/next-question': 'next_question' })[endpoint] || 'other';
  const finishRequest = timingSpan(`http.${stage}`);
  try {
    response = await fetch(url, config);
    try {
      data = response.ok && responseType === 'blob' ? await response.blob() : await response.json();
    } catch (error) {
      if (error.name === 'AbortError') throw error;
      if (error instanceof SyntaxError) data = null;
      else throw error;
    }
  } catch (networkError) {
    finishRequest({ status: 0 });
    if (networkError.name === 'AbortError') throw new Error('The request timed out. Please retry the same action.');
    // Network failure (backend offline, DNS failure, CORS block, etc.)
    throw new Error(
      'Unable to reach the interview service. Check your connection and try again.'
    );
  } finally {
    // Cover the response body too, not just the arrival of HTTP headers.
    clearTimeout(timeout);
    signal?.removeEventListener('abort', abort);
  }
  finishRequest({ status: response.status });
  const serverMs = Number(response.headers.get('Server-Timing')?.match(/app;dur=([\d.]+)/)?.[1]);
  timingEvent(`backend.${stage}`, { duration_ms: serverMs, processing_ms: data?.processing_time_ms, total_ms: data?.total_time_ms });

  // Handle HTTP errors
  if (!response.ok) {
    const fallback = response.status === 429 ? 'Too many requests. Please wait before retrying.'
      : response.status >= 500 ? 'The interview service could not complete this action. Please try again shortly.'
      : 'The request was rejected. Please review your input and try again.';
    const message = data?.detail || data?.message || fallback;

    // Handle authentication errors specifically
    if (response.status === 401) {

      // If we had a token and this request has not been retried yet, attempt a single refresh
      if (token && !options._retry) {
        let refreshed;
        try { refreshed = await supabase.auth.refreshSession(); }
        catch { throw new Error('Unable to refresh your session. Check your connection and retry.'); }
        if (!refreshed.error && refreshed.data?.session?.access_token) {
          // Outside the refresh catch: a failed retried POST is not an auth failure.
          return request(endpoint, { ...options, _retry: true });
        }
        if (!refreshed.error?.status || refreshed.error.status >= 500) {
          throw new Error('Sign-in service is temporarily unavailable. Please retry shortly.');
        }
        if (![400, 401, 403].includes(refreshed.error.status)) {
          throw new Error('Unable to refresh your session. Please retry shortly.');
        }
        try { await supabase.auth.signOut(); } catch { /* No recursive retry. */ }
      } else {
        // Unauthenticated request to protected endpoint — ensure auth state is cleanly evicted
        try {
          await supabase.auth.signOut();
        } catch {
          // Ignore signOut error
        }
      }
    }

    const validationMessage = Array.isArray(message)
      ? message.map(item => `${(item.loc || []).filter(part => part !== 'body').join('.')}: ${item.msg || 'Invalid value'}`).join('; ')
      : null;
    const error = new Error(response.status >= 500 ? fallback
      : typeof message === 'string' ? message : validationMessage || fallback);
    error.status = response.status;
    error.retryAfter = response.headers.get('Retry-After');
    throw error;
  }

  if (!data || typeof data !== 'object') {
    throw new Error('The interview service returned an unreadable response. Please retry.');
  }
  if (responseType === 'blob' && (!data.size || data.type.split(';')[0] !== 'audio/mpeg')) {
    throw new Error('Question audio is unavailable. You can continue using the text question.');
  }
  return data;
}

/**
 * API client with convenience methods for each HTTP verb.
 */
const apiClient = {
  postBlob(endpoint, body, { signal } = {}) {
    return request(endpoint, {
      method: 'POST', body: JSON.stringify(body), responseType: 'blob',
      timeoutMs: 25000, signal,
    });
  },
  /**
   * GET request.
   * @param {string} endpoint - API path (e.g. '/health')
   * @returns {Promise<object>}
   */
  get(endpoint, options = {}) {
    return request(endpoint, { ...options, method: 'GET' });
  },

  /**
   * POST request with JSON body.
   * @param {string} endpoint - API path
   * @param {object} body     - Request payload
   * @returns {Promise<object>}
   */
  post(endpoint, body, options = {}) {
    return request(endpoint, {
      ...options,
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  /**
   * POST request with FormData (for file uploads).
   * @param {string} endpoint - API path
   * @param {FormData} formData - Form data with files
   * @returns {Promise<object>}
   */
  upload(endpoint, formData, options = {}) {
    return request(endpoint, {
      ...options,
      method: 'POST',
      body: formData,
    });
  },
};

export default apiClient;
