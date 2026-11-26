import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';
import { useToast } from '../context/ToastContext';

export default function Toast() {
  const { toasts, removeToast, placement } = useToast();

  const icons = {
    success: <CheckCircle className="w-5 h-5 text-success" />,
    error: <AlertCircle className="w-5 h-5 text-danger" />,
    info: <Info className="w-5 h-5 text-primary" />,
  };

  const borders = {
    success: 'border-emerald-300',
    error: 'border-red-300',
    info: 'border-primary',
  };

  if (toasts.length === 0) return null;

  return (
    <div className={placement === 'immersive' ? 'immersive-toasts fixed left-1/2 -translate-x-1/2 z-[60] flex flex-col gap-2 w-[min(90vw,480px)]' : 'fixed top-4 right-4 z-[60] flex flex-col gap-2 max-w-sm'}>
      {toasts.map((toast) => (
        <div
          key={toast.id}
          role={toast.type === 'error' ? 'alert' : 'status'}
          className={`${placement === 'immersive' ? 'bg-surface rounded-lg' : 'glass-card'} p-4 flex items-start gap-3 animate-slide-in-right border ${borders[toast.type]}`}
        >
          {icons[toast.type]}
          <span className="text-sm text-ink flex-1">{toast.message}</span>
          {toast.action && <button className="min-h-11 px-2 text-sm text-primary focus-visible:ring-2 focus-visible:ring-primary rounded-lg" onClick={() => { removeToast(toast.id); toast.action.onClick(); }}>{toast.action.label}</button>}
          <button
            aria-label="Dismiss notification"
            onClick={() => removeToast(toast.id)}
            className="min-w-11 min-h-11 flex items-center justify-center text-secondary hover:text-heading transition-colors focus-visible:ring-2 focus-visible:ring-primary rounded-lg"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  );
}
