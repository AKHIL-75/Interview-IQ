// Capture Supabase callbacks before the SDK can remove their URL parameters.
// Never persist callback URLs/tokens or display provider response bodies.
export const RECOVERY_KEY = 'interviewiq_recovery';
export const RESET_ACK = 'If an account can receive recovery email, check its inbox for a reset link.';
const LINK_ERROR = 'This sign-in or recovery link is invalid, expired, or already used. Please start again.';

export function readAuthCallback(href) {
  const url = new URL(href);
  const params = new URLSearchParams(url.hash.slice(1));
  for (const [key, value] of url.searchParams) if (!params.has(key)) params.set(key, value);
  const error = params.get('error') || params.get('error_code');
  const accessToken = params.get('access_token');
  const refreshToken = params.get('refresh_token');
  const kind = params.get('type') === 'recovery' ? 'recovery' : (accessToken || error || params.has('code') ? 'oauth' : null);
  const tokenHash = kind === 'recovery' && !error && !accessToken && !refreshToken ? params.get('token_hash') : null;
  return { kind, accessToken, refreshToken, tokenHash, error, code: params.get('code') };
}

export const initialAuthCallback = typeof window === 'undefined' ? {} : readAuthCallback(window.location.href);

export function callbackUrl(origin, path) {
  const url = new URL(origin);
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Invalid application address.');
  return new URL(path, url.origin).href;
}

export function safeAuthError(error, operation) {
  if (error?.status === 429 || error?.code === 'over_email_send_rate_limit') return 'Too many requests. Please wait before trying again.';
  if (operation === 'reset') return 'Unable to request a reset email. Please try again later.';
  if (operation === 'password') return 'Unable to update your password. Check the password requirements or request a new recovery link.';
  return 'Unable to start Google sign-in. Please try again or use email sign-in.';
}

export async function requestPasswordReset(auth, email, origin) {
  const clean = email.trim();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean)) throw new Error('Enter a valid email address.');
  try {
    const { error } = await auth.resetPasswordForEmail(clean, { redirectTo: callbackUrl(origin, '/reset-password') });
    if (error) throw error;
    return RESET_ACK; // Provider acceptance does not prove inbox delivery.
  } catch (error) { throw new Error(safeAuthError(error, 'reset')); }
}

export async function startGoogleSignIn(auth, origin, providerSettings) {
  let settings;
  try { settings = await providerSettings(); }
  catch { throw new Error('Unable to check Google sign-in availability. Please retry or use email sign-in.'); }
  if (settings?.external?.google !== true) throw new Error('Google sign-in is not configured for this application. Please use email sign-in.');
  try {
    const { error } = await auth.signInWithOAuth({ provider: 'google', options: { redirectTo: callbackUrl(origin, '/auth/callback') } });
    if (error) throw error;
  } catch (error) { throw new Error(safeAuthError(error, 'google')); }
}

export function hasRecoveryMarker(storage, userId, now = Date.now()) {
  try {
    const marker = JSON.parse(storage?.getItem(RECOVERY_KEY) || 'null');
    return !!marker && (!userId || marker.userId === userId) && marker.at <= now && now - marker.at < 30 * 60 * 1000;
  } catch { return false; }
}

export function clearRecoveryMarker(storage) {
  try { storage?.removeItem(RECOVERY_KEY); } catch { /* Storage may be unavailable. */ }
}

export async function finishAuthCallback(auth, intent, mode, storage) {
  // initialize/getSession wait for the existing SDK URL processing; never exchange twice.
  const { error: initError } = await auth.initialize();
  if (mode === 'oauth' && intent.error === 'access_denied') throw new Error('Google sign-in was cancelled. You can try again.');
  if (initError || intent.error || intent.code) throw new Error(LINK_ERROR);
  const { data, error } = await auth.getSession();
  const session = data?.session;
  if (error || !session?.user || !session.access_token) throw new Error(LINK_ERROR);
  const resumed = mode === 'recovery' && !intent.kind && hasRecoveryMarker(storage, session.user.id);
  if (!resumed && (!intent.accessToken || !intent.refreshToken || session.access_token !== intent.accessToken)) throw new Error(LINK_ERROR);
  if (mode === 'recovery' && !resumed && intent.kind !== 'recovery') throw new Error(LINK_ERROR);
  const verified = await auth.getUser();
  if (verified.error || verified.data?.user?.id !== session.user.id) throw new Error(LINK_ERROR);
  if (mode === 'recovery') {
    try { storage?.setItem(RECOVERY_KEY, JSON.stringify({ userId: session.user.id, at: Date.now() })); } catch { /* Still allow the current recovery form. */ }
  }
  return session;
}

export async function verifyRecoveryLink(auth, tokenHash, storage) {
  const { data, error } = await auth.verifyOtp({ token_hash: tokenHash, type: 'recovery' });
  const session = data?.session;
  if (error || !session?.user?.id) throw new Error(LINK_ERROR);
  return finishAuthCallback(auth, {
    kind: 'recovery',
    accessToken: session.access_token,
    refreshToken: session.refresh_token,
  }, 'recovery', storage);
}

export function clearCallbackUrl(location, history) {
  // Called only after the SDK has finished reading the callback.
  history.replaceState(history.state, '', location.pathname);
}

export async function updateRecoveredPassword(auth, password, confirmPassword, expectedUserId) {
  if (password.length < 6) throw new Error('Password must be at least 6 characters.');
  if (password !== confirmPassword) throw new Error('Passwords do not match.');
  try {
    const { data, error: identityError } = await auth.getUser();
    if (identityError || !expectedUserId || data?.user?.id !== expectedUserId) throw new Error(LINK_ERROR);
    const { error } = await auth.updateUser({ password });
    if (error) throw error;
  } catch (error) { throw new Error(safeAuthError(error, 'password')); }
}
