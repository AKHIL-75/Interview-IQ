export default function Card({ children, className = '', hover = false, padding = true, ...props }) {
  return (
    <div
      className={`${hover ? 'glass-card-hover' : 'glass-card'} ${padding ? 'p-6' : ''} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export function CardHeader({ children, className = '' }) {
  return (
    <div className={`mb-4 ${className}`}>
      {children}
    </div>
  );
}

export function CardTitle({ children, className = '' }) {
  return (
    <h3 className={`text-lg font-semibold text-heading ${className}`}>
      {children}
    </h3>
  );
}
