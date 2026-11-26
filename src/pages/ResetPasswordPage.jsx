import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { useAuth } from '../context/AuthContext';
import { initialAuthCallback, finishAuthCallback, clearCallbackUrl, updateRecoveredPassword, verifyRecoveryLink } from '../services/authFlows';
import Button from '../components/Button';

export default function ResetPasswordPage() {
  const { endRecovery } = useAuth();
  const [confirmLink, setConfirmLink] = useState(Boolean(initialAuthCallback.tokenHash));
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [complete, setComplete] = useState(false);
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const work = useRef(null);
  const lock = useRef(false);
  const recoveryUser = useRef(null);
  useEffect(() => {
    if (initialAuthCallback.tokenHash) {
      // A scanner can load this page without spending the single-use token.
      clearCallbackUrl(window.location, window.history);
      return;
    }

    let active = true;
    work.current ||= finishAuthCallback(supabase.auth, initialAuthCallback, 'recovery', window.sessionStorage);
    work.current.then(session => { if (active) { recoveryUser.current = session.user.id; setReady(true); } })
      .catch(failure => { if (active) { setError(failure.message); endRecovery(); } })
      .finally(() => { if (active) clearCallbackUrl(window.location, window.history); });
    return () => { active = false; };
  }, [endRecovery]);

  const continueRecovery = async () => {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const session = await verifyRecoveryLink(supabase.auth, initialAuthCallback.tokenHash, window.sessionStorage);
      recoveryUser.current = session.user.id;
      setReady(true);
    } catch (failure) {
      setError(failure.message);
      endRecovery();
    } finally {
      setConfirmLink(false);
      lock.current = false;
      setBusy(false);
    }
  };

  const submit = async event => {
    event.preventDefault();
    if (!ready || lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      await updateRecoveredPassword(supabase.auth, password, confirm, recoveryUser.current);
      endRecovery(); setComplete(true); setPassword(''); setConfirm(''); setReady(false);
      // A successful password change is independent of a possible sign-out failure.
      await supabase.auth.signOut({ scope: 'local' }).catch(() => {});
    } catch (failure) { setError(failure.message); }
    finally { lock.current = false; setBusy(false); }
  };
  return <div>
    <h1 className="text-2xl font-semibold text-heading mb-3">Choose a new password</h1>
    {error && <p role="alert" className="text-danger mb-5">{error}</p>}
    {confirmLink ? <>
      <p className="text-secondary mb-5">Confirm that you want to reset your InterviewIQ password.</p>
      <Button type="button" loading={busy} onClick={continueRecovery} className="w-full">Continue password reset</Button>
    </> : complete ? <p role="status" className="text-success">Your password was updated. Sign in with your new password.</p>
      : ready ? <form onSubmit={submit} className="space-y-5">
        <label className="block text-sm text-heading">New password
          <input type="password" autoComplete="new-password" minLength={6} required className="input-field mt-2"
            value={password} onChange={event => setPassword(event.target.value)} disabled={busy} />
        </label>
        <label className="block text-sm text-heading">Confirm password
          <input type="password" autoComplete="new-password" minLength={6} required className="input-field mt-2"
            value={confirm} onChange={event => setConfirm(event.target.value)} disabled={busy} />
        </label>
        <Button type="submit" loading={busy} className="w-full">Update password</Button>
      </form> : !error && <p role="status" className="text-secondary">Verifying your recovery link…</p>}
    <Link className="inline-block mt-6 text-primary" to={error && !ready ? '/forgot-password' : '/login'}>
      {error && !ready ? 'Request a new recovery link' : 'Back to sign in'}
    </Link>
  </div>;
}
