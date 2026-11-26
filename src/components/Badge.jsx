export default function Badge({ children, variant = 'default', size = 'md', className = '' }) {
  const variants = {
    neutral: 'bg-subtle text-secondary border-line',
    purple: 'bg-violet-50 text-violet-800 border-violet-300',
    default: 'bg-subtle text-heading border-line',
    accent: 'bg-selected text-primary border-primary',
    success: 'bg-success-surface text-success border-emerald-300',
    warning: 'bg-warning-surface text-warning border-amber-300',
    danger: 'bg-danger-surface text-danger border-red-300',
    info: 'bg-cyan-50 text-cyan-800 border-cyan-300',
  };

  const sizes = {
    sm: 'px-2 py-0.5 text-xs',
    md: 'px-3 py-1 text-sm',
    lg: 'px-4 py-1.5 text-sm',
  };

  return (
    <span className={`inline-flex items-center font-medium rounded-md border ${variants[variant]} ${sizes[size]} ${className}`}>
      {children}
    </span>
  );
}
