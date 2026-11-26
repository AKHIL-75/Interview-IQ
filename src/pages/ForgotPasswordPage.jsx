import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import Button from '../components/Button';

export default function ForgotPasswordPage() {
  const { requestReset } = useAuth();
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const lock = useRef(false);
  const submit = async (event) => {
    event.preventDefault();
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(''); setMessage('');
    try { setMessage(await requestReset(email)); }
    catch (failure) { setError(failure.message); }
    finally { lock.current = false; setBusy(false); }
  };
  return <div>
    <h1 className="text-2xl font-semibold text-heading mb-2">Reset your password</h1>
    <p className="text-secondary mb-8">Enter your email to request a recovery link.</p>
    <form onSubmit={submit} className="space-y-5">
      <label className="block text-heading text-sm">Email
        <input className="input-field mt-2" type="email" autoComplete="email" required value={email}
          onChange={event => setEmail(event.target.value)} disabled={busy} />
      </label>
      {message && <p role="status" className="text-success">{message}</p>}
      {error && <p role="alert" className="text-danger">{error}</p>}
      <Button type="submit" loading={busy} className="w-full">Send reset link</Button>
    </form>
    <Link to="/login" className="inline-block mt-6 text-primary">Back to sign in</Link>
  </div>;
}
