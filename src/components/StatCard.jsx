import { TrendingUp, TrendingDown } from 'lucide-react';

export default function StatCard({ title, value, suffix = '', icon: Icon, trend, trendLabel, className = '' }) {
  const isPositive = trend > 0;

  return (
    <div className={`glass-card p-4 sm:p-6 ${className}`}>
      <div className="flex items-start justify-between mb-4">
        <span className="text-sm text-secondary font-medium">{title}</span>
        {Icon && (
          <div className="shrink-0 pl-2">
            <Icon className="w-4 h-4 text-secondary" />
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-3xl tabular-nums font-semibold text-heading">
          {value}{suffix}
        </span>
        {trend !== undefined && (
          <div className={`flex items-center gap-1 text-sm font-medium ${isPositive ? 'text-success' : 'text-danger'}`}>
            {isPositive ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
            {isPositive ? '+' : ''}{trend}%
          </div>
        )}
      </div>
      {trendLabel && (
        <span className="text-xs text-secondary mt-1 block">{trendLabel}</span>
      )}
    </div>
  );
}
