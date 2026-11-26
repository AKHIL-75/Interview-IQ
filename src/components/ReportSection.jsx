import { ChevronDown, ChevronUp } from 'lucide-react';
import { useId, useState } from 'react';

export default function ReportSection({ title, icon: Icon, children, defaultOpen = true, className = '' }) {
  const panelId = useId();
  const [isOpen, setIsOpen] = useState(defaultOpen);

  return (
    <div className={`glass-card overflow-hidden ${className}`}>
      <button
        aria-expanded={isOpen}
        aria-controls={isOpen ? panelId : undefined}
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between gap-4 px-4 py-4 sm:px-6 text-left hover:bg-subtle transition-colors"
      >
        <div className="flex items-center gap-3">
          {Icon && <Icon className="w-5 h-5 text-primary" />}
          <h3 className="text-lg font-semibold text-heading">{title}</h3>
        </div>
        {isOpen ? (
          <ChevronUp className="w-5 h-5 text-secondary" />
        ) : (
          <ChevronDown className="w-5 h-5 text-secondary" />
        )}
      </button>
      {isOpen && (
        <div id={panelId} className="px-4 sm:px-6 pb-6 animate-fade-in">
          {children}
        </div>
      )}
    </div>
  );
}
