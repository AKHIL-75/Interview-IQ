import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff, User, Brain } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../context/ToastContext';
import Button from '../components/Button';

export default function RegisterPage() {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const { register } = useAuth();
  const { success, error } = useToast();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    if (!name || !email || !password || !confirmPassword) {
      error('Please fill in all fields');
      return;
    }
    if (password !== confirmPassword) {
      error('Passwords do not match');
      return;
    }
    if (password.length < 6) {
      error('Password must be at least 6 characters');
      return;
    }
    setLoading(true);
    try {
      const result = await register(name, email, password);
      if (result?.confirmationRequired) {
        success('Check your inbox to confirm your email before signing in.');
        navigate('/login');
      } else {
        success('Account created successfully!');
        navigate('/dashboard');
      }
    } catch (err) {
      error(err?.message || 'Registration failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      {/* Mobile branding */}
      <div className="lg:hidden text-center mb-8">
        <div className="flex items-center justify-center gap-2.5 mb-4">
          <div className="w-10 h-10 rounded-lg bg-primary flex items-center justify-center">
            <Brain className="w-6 h-6 text-white" />
          </div>
          <span className="text-xl font-semibold text-heading">Interview-IQ</span>
        </div>
      </div>

      <h1 className="text-2xl font-semibold text-heading mb-1">Create your account</h1>
      <p className="text-secondary mb-8">Start preparing for your dream job interview</p>

      <form onSubmit={handleSubmit} className="space-y-5">
        <div>
          <label htmlFor="full-name" className="block text-sm font-medium text-heading mb-2">Full Name</label>
          <div className="relative">
            <User className="absolute left-3.5 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-secondary" />
            <input id="full-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Alex Kumar"
              className="input-field pl-11"
            />
          </div>
        </div>

        <div>
          <label htmlFor="email" className="block text-sm font-medium text-heading mb-2">Email</label>
          <div className="relative">
            <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-secondary" />
            <input id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="alex@example.com"
              className="input-field pl-11"
            />
          </div>
        </div>

        <div>
          <label htmlFor="password" className="block text-sm font-medium text-heading mb-2">Password</label>
          <div className="relative">
            <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-secondary" />
            <input id="password"
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Min. 6 characters"
              className="input-field pl-11 pr-11"
            />
            <button
              type="button"
              aria-label={showPassword ? "Hide password" : "Show password"}
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 text-secondary hover:text-heading transition-colors"
            >
              {showPassword ? <EyeOff className="w-[18px] h-[18px]" /> : <Eye className="w-[18px] h-[18px]" />}
            </button>
          </div>
        </div>

        <div>
          <label htmlFor="confirm-password" className="block text-sm font-medium text-heading mb-2">Confirm Password</label>
          <div className="relative">
            <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 w-[18px] h-[18px] text-secondary" />
            <input id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Confirm your password"
              className="input-field pl-11"
            />
          </div>
        </div>

        <Button type="submit" loading={loading} className="w-full py-3.5">
          Create Account
        </Button>
      </form>

      <p className="text-center text-sm text-secondary mt-8">
        Already have an account?{' '}
        <Link to="/login" className="text-primary hover:text-primary font-medium transition-colors">
          Sign in
        </Link>
      </p>
    </div>
  );
}
