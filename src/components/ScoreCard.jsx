import { useEffect, useState } from 'react';

export default function ScoreCard({ score, label, size = 'md', className = '' }) {
  const [animatedScore, setAnimatedScore] = useState(0);

  const sizes = {
    sm: { width: 80, stroke: 6, fontSize: 'text-lg' },
    md: { width: 120, stroke: 8, fontSize: 'text-2xl' },
    lg: { width: 160, stroke: 10, fontSize: 'text-4xl' },
  };

  const s = sizes[size];
  const radius = (s.width - s.stroke) / 2;
  const circumference = 2 * Math.PI * radius;

  useEffect(() => {
    const timer = setTimeout(() => setAnimatedScore(score), 200);
    return () => clearTimeout(timer);
  }, [score]);

  const offset = circumference - (animatedScore / 100) * circumference;

  const getColor = (val) => {
    if (val >= 80) return { stroke: 'var(--ui-primary)', bg: 'text-primary' };
    if (val >= 60) return { stroke: '#92400e', bg: 'text-warning' };
    return { stroke: '#991b1b', bg: 'text-danger' };
  };

  const color = getColor(score);

  return (
    <div className={`flex flex-col items-center ${className}`}>
      <div className="relative" style={{ width: s.width, height: s.width }}>
        <svg width={s.width} height={s.width} className="transform -rotate-90">
          <circle
            cx={s.width / 2}
            cy={s.width / 2}
            r={radius}
            fill="none"
            stroke="var(--ui-line)"
            strokeWidth={s.stroke}
          />
          <circle
            cx={s.width / 2}
            cy={s.width / 2}
            r={radius}
            fill="none"
            stroke={color.stroke}
            strokeWidth={s.stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ transition: 'stroke-dashoffset 1s ease-out' }}
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={`${s.fontSize} tabular-nums font-semibold ${color.bg}`}>
            {animatedScore}
          </span>
        </div>
      </div>
      {label && <span className="text-sm text-secondary mt-2 font-medium">{label}</span>}
    </div>
  );
}

export function ScoreBar({ label, score, color = 'bg-primary', className = '' }) {
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setWidth(score), 200);
    return () => clearTimeout(timer);
  }, [score]);

  return (
    <div className={`${className}`}>
      <div className="flex justify-between items-center mb-1.5">
        <span className="text-sm text-heading">{label}</span>
        <span className="text-sm tabular-nums text-secondary">{score}%</span>
      </div>
      <div className="h-2 bg-subtle rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full  ${color} transition-all duration-1000 ease-out`}
          style={{ width: `${width}%` }}
        />
      </div>
    </div>
  );
}
