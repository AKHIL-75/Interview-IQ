export default function SkillBadge({ skill, variant = 'default', className = '' }) {
  const variants = {
    default: 'bg-selected text-primary border-primary',
    found: 'bg-success-surface text-success border-emerald-300',
    related: 'bg-sky-50 text-sky-800 border-sky-300',
    not_evidenced: 'bg-warning-surface text-warning border-amber-300',
    gap: 'bg-danger-surface text-danger border-red-300',
    neutral: 'bg-subtle text-heading border-line',
  };

  return (
    <span className={`inline-flex max-w-full items-center break-words px-2.5 py-1 text-sm rounded-md border ${variants[variant] || variants.default} ${className}`}>
      {skill}
    </span>
  );
}
