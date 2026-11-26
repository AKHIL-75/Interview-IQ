import { NavLink, useNavigate } from 'react-router-dom';
import {
  Brain, LayoutDashboard, PlusCircle, History, BarChart3,
  User, Settings, LogOut, X, ChevronLeft
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Sidebar({ isOpen, onClose }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const navItems = [
    { path: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/interview/setup', icon: PlusCircle, label: 'New Interview' },
    { path: '/history', icon: History, label: 'Interview History' },
    { path: '/report', icon: BarChart3, label: 'Reports' },
    { path: '/profile', icon: User, label: 'Profile' },
  ];

  const handleLogout = () => {
    logout();
    navigate('/');
  };

  return (
    <>
      {/* Mobile overlay */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/50  z-40 lg:hidden"
          onClick={onClose}
        />
      )}

      <aside className={`fixed top-0 left-0 h-full w-64 bg-surface  border-r border-line z-50 transition-transform duration-300 flex flex-col
        ${isOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
      `}>
        {/* Logo */}
        <div className="flex items-center justify-between px-5 py-5 border-b border-line">
          <NavLink to="/dashboard" className="flex items-center gap-2.5" onClick={onClose}>
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <Brain className="w-5 h-5 text-white" />
            </div>
            <span className="text-lg font-semibold text-heading">Interview-IQ</span>
          </NavLink>
          <button aria-label="Close navigation"
            className="lg:hidden p-1.5 text-secondary hover:text-heading rounded-lg hover:bg-subtle"
            onClick={onClose}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Nav links */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {navItems.map(({ path, icon: Icon, label }) => (
            <NavLink
              key={path}
              to={path}
              onClick={onClose}
              className={({ isActive }) =>
                isActive ? 'sidebar-link-active' : 'sidebar-link'
              }
            >
              <Icon className="w-5 h-5" />
              {label}
            </NavLink>
          ))}
        </nav>

        {/* User section */}
        <div className="border-t border-line p-4">
          <div className="flex items-center gap-3 mb-3">
            <div className="w-9 h-9 rounded-full bg-selected flex items-center justify-center">
              <span className="text-sm font-semibold text-primary">
                {user?.name?.charAt(0) || 'A'}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-heading truncate">{user?.name || 'Alex Kumar'}</p>
              <p className="text-xs text-secondary truncate">{user?.email || 'alex@example.com'}</p>
            </div>
          </div>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-2 px-3 py-2 text-sm text-secondary hover:text-danger hover:bg-danger-surface rounded-lg transition-colors"
          >
            <LogOut className="w-4 h-4" />
            Sign Out
          </button>
        </div>
      </aside>
    </>
  );
}
