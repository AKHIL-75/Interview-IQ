import { useEffect } from 'react';
import { X } from 'lucide-react';

export default function Modal({ isOpen, onClose, title, children, size = 'md', className = '' }) {
  const sizes = {
    sm: 'max-w-md',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
  };

  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 " onClick={onClose} />
      <div role="dialog" aria-modal="true" aria-label={title} className={`relative w-full ${sizes[size]} glass-card p-0 animate-fade-in ${className}`}>
        <div className="flex items-center justify-between p-6 border-b border-line">
          <h2 className="text-lg font-semibold text-heading">{title}</h2>
          <button
            aria-label="Close dialog" onClick={onClose}
            className="p-2 text-secondary hover:text-heading hover:bg-subtle rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-6">
          {children}
        </div>
      </div>
    </div>
  );
}
