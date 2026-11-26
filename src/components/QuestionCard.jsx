import Badge from './Badge';

export default function QuestionCard({ question, number, total, difficulty, topic, focus, stage, isDynamic = false, className = '' }) {
  const difficultyColors = {
    Easy: 'success',
    Medium: 'warning',
    Hard: 'danger',
  };

  const stageLabels = {
    INTRO: 'Introduction',
    RESUME_JD: 'Resume & Role',
    TECHNICAL_FUNDAMENTALS: 'Fundamentals',
    PROJECT: 'Project Experience',
    ADVANCED_TECHNICAL: 'Advanced Architecture',
    ADAPTIVE: 'Adaptive Follow-up',
  };

  const getFocusVariant = (f) => {
    if (!f) return 'default';
    if (f.includes('Follow-up')) return 'warning';
    if (f.includes('Challenge')) return 'purple';
    return 'default';
  };

  return (
    <div className={`${className}`}>
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <span className="text-sm text-secondary tabular-nums">
          {isDynamic ? `Question ${number} (Dynamic Mode)` : `Question ${number} of ${total}`}
        </span>
        {stage && stageLabels[stage] && (
          <Badge variant="purple" size="sm">{stageLabels[stage]}</Badge>
        )}
        <Badge variant={difficultyColors[difficulty] || 'default'} size="sm">{difficulty}</Badge>
        {topic && <Badge variant="info" size="sm">{topic}</Badge>}
        {focus && focus !== 'General' && focus !== 'Introduction' && (
          <Badge variant={getFocusVariant(focus)} size="sm">{focus}</Badge>
        )}
      </div>
      <h2 className="text-xl md:text-2xl font-semibold text-heading leading-relaxed">
        {question}
      </h2>
    </div>
  );
}
