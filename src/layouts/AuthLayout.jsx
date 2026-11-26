import { Outlet, Navigate } from 'react-router-dom';
import { Brain } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function AuthLayout({ allowAuthenticated = false }) {
  const { user, loading } = useAuth();

  if (loading) return null;
  if (user && !allowAuthenticated) return <Navigate to="/dashboard" replace />;

  return (
    <div className="min-h-screen bg-page flex">
      {/* Branding panel - desktop only */}
      <div className="bg-selected border-r border-line hidden lg:flex lg:w-1/2 xl:w-[45%] relative overflow-hidden">
        
        

        <div className="relative z-10 flex flex-col justify-center px-12 xl:px-16">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-12 h-12 rounded-lg bg-primary flex items-center justify-center">
              <Brain className="w-7 h-7 text-white" />
            </div>
            <span className="text-2xl font-semibold text-heading">Interview-IQ</span>
          </div>

          <h1 className="text-4xl xl:text-5xl font-semibold text-heading leading-tight mb-4">
            Interview smarter.
            <br />
            <span className="gradient-text">Get hired faster.</span>
          </h1>

          <p className="text-secondary text-lg leading-relaxed max-w-md">
            AI-powered personalized mock interviews built around your resume and the job you want.
          </p>

          <div className="mt-10 grid grid-cols-2 gap-6 border-t border-indigo-200 pt-6">
            {[
              { value: '10K+', label: 'Interviews Conducted' },
              { value: '95%', label: 'Satisfaction Rate' },
              { value: '500+', label: 'Companies Covered' },
              { value: '82%', label: 'Avg. Score Improvement' },
            ].map((stat, i) => (
              <div key={i}>
                <p className="text-2xl tabular-nums font-semibold text-heading">{stat.value}</p>
                <p className="text-sm text-secondary">{stat.label}</p>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Form panel */}
      <div className="bg-surface flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-md">
          <Outlet />
        </div>
      </div>
    </div>
  );
}
