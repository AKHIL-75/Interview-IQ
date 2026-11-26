import { useEffect, useState } from 'react';

export default function ProgressBar({ value = 0, max = 100, color = 'bg-primary', label, showPercentage = true, className = '' }) {
  const [width, setWidth] = useState(0);
  const percentage = Math.round((value / max) * 100);

  useEffect(() => {
    const timer = setTimeout(() => setWidth(percentage), 100);
    return () => clearTimeout(timer);
  }, [percentage]);

  return (
    <div className={`w-full ${className}`}>
      {(label || showPercentage) && (
        <div className="flex justify-between items-center mb-2">
          {label && <span className="text-sm text-heading font-medium">{label}</span>}
          {showPercentage && <span className="text-sm text-secondary tabular-nums">{percentage}%</span>}
        </div>
      )}
      <div className="progress-bar">
        <div
          className={`progress-fill  ${color}`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}
