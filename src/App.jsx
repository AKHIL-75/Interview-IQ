import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { InterviewProvider } from './context/InterviewContext';
import { ToastProvider } from './context/ToastContext';

import DashboardLayout from './layouts/DashboardLayout';
import AuthLayout from './layouts/AuthLayout';
import ProtectedRoute from './components/ProtectedRoute';

import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import AuthCallbackPage from './pages/AuthCallbackPage';
import DashboardPage from './pages/DashboardPage';
import InterviewSetupPage from './pages/InterviewSetupPage';
import InterviewPage from './pages/InterviewPage';
import FeedbackPage from './pages/FeedbackPage';
import ReportPage from './pages/ReportPage';
import ProfilePage from './pages/ProfilePage';
import InterviewHistoryPage from './pages/InterviewHistoryPage';

import Toast from './components/Toast';

function RecoveryRedirect() {
  const { recoveryActive } = useAuth();
  const location = useLocation();
  return recoveryActive && location.pathname !== '/reset-password' ? <Navigate to="/reset-password" replace /> : null;
}

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <InterviewProvider>
          <Toast />
          <RecoveryRedirect />
          <Routes>
            {/* Public */}
            <Route path="/" element={<LandingPage />} />

            {/* Auth */}
            <Route element={<AuthLayout />}>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
            </Route>
            <Route element={<AuthLayout allowAuthenticated />}>
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
              <Route path="/reset-password" element={<ResetPasswordPage />} />
              <Route path="/auth/callback" element={<AuthCallbackPage />} />
            </Route>

            {/* Protected — Dashboard layout */}
            <Route element={<DashboardLayout />}>
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/interview/setup" element={<InterviewSetupPage />} />
              <Route path="/interview/feedback" element={<FeedbackPage />} />
              <Route path="/report" element={<ReportPage />} />
              <Route path="/profile" element={<ProfilePage />} />
              <Route path="/history" element={<InterviewHistoryPage />} />
            </Route>

            {/* Interview — Full screen (no sidebar), protected */}
            <Route path="/interview" element={
              <ProtectedRoute>
                <InterviewPage />
              </ProtectedRoute>
            } />

            {/* Catch-all */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </InterviewProvider>
      </ToastProvider>
    </AuthProvider>
  );
}
