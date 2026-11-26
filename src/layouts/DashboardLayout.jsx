import { useState } from 'react';
import { Outlet, Navigate } from 'react-router-dom';
import { Menu } from 'lucide-react';
import Sidebar from '../components/Sidebar';
import { useAuth } from '../context/AuthContext';

export default function DashboardLayout() {
  const { user, loading } = useAuth();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="min-h-screen bg-page">
      <Sidebar isOpen={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      {/* Mobile header */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-30 bg-surface  border-b border-line px-4 py-3">
        <button aria-label="Open navigation" aria-expanded={sidebarOpen}
          onClick={() => setSidebarOpen(true)}
          className="p-2 text-secondary hover:text-heading hover:bg-subtle rounded-lg"
        >
          <Menu className="w-5 h-5" />
        </button>
      </div>

      {/* Main content */}
      <main className="lg:ml-64 min-h-screen pt-14 lg:pt-0">
        <Outlet />
      </main>
    </div>
  );
}
