/**
 * ProtectedRoute — Phase 11
 *
 * Wraps routes that require authentication.
 * Redirects to /login if the user is not authenticated.
 * Shows nothing while the auth state is loading to prevent flash.
 */

import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export default function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();

  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;

  return children;
}
