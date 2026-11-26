import { useState } from 'react';
import { useToast } from '../context/ToastContext';
import { useNavigate } from 'react-router-dom';
import {
  CheckCircle, AlertTriangle, Lightbulb, ArrowRight,
  Target, MessageSquare, BookOpen, Sparkles
} from 'lucide-react';
import { useInterview } from '../context/InterviewContext';
import Card from '../components/Card';
import ScoreCard, { ScoreBar } from '../components/ScoreCard';
import Button from '../components/Button';
import { CONCEPTUAL_RUBRIC, OPTIONAL_SUGGESTIONS_HEADING, suggestionText } from '../services/evaluationRubric';

export default function FeedbackPage() {
  const { feedback, evaluation, questions, currentQuestionIndex, nextQuestion, generateReport, session } = useInterview();
  const navigate = useNavigate();

  const [busy, setBusy] = useState(false);
  const { error } = useToast();
  const fb = feedback;
  if (!fb) return <div className="content-area"><p>No evaluated answer is available.</p><Button onClick={() => navigate('/interview')}>Back to interview</Button></div>;
  const conceptual = fb.rubric_version === CONCEPTUAL_RUBRIC;
  const optionalSuggestions = conceptual && fb.answer_status === 'CORRECT';

  const handleNextQuestion = async () => {
    if (busy) return;
    setBusy(true);
    try {
    const hasMore = nextQuestion();
    if (hasMore) {
      navigate('/interview');
    } else {
      const rep = await generateReport();
      const activeSessionId = session?.sessionId || rep?.sessionId;
      if (activeSessionId) {
        navigate(`/report?session_id=${encodeURIComponent(activeSessionId)}`);
      } else {
        navigate('/report');
      }
    }
    } catch (err) { error(err.message); } finally { setBusy(false); }
  };

  return (
    <div className="print-report content-area animate-fade-in">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-selected border border-primary text-primary text-sm font-medium mb-4">
            <Sparkles className="w-4 h-4" />
            AI Feedback
          </div>
          <h1 className="text-2xl sm:text-3xl font-semibold text-heading">Answer Evaluation</h1>
        </div>

        {/* Overall Score */}
        <Card className="flex flex-col items-center py-8 mb-6">
          <ScoreCard score={fb.overallScore} size="lg" label="Overall Score" />
        </Card>

        {/* Score Breakdown */}
        <div className={"grid grid-cols-2 gap-4 mb-6 " + (conceptual ? 'md:grid-cols-3' : 'md:grid-cols-4')}>
          {[
            { label: 'Technical Accuracy', score: fb.scores?.technicalAccuracy ?? 0, icon: Target },
            { label: conceptual ? 'Clarity' : 'Communication / Clarity', score: fb.scores?.communication ?? fb.scores?.clarity ?? 0, icon: MessageSquare },
            ...(!conceptual ? [{ label: 'Depth', score: fb.scores?.depth ?? 0, icon: BookOpen }] : []),
            { label: 'Relevance', score: fb.scores?.relevance ?? 0, icon: Sparkles },
          ].map((item, i) => (
            <Card key={i} className="text-center">
              <item.icon className="w-5 h-5 text-primary mx-auto mb-2" />
              <p className="text-2xl tabular-nums font-semibold text-heading mb-1">{item.score}%</p>
              <p className="text-xs text-secondary">{item.label}</p>
            </Card>
          ))}
        </div>

        {/* Strengths & Improvements */}
        <div className="grid md:grid-cols-2 gap-6 mb-6">
          <Card>
            <div className="flex items-center gap-2 mb-4">
              <CheckCircle className="w-5 h-5 text-success" />
              <h3 className="font-semibold text-heading">What You Did Well</h3>
            </div>
            <ul className="space-y-3">
              {fb.strengths.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-600 mt-2 flex-shrink-0" />
                  <span className="text-sm leading-relaxed text-ink">{item}</span>
                </li>
              ))}
            </ul>
          </Card>

          <Card>
            <div className="flex items-center gap-2 mb-4">
              {optionalSuggestions ? <Lightbulb className="w-5 h-5 text-primary" /> : <AlertTriangle className="w-5 h-5 text-warning" />}
              <h3 className="font-semibold text-heading">{optionalSuggestions ? OPTIONAL_SUGGESTIONS_HEADING : 'Areas to Improve'}</h3>
            </div>
            <ul className="space-y-3">
              {fb.improvements.map((item, i) => (
                <li key={i} className="flex items-start gap-3">
                  <div className="w-1.5 h-1.5 rounded-full bg-amber-600 mt-2 flex-shrink-0" />
                  <span className="text-sm leading-relaxed text-ink">{optionalSuggestions ? suggestionText(item) : item}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        {/* Suggested Answer */}
        <Card className="mb-8">
          <div className="flex items-center gap-2 mb-4">
            <Lightbulb className="w-5 h-5 text-primary" />
            <h3 className="font-semibold text-heading">Suggested Answer</h3>
          </div>
          <p className="text-sm text-heading leading-relaxed bg-selected rounded-lg p-4 border border-primary">
            {fb.suggestedAnswer}
          </p>
        </Card>

        {/* Actions */}
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Button variant="secondary" onClick={() => navigate('/interview')}>
            Back to Interview
          </Button>
          <Button onClick={handleNextQuestion} disabled={busy} icon={ArrowRight}>
            {currentQuestionIndex >= questions.length - 1 ? 'View Full Report' : 'Next Question'}
          </Button>
        </div>
      </div>
    </div>
  );
}
