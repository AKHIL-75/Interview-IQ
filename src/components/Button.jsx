import { Loader2 } from 'lucide-react';

export default function Button({
  children, variant = 'primary', size = 'md', loading = false,
  disabled = false, icon: Icon, className = '', ...props
}) {
  const variants = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    ghost: 'btn-ghost',
    danger: 'min-h-11 px-5 py-2.5 border border-red-300 bg-danger-surface text-danger hover:bg-red-100 font-medium rounded-md',
  };

  const sizes = {
    sm: 'px-3 py-1.5 text-sm',
    md: '',
    lg: 'px-8 py-4 text-lg',
  };

  return (
    <button
      className={`${variants[variant]} ${sizes[size]} inline-flex items-center justify-center gap-2 ${className}`}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : Icon && <Icon className="w-4 h-4" />}
      {children}
    </button>
  );
}
