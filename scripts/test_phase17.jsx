import test, { beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import Renderer, { act } from 'react-test-renderer';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { requestPasswordReset, startGoogleSignIn, readAuthCallback, finishAuthCallback,
  updateRecoveredPassword, initialAuthCallback, RECOVERY_KEY, hasRecoveryMarker, RESET_ACK } from '../src/services/authFlows';
import { AuthProvider, useAuth } from '../src/context/AuthContext';
import { ToastProvider } from '../src/context/ToastContext';
import ProtectedRoute from '../src/components/ProtectedRoute';
import AuthLayout from '../src/layouts/AuthLayout';
import ForgotPasswordPage from '../src/pages/ForgotPasswordPage';
import ResetPasswordPage from '../src/pages/ResetPasswordPage';
import LoginPage from '../src/pages/LoginPage';
import AuthCallbackPage from '../src/pages/AuthCallbackPage';

const storage = () => { const items = new Map(); return { getItem: key => items.get(key) || null,
  setItem: (key, value) => items.set(key, value), removeItem: key => items.delete(key) }; };
let handler, context, session, root;
const tick = () => new Promise(resolve => setTimeout(resolve, 5));
function Probe() { context = useAuth(); return null; }
async function mount(children) {
  await act(async () => { root = Renderer.create(<MemoryRouter><AuthProvider><ToastProvider><Probe />{children}</ToastProvider></AuthProvider></MemoryRouter>); await tick(); });
  return root;
}
beforeEach(async () => {
  if (root) await act(async () => root.unmount());
  session = null; handler = null; context = null;
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  globalThis.window = { sessionStorage: storage(), location: { origin: 'https://interview.example', pathname: '/reset-password' },
    history: { state: null, replaceState() {} } };
  globalThis.localStorage = storage();
  for (const key of Object.keys(initialAuthCallback)) delete initialAuthCallback[key];
  globalThis.providerSettings = async () => ({ external: { google: true } });
  globalThis.sdk = { auth: {
    initialize: async () => ({ error: null }),
    getSession: async () => ({ data: { session }, error: null }),
    getUser: async () => ({ data: { user: session?.user || null }, error: null }),
    onAuthStateChange: fn => { handler = fn; return { data: { subscription: { unsubscribe() {} } } }; },
    resetPasswordForEmail: async () => ({ error: null }),
    updateUser: async () => ({ error: null }),
    signOut: async () => { session = null; handler?.('SIGNED_OUT', null); return { error: null }; },
    signInWithOAuth: async () => ({ error: null }),
  }, from: () => ({ select: () => ({ eq: () => ({ maybeSingle: async () => ({ data: null }) }) }) }) };
});
const validSession = () => ({ access_token: 'synthetic-access', user: { id: 'test-user', email: 'test@example.invalid' } });
const recoveryIntent = () => readAuthCallback('https://interview.example/reset-password#access_token=synthetic-access&refresh_token=synthetic-refresh&type=recovery');

test('reset request uses current origin and neutral acknowledgement', async () => {
  let sent;
  sdk.auth.resetPasswordForEmail = async (...args) => { sent = args; return { error: null }; };
  assert.equal(await requestPasswordReset(sdk.auth, ' test@example.invalid ', window.location.origin), RESET_ACK);
  assert.deepEqual(sent, ['test@example.invalid', { redirectTo: 'https://interview.example/reset-password' }]);
});
test('reset errors never claim success or disclose provider body', async () => {
  sdk.auth.resetPasswordForEmail = async () => ({ error: { message: 'private account response' } });
  await assert.rejects(requestPasswordReset(sdk.auth, 'test@example.invalid', window.location.origin), error => !error.message.includes('private') && /Unable/.test(error.message));
});
test('invalid email does not request recovery', async () => {
  sdk.auth.resetPasswordForEmail = async () => { throw new Error('must not call'); };
  await assert.rejects(requestPasswordReset(sdk.auth, 'invalid', window.location.origin), /valid email/);
});
test('reset rate limit is recoverable', async () => {
  sdk.auth.resetPasswordForEmail = async () => ({ error: { status: 429 } });
  await assert.rejects(requestPasswordReset(sdk.auth, 'test@example.invalid', window.location.origin), /wait/);
});
test('Google initiation uses provider and safe current-origin callback', async () => {
  let sent; sdk.auth.signInWithOAuth = async args => { sent = args; return { error: null }; };
  await startGoogleSignIn(sdk.auth, window.location.origin, providerSettings);
  assert.deepEqual(sent, { provider: 'google', options: { redirectTo: 'https://interview.example/auth/callback' } });
});
test('disabled Google is blocked before OAuth', async () => {
  sdk.auth.signInWithOAuth = () => { throw new Error('must not call'); };
  await assert.rejects(startGoogleSignIn(sdk.auth, window.location.origin, async () => ({ external: { google: false } })), /not configured/);
});
test('provider check outage permits retry and does not navigate', async () => {
  await assert.rejects(startGoogleSignIn(sdk.auth, window.location.origin, async () => { throw new Error('private network body'); }), /availability/);
});
test('OAuth SDK errors are sanitized', async () => {
  sdk.auth.signInWithOAuth = async () => ({ error: { message: 'private provider secret' } });
  await assert.rejects(startGoogleSignIn(sdk.auth, window.location.origin, providerSettings), /Unable to start/);
});
test('real SDK-style recovery session is verified before form readiness', async () => {
  session = validSession();
  assert.equal((await finishAuthCallback(sdk.auth, recoveryIntent(), 'recovery', window.sessionStorage)).user.id, 'test-user');
  assert.equal(hasRecoveryMarker(window.sessionStorage, 'test-user'), true);
  assert.equal(window.sessionStorage.getItem(RECOVERY_KEY).includes('synthetic-access'), false);
});
test('callback cannot use an unrelated existing session', async () => {
  session = validSession();
  await assert.rejects(finishAuthCallback(sdk.auth, {}, 'oauth', window.sessionStorage), /invalid/);
  await assert.rejects(finishAuthCallback(sdk.auth, { ...recoveryIntent(), accessToken: 'different' }, 'recovery', window.sessionStorage), /invalid/);
});
test('expired reused malformed and unsupported code callbacks reject', async () => {
  session = validSession();
  for (const intent of [{ error: 'otp_expired' }, { code: 'synthetic-code' }, { kind: 'recovery' }]) {
    await assert.rejects(finishAuthCallback(sdk.auth, intent, 'recovery', window.sessionStorage), /invalid/);
  }
  sdk.auth.initialize = async () => ({ error: new Error('expired') });
  await assert.rejects(finishAuthCallback(sdk.auth, recoveryIntent(), 'recovery', window.sessionStorage), /invalid/);
});
test('cancelled OAuth has a retry message without arbitrary provider text', async () => {
  await assert.rejects(finishAuthCallback(sdk.auth, { error: 'access_denied' }, 'oauth', window.sessionStorage), /cancelled/);
});
test('callback checks server user identity', async () => {
  session = validSession(); sdk.auth.getUser = async () => ({ data: { user: { id: 'other' } }, error: null });
  await assert.rejects(finishAuthCallback(sdk.auth, recoveryIntent(), 'recovery', window.sessionStorage), /invalid/);
});
test('recovery refresh marker works only for the same user within its lifetime', async () => {
  session = validSession(); await finishAuthCallback(sdk.auth, recoveryIntent(), 'recovery', window.sessionStorage);
  assert.equal((await finishAuthCallback(sdk.auth, {}, 'recovery', window.sessionStorage)).user.id, 'test-user');
  window.sessionStorage.setItem(RECOVERY_KEY, JSON.stringify({ userId: 'test-user', at: Date.now() - 31 * 60000 }));
  await assert.rejects(finishAuthCallback(sdk.auth, {}, 'recovery', window.sessionStorage), /invalid/);
});
test('password validation and account-switch protection prevent writes', async () => {
  session = validSession(); let calls = 0; sdk.auth.updateUser = async () => { calls++; return { error: null }; };
  await assert.rejects(updateRecoveredPassword(sdk.auth, 'short', 'short', 'test-user'), /6 characters/);
  await assert.rejects(updateRecoveredPassword(sdk.auth, 'synthetic-password', 'different', 'test-user'), /match/);
  await assert.rejects(updateRecoveredPassword(sdk.auth, 'synthetic-password', 'synthetic-password', 'other'), /Unable/);
  assert.equal(calls, 0);
});
test('password SDK failure preserves retry without claiming success', async () => {
  session = validSession(); sdk.auth.updateUser = async () => ({ error: { message: 'private provider body' } });
  await assert.rejects(updateRecoveredPassword(sdk.auth, 'synthetic-password', 'synthetic-password', 'test-user'), /Unable/);
});
test('auth event callback is synchronous and recovery is routed distinctly', async () => {
  await mount(null); session = validSession();
  await act(async () => { assert.equal(handler('PASSWORD_RECOVERY', session), undefined); await tick(); });
  assert.equal(context.recoveryActive, true); assert.equal(context.user.id, 'test-user');
});
test('late profile hydration cannot restore a signed-out user', async () => {
  let resolve; sdk.from = () => ({ select: () => ({ eq: () => ({ maybeSingle: () => new Promise(r => resolve = r) }) }) });
  await mount(null); session = validSession();
  await act(async () => { handler('SIGNED_IN', session); await tick(); });
  await act(async () => { handler('SIGNED_OUT', null); resolve({ data: { full_name: 'late' } }); await tick(); });
  assert.equal(context.user, null); assert.equal(currentToken, null);
});
test('confirmation-required registration never authenticates', async () => {
  sdk.auth.signUp = async () => ({ data: { user: validSession().user, session: null }, error: null });
  await mount(null); let result;
  await act(async () => { result = await context.register('Test', 'test@example.invalid', 'synthetic-password'); });
  assert.equal(result.confirmationRequired, true); assert.equal(context.user, null);
});
test('unauthenticated protected route redirects to login', async () => {
  await mount(<Routes><Route path="/" element={<ProtectedRoute><p>Private</p></ProtectedRoute>} /><Route path="/login" element={<p>Sign in required</p>} /></Routes>);
  assert.match(JSON.stringify(root.toJSON()), /Sign in required/);
});
test('authenticated recovery layout renders its form instead of bouncing to dashboard', async () => {
  session = validSession();
  await mount(<Routes><Route element={<AuthLayout allowAuthenticated />}><Route path="/" element={<p>Recovery form</p>} /></Route></Routes>);
  assert.match(JSON.stringify(root.toJSON()), /Recovery form/);
});
test('rendered reset request prevents duplicate clicks and shows accepted review', async () => {
  let resolve, calls = 0; sdk.auth.resetPasswordForEmail = () => { calls++; return new Promise(r => resolve = r); };
  await mount(<ForgotPasswordPage />);
  await act(async () => root.root.findByType('input').props.onChange({ target: { value: 'test@example.invalid' } }));
  const form = root.root.findByType('form');
  await act(async () => { form.props.onSubmit({ preventDefault() {} }); form.props.onSubmit({ preventDefault() {} }); });
  assert.equal(calls, 1);
  await act(async () => resolve({ error: null }));
  assert.match(JSON.stringify(root.toJSON()), /If an account/);
});
test('rendered Google button actually invokes OAuth once', async () => {
  let resolve, calls = 0; sdk.auth.signInWithOAuth = () => { calls++; return new Promise(r => resolve = r); };
  await mount(<LoginPage />);
  const button = root.root.findAllByType('button').find(b => b.props.onClick?.name === 'handleGoogle');
  await act(async () => { button.props.onClick(); button.props.onClick(); await tick(); });
  assert.equal(calls, 1); assert.equal(button.props.disabled, true);
  await act(async () => resolve({ error: null }));
});
test('rendered recovery form validates, saves exactly once, then clears secrets', async () => {
  session = validSession(); Object.assign(initialAuthCallback, recoveryIntent());
  let calls = 0, resolve; sdk.auth.updateUser = () => { calls++; return new Promise(r => resolve = r); };
  await mount(<ResetPasswordPage />);
  const inputs = root.root.findAllByType('input'); assert.equal(inputs.length, 2);
  await act(async () => inputs.forEach(input => input.props.onChange({ target: { value: 'synthetic-new-password' } })));
  const form = root.root.findByType('form');
  await act(async () => { form.props.onSubmit({ preventDefault() {} }); form.props.onSubmit({ preventDefault() {} }); await tick(); });
  assert.equal(calls, 1);
  await act(async () => resolve({ error: null }));
  assert.match(JSON.stringify(root.toJSON()), /password was updated/);
  assert.equal(root.root.findAllByType('input').length, 0); assert.equal(window.sessionStorage.getItem(RECOVERY_KEY), null);
});
test('rendered malformed callback offers retry rather than protected navigation', async () => {
  await mount(<AuthCallbackPage />);
  assert.match(JSON.stringify(root.toJSON()), /invalid, expired, or already used/);
});
