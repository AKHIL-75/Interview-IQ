import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { supabase } from '../lib/supabase';
import { initialAuthCallback, finishAuthCallback, clearCallbackUrl } from '../services/authFlows';

export default function AuthCallbackPage() {
  const navigate = useNavigate();
  const [error, setError] = useState('');
  const work = useRef(null);
  useEffect(() => {
    let active = true;
    work.current ||= finishAuthCallback(supabase.auth, initialAuthCallback, 'oauth', window.sessionStorage);
    work.current.then(() => {
      if (active) navigate('/dashboard', { replace: true });
    }).catch(failure => { if (active) setError(failure.message); })
      .finally(() => { if (active) clearCallbackUrl(window.location, window.history); });
    return () => { active = false; };
  }, [navigate]);
  return <div>
    <h1 className="text-2xl font-semibold text-heading mb-3">Google sign-in</h1>
    {error ? <><p role="alert" className="text-danger">{error}</p>
      <Link className="inline-block mt-6 text-primary" to="/login">Back to sign in</Link></>
      : <p role="status" className="text-secondary">Verifying your session…</p>}
  </div>;
}
