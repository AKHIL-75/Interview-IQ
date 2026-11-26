import { CheckCircle, Circle, ArrowRight } from 'lucide-react';

export default function InterviewProgress({ topics, currentIndex, totalQuestions, answeredCount, isDynamic = false, className = '' }) {
  const currentNum = typeof currentIndex === 'number' ? currentIndex + 1 : answeredCount + 1;
  const progress = isDynamic
    ? Math.min(100, (answeredCount / 5) * 100)
    : (totalQuestions > 0 ? (answeredCount / totalQuestions) * 100 : 0);

  return (
    <div className={className}>
      <div className="mb-6">
        <div className="flex justify-between items-center mb-2">
          <span className="text-sm font-medium text-heading">
            {isDynamic ? `Question ${currentNum} (Dynamic)` : `Question ${totalQuestions > 0 ? Math.min(currentNum, totalQuestions) : 0} of ${totalQuestions}`}
          </span>
          <span className="text-sm text-secondary tabular-nums">
              {isDynamic ? (answeredCount >= 5 ? 'Minimum Reached' : `${answeredCount}/5 Min`) : `${Math.round(progress)}%`}
          </span>
        </div>
        <div className="h-2 bg-subtle rounded-full overflow-hidden">
          <div
            className="h-full rounded-full bg-primary transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      <div className="space-y-1">
        <h4 className="text-xs font-semibold text-secondary uppercase  mb-3">Topics</h4>
        {topics.map((topic, index) => (
          <div
            key={index}
            className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
              topic.status === 'current' ? 'bg-selected border border-primary' : ''
            }`}
          >
            {topic.status === 'completed' ? (
              <CheckCircle className="w-4 h-4 text-success flex-shrink-0" />
            ) : topic.status === 'current' ? (
              <ArrowRight className="w-4 h-4 text-primary flex-shrink-0" />
            ) : (
              <Circle className="w-4 h-4 text-secondary flex-shrink-0" />
            )}
            <span className={`text-sm ${
              topic.status === 'completed'
                ? 'text-secondary'
                : topic.status === 'current'
                  ? 'text-heading font-medium'
                  : 'text-secondary'
            }`}>
              {topic.name}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
