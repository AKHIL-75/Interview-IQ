import { useState, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Award, TrendingUp, AlertTriangle, CheckCircle,
  BarChart3, Brain, Target, MessageSquare, Shield, Briefcase,
  Calendar, Clock, FileText, Lightbulb, RotateCcw, LayoutDashboard,
  Loader2, Layers, Zap, ChevronDown, ChevronUp, Check, XCircle
} from 'lucide-react';
import { useInterview } from '../context/InterviewContext';
import Card from '../components/Card';
import ScoreCard, { ScoreBar } from '../components/ScoreCard';
import SkillBadge from '../components/SkillBadge';
import ReportSection from '../components/ReportSection';
import Button from '../components/Button';
import { fetchReportById } from '../services/api';
import { CONCEPTUAL_RUBRIC, MIXED_RUBRICS, OPTIONAL_SUGGESTIONS_HEADING, suggestionText } from '../services/evaluationRubric';

function referenceAnswer(q) {
  const text = q.suggested_answer || q.suggestedAnswer;
  const normalize = value => String(value || '').toLowerCase().replace(/[\W_]+/g, '');
  if (typeof text !== 'string' || !text.trim() || [q.question, q.candidate_answer || q.candidateAnswer].some(value => normalize(value) === normalize(text))) return '';
  return text;
}
function evaluationAvailable(q) {
  return ![q.evaluation_status, q.answer_status].some(status => ['UNAVAILABLE', 'FAILED', 'ERROR'].includes(status))
    && Number.isFinite(q.score) && q.score >= 0 && q.score <= 100;
}
const dimensionMark = value => Number.isFinite(value) ? `${value}%` : 'Unavailable';

/**
 * Normalizes any report object (from Supabase REST or in-memory React state)
 * into a consistent, robust structure for rendering.
 */
function normalizeReportData(r) {
  if (!r) return null;

  const rawScores = r.scores || {};
  const overallScore = typeof r.overall_score === 'number'
    ? r.overall_score
    : (typeof r.overallScore === 'number' ? r.overallScore : (rawScores.overall || 0));

  // Determine standard grade
  const grade = r.grade || rawScores.grade || (
    overallScore >= 90 ? 'A+' :
    overallScore >= 80 ? 'A' :
    overallScore >= 70 ? 'B' :
    overallScore >= 60 ? 'C' :
    overallScore >= 50 ? 'D' : 'F'
  );

  const gradeLabel = r.grade_label || r.gradeLabel || rawScores.grade_label || (
    grade === 'A+' ? 'Outstanding Performance' :
    grade === 'A' ? 'Strong Performance' :
    grade === 'B' ? 'Proficient Performance' :
    grade === 'C' ? 'Developing Performance' :
    grade === 'D' ? 'Needs Improvement' : 'Unsatisfactory Performance'
  );

  // Authoritative Phase 10 Dimensions
  const techAcc = r.dimensions?.technical_accuracy
    ?? rawScores.technical_accuracy
    ?? rawScores.technicalKnowledge
    ?? rawScores.technicalAccuracy
    ?? null;

  const rel = r.dimensions?.relevance
    ?? rawScores.relevance
    ?? rawScores.jobRelevance
    ?? rawScores.experienceMatch
    ?? null;

  const depth = r.dimensions?.depth
    ?? rawScores.depth
    ?? rawScores.problemSolving
    ?? null;

  const clarity = r.dimensions?.clarity
    ?? rawScores.clarity
    ?? rawScores.communication
    ?? null;

  const questionAnalysis = Array.isArray(r.question_analysis)
    ? r.question_analysis
    : (Array.isArray(r.questionAnalysis) ? r.questionAnalysis : []);

  const hasEvaluations = questionAnalysis.length > 0
    ? questionAnalysis.some(q => q.skipped || evaluationAvailable(q))
    : rawScores.questions_evaluated !== 0;

  // Skill / Topic Analysis
  let skillAnalysis = r.skill_analysis || rawScores.skill_analysis || r.skillAnalysis || [];
  if ((!skillAnalysis || skillAnalysis.length === 0) && questionAnalysis.length > 0) {
    const topicMap = {};
    questionAnalysis.forEach(qa => {
      if (!evaluationAvailable(qa)) return;
      const t = qa.topic || 'General';
      if (!topicMap[t]) {
        topicMap[t] = { topic: t, category: qa.category || 'Technical', scores: [] };
      }
      topicMap[t].scores.push(qa.score ?? 0);
    });
    skillAnalysis = Object.values(topicMap).map(tm => {
      const avg = Math.round(tm.scores.reduce((sum, v) => sum + v, 0) / tm.scores.length);
      return {
        topic: tm.topic,
        category: tm.category,
        question_count: tm.scores.length,
        average_score: avg,
        proficiency: avg >= 80 ? 'Strong' : avg >= 65 ? 'Proficient' : 'Needs Practice',
      };
    }).sort((a, b) => b.average_score - a.average_score);
  }

  // Adaptive Interview Summary
  let adaptiveSummary = r.adaptive_summary || rawScores.adaptive_summary || r.adaptiveSummary || null;
  if (!adaptiveSummary && questionAnalysis.length > 0) {
    const followUps = questionAnalysis.filter(q => q.is_follow_up || q.isFollowUp);
    const followUpTopics = Array.from(new Set(followUps.map(q => q.topic || 'Technical')));
    adaptiveSummary = {
      total_follow_ups: followUps.length,
      follow_up_topics: followUpTopics,
      difficulty_progression: 'Maintained consistent difficulty progression',
      adaptability_rating: followUps.length >= 2 ? 'High Adaptability' : followUps.length === 1 ? 'Standard Adaptability' : 'Direct Assessment',
      summary_text: followUps.length > 0
        ? `The interview adapted with ${followUps.length} targeted follow-up questions in ${followUpTopics.slice(0, 3).join(', ')} to evaluate deeper technical understanding.`
        : 'The interview covered planned competency stages with consistent technical assessment.',
    };
  }

  const durationSecs = r.duration_secs || r.durationSecs || 0;
  const durationFormatted = r.duration || `${Math.max(1, Math.round(durationSecs / 60))} min`;

  const validAnswerCount = questionAnalysis.length > 0
    ? questionAnalysis.filter(q => !q.skipped && evaluationAvailable(q)).length
    : (r.questions_answered ?? r.questionsAnswered ?? 0);

  const totalQuestionsCount = r.total_questions ?? r.totalQuestions ?? (questionAnalysis.length || 0);

  return {
    id: r.id,
    sessionId: r.session_id || r.sessionId,
    role: r.role || 'Software Engineer',
    interviewType: r.interview_type || r.interviewType || 'Technical',
    difficulty: r.difficulty || 'Medium',
    subject: r.subject || r.scores?.subject || null,
    date: r.created_at
      ? new Date(r.created_at).toLocaleDateString('en-US', {
          month: 'short',
          day: 'numeric',
          year: 'numeric',
        })
      : (r.date || 'Recent'),
    duration: durationFormatted,
    durationSecs,
    questionsAnswered: validAnswerCount,
    totalQuestions: totalQuestionsCount,
    overallScore,
    rubricVersion: rawScores.rubric_version,
    hasEvaluations,
    grade: hasEvaluations ? grade : '—',
    gradeLabel: hasEvaluations ? gradeLabel : 'Evaluation unavailable',
    dimensions: {
      technical_accuracy: hasEvaluations ? techAcc : null,
      relevance: hasEvaluations ? rel : null,
      depth: hasEvaluations ? depth : null,
      clarity: hasEvaluations ? clarity : null,
    },
    scores: {
      technicalAccuracy: techAcc,
      relevance: hasEvaluations ? rel : null,
      depth: hasEvaluations ? depth : null,
      clarity: hasEvaluations ? clarity : null,
      technicalKnowledge: techAcc,
      problemSolving: depth,
      communication: clarity,
      confidence: rawScores.confidence ?? null,
      jobRelevance: rel,
    },
    strengths: Array.isArray(r.strengths) ? r.strengths : [],
    skillGaps: Array.isArray(r.skill_gaps) ? r.skill_gaps : (Array.isArray(r.skillGaps) ? r.skillGaps : []),
    skillAnalysis,
    adaptiveSummary,
    questionAnalysis,
    recommendations: Array.isArray(r.recommendations) ? r.recommendations : [],
  };
}

export default function ReportPage() {
  const { report, resetInterview } = useInterview();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const reportIdParam = searchParams.get('id');
  const sessionIdParam = searchParams.get('session_id');

  const [loadedReport, setLoadedReport] = useState(null);
  const [loading, setLoading] = useState(Boolean(reportIdParam || sessionIdParam));
  const [error, setError] = useState(null);
  const [expandedQuestion, setExpandedQuestion] = useState(null);

  useEffect(() => {
    const lookupId = reportIdParam || sessionIdParam;
    if (!lookupId) {
      setLoading(false);
      return;
    }

    let mounted = true;
    setLoading(true);
    setError(null);

    fetchReportById(lookupId)
      .then((res) => {
        if (mounted && res?.report) {
          setLoadedReport(normalizeReportData(res.report));
        } else if (mounted) {
          setError('Interview report not found.');
        }
      })
      .catch((err) => {
        if (mounted) {
          console.warn('[ReportPage] Could not fetch report:', err);
          setError('Report not found or access denied.');
        }
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [reportIdParam, sessionIdParam]);

  const handlePracticeAgain = () => {
    resetInterview();
    navigate('/interview/setup');
  };

  const rawData = loadedReport || (report ? normalizeReportData(report) : null);

  if (loading) {
    return (
      <div className="content-area flex flex-col items-center justify-center min-h-[60vh] animate-fade-in">
        <Loader2 className="w-10 h-10 text-primary animate-spin mb-4" />
        <p className="text-secondary font-medium">Loading interview performance report...</p>
      </div>
    );
  }

  if (error || !rawData) {
    return (
      <div className="content-area max-w-xl mx-auto text-center py-16 animate-fade-in">
        <div className="w-14 h-14 rounded-lg bg-surface border border-line flex items-center justify-center mx-auto mb-4 text-secondary">
          <FileText className="w-7 h-7" />
        </div>
        <h2 className="text-xl font-semibold text-heading mb-2">
          {error ? 'Report Unavailable' : 'No Report Available'}
        </h2>
        <p className="text-secondary text-sm mb-6">
          {error || 'Complete an interview or choose one from your interview history to view the full performance evaluation.'}
        </p>
        <div className="flex flex-col sm:flex-row gap-3 justify-center">
          <Button variant="secondary" icon={RotateCcw} onClick={handlePracticeAgain}>
            Start New Interview
          </Button>
          <Button icon={LayoutDashboard} onClick={() => navigate('/dashboard')}>
            Go to Dashboard
          </Button>
        </div>
      </div>
    );
  }

  const data = rawData;
  const legacyRubric = ![CONCEPTUAL_RUBRIC, MIXED_RUBRICS].includes(data.rubricVersion);

  const dimensionItems = [
    {
      label: 'Technical Accuracy',
      score: data.dimensions?.technical_accuracy ?? null,
      color: 'bg-primary',
      textColor: 'text-primary',
      icon: Brain,
      description: 'Correctness and coverage of the essential concepts, or sound judgment in behavioral responses.',
    },
    {
      label: 'Relevance',
      score: data.dimensions?.relevance ?? null,
      color: 'bg-cyan-700',
      textColor: 'text-cyan-800',
      icon: Target,
      description: 'Direct alignment with prompt requirements and role expectations.',
    },
    ...(legacyRubric ? [{
      label: 'Depth',
      score: data.dimensions?.depth ?? null,
      color: 'bg-violet-700',
      textColor: 'text-violet-800',
      icon: Layers,
      description: 'Understanding of internal trade-offs, architecture, and edge cases.',
    }] : []),
    {
      label: 'Clarity',
      score: data.dimensions?.clarity ?? null,
      color: 'bg-emerald-700',
      textColor: 'text-success',
      icon: MessageSquare,
      description: 'How clearly the answer communicates its meaning.',
    },
  ];

  return (
    <div className="print-report content-area animate-fade-in pb-16">
      <div className="max-w-4xl mx-auto">
        {/* Header & Metadata */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full bg-selected border border-primary text-primary text-sm font-semibold mb-4 ">
            <Award className="w-4 h-4 text-primary" />
            {data.hasEvaluations ? 'Performance Evaluation Complete' : 'Interview Report'}
          </div>
          <h1 className="text-2xl sm:text-3xl font-semibold text-heading mb-2 tracking-tight">
            Interview Performance Report
          </h1>
          <div className="flex flex-wrap items-center justify-center gap-3 sm:gap-6 text-sm text-secondary mt-3">
            <span className="flex items-center gap-1.5"><Briefcase className="w-4 h-4 text-secondary" />{data.role}</span>
            <span className="flex items-center gap-1.5"><Calendar className="w-4 h-4 text-secondary" />{data.date}</span>
            <span className="flex items-center gap-1.5"><Clock className="w-4 h-4 text-secondary" />{data.duration}</span>
            <span className="flex items-center gap-1.5"><FileText className="w-4 h-4 text-secondary" />{data.questionsAnswered} of {data.totalQuestions} answered</span>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-surface text-secondary border border-line">
              {data.subject ? `${data.subject} · ` : ''}{data.difficulty}
            </span>
            <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-surface text-secondary border border-line">
              {data.interviewType}
            </span>
          </div>
        </div>

        {/* Overall Score & Grade Card */}
        <Card className="flex flex-col items-center py-8 px-6 mb-8 border-line relative overflow-hidden   ">
          <div className="flex items-center justify-between w-full max-w-sm mb-4">
            <span className="text-xs uppercase  text-secondary font-semibold">Final Assessment</span>
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-secondary">Grade:</span>
              <span className={`px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                data.grade.startsWith('A')
                  ? 'bg-success-surface text-success border border-emerald-300'
                  : data.grade === 'B'
                  ? 'bg-selected text-primary border border-primary'
                  : data.grade === 'C'
                  ? 'bg-warning-surface text-warning border border-amber-300'
                  : 'bg-danger-surface text-danger border border-red-300'
              }`}>
                {data.grade}
              </span>
            </div>
          </div>

          {data.hasEvaluations ? <ScoreCard score={data.overallScore} size="lg" /> : <p className="text-secondary">No valid evaluation scores are available.</p>}

          <h3 className={`text-xl font-semibold mt-4 ${
            data.overallScore >= 80 ? 'text-success' : data.overallScore >= 60 ? 'text-warning' : 'text-danger'
          }`}>
            {data.gradeLabel}
          </h3>
          <p className="text-secondary text-sm mt-1 text-center max-w-md">
            {!data.hasEvaluations ? 'Your recorded responses are shown below. No performance assessment is available.' : data.overallScore >= 80
              ? 'Excellent performance demonstrating strong conceptual mastery, sound communication, and robust problem solving.'
              : data.overallScore >= 60
              ? 'Solid foundations with opportunities to strengthen the concepts identified below.'
              : 'Core fundamentals need focused preparation. Review the topic breakdown and targeted recommendations below.'}
          </p>
          {data.hasEvaluations && <p className="text-secondary text-xs mt-3 text-center max-w-lg">
            Each evaluated question, including follow-ups, contributes equally to the overall score. Skipped answers count as zero; unavailable evaluations are excluded.
          </p>}
          {data.hasEvaluations && !legacyRubric && <p className="text-secondary text-xs mt-2 text-center max-w-lg">
            {data.rubricVersion === MIXED_RUBRICS ? 'This report combines originally saved scores from two rubrics. ' : ''}
            New answers are weighted 60% Technical Accuracy, 30% Relevance and 10% Clarity.
          </p>}
        </Card>

        {/* Performance Dimensions Grid */}
        <div className="mb-8">
          <h2 className="text-sm font-semibold uppercase  text-secondary mb-3 flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-primary" />
            Performance Dimensions
          </h2>
          <div className={"grid grid-cols-2 gap-4 " + (legacyRubric ? 'lg:grid-cols-4' : 'lg:grid-cols-3')}>
            {dimensionItems.map((item, i) => (
              <Card key={i} className="p-4 border-line hover:border-line transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <item.icon className={`w-5 h-5 ${item.textColor}`} />
                  <span className="text-xs tabular-nums font-semibold text-secondary">{dimensionMark(item.score)}</span>
                </div>
                <p className="text-sm font-semibold text-heading mb-0.5">{item.label}</p>
                <div className="h-1.5 bg-subtle rounded-full overflow-hidden my-2">
                  <div
                    className={`h-full rounded-full  ${item.color} transition-all duration-700`}
                    style={{ width: Number.isFinite(item.score) ? `${item.score}%` : 0 }}
                  />
                </div>
                <p className="text-sm text-secondary leading-relaxed">{item.description}</p>
              </Card>
            ))}
          </div>
        </div>

        {/* Strong Areas & Areas to Improve */}
        <div className="grid md:grid-cols-2 gap-6 mb-8">
          <ReportSection title="Strong Areas" icon={CheckCircle} defaultOpen={true}>
            <div className="space-y-2.5">
              {(data.strengths || []).length > 0 ? (
                data.strengths.map((str, idx) => (
                  <div key={idx} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-success-surface border border-emerald-300">
                    <Check className="w-4 h-4 text-success flex-shrink-0 mt-0.5" />
                    <span className="text-sm text-heading">{str}</span>
                  </div>
                ))
              ) : (
                <p className="text-sm text-secondary italic">No specific strengths captured.</p>
              )}
            </div>
          </ReportSection>

          <ReportSection title="Areas to Improve" icon={AlertTriangle} defaultOpen={true}>
            <div className="space-y-2.5">
              {(data.skillGaps || []).length > 0 ? (
                data.skillGaps.map((gap, idx) => (
                  <div key={idx} className="flex items-start gap-2.5 p-2.5 rounded-lg bg-danger-surface border border-red-300">
                    <AlertTriangle className="w-4 h-4 text-danger flex-shrink-0 mt-0.5" />
                    <span className="text-sm text-heading">{gap}</span>
                  </div>
                ))
              ) : (
                <p className="text-sm text-secondary italic">No critical skill gaps identified.</p>
              )}
            </div>
          </ReportSection>
        </div>

        {/* Skill / Topic Performance (Assessed topics only) */}
        {(data.skillAnalysis || []).length > 0 && (
          <ReportSection title="Assessed Skill & Topic Performance" icon={TrendingUp} className="mb-8" defaultOpen={true}>
            <div className="space-y-3">
              {data.skillAnalysis.map((topicItem, idx) => (
                <div
                  key={idx}
                  className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 rounded-lg bg-subtle border border-line gap-3"
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-heading">{topicItem.topic}</span>
                      <span className="text-xs text-secondary">({topicItem.question_count} question{topicItem.question_count > 1 ? 's' : ''})</span>
                    </div>
                    <div className="h-1.5 bg-subtle rounded-full overflow-hidden mt-2 max-w-md">
                      <div
                        className={`h-full rounded-full transition-all duration-700 ${
                          topicItem.average_score >= 80
                            ? 'bg-emerald-600'
                            : topicItem.average_score >= 65
                            ? 'bg-primary'
                            : topicItem.average_score >= 50
                            ? 'bg-amber-600'
                            : 'bg-red-600'
                        }`}
                        style={{ width: `${topicItem.average_score}%` }}
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <span className="text-sm tabular-nums font-semibold text-heading w-12 text-right">
                      {topicItem.average_score}%
                    </span>
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                      topicItem.proficiency === 'Strong'
                        ? 'bg-success-surface text-success border border-emerald-300'
                        : topicItem.proficiency === 'Proficient'
                        ? 'bg-selected text-primary border border-primary'
                        : 'bg-warning-surface text-warning border border-amber-300'
                    }`}>
                      {topicItem.proficiency}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </ReportSection>
        )}

        {/* Adaptive Interview Progression Summary */}
        {data.adaptiveSummary && (
          <ReportSection title="Adaptive Interview Summary" icon={Zap} className="mb-8" defaultOpen={true}>
            <div className="p-4 rounded-lg bg-selected border border-primary space-y-3">
              <div className="flex flex-wrap items-center gap-4 text-xs font-medium">
                <span className="px-2.5 py-1 rounded-md bg-selected text-primary border border-primary">
                  {data.adaptiveSummary.adaptability_rating || 'Adaptive Assessment'}
                </span>
                <span className="text-secondary">
                  Follow-Up Questions: <strong className="text-heading">{data.adaptiveSummary.total_follow_ups}</strong>
                </span>
                <span className="text-secondary">
                  Difficulty: <strong className="text-heading">{data.adaptiveSummary.difficulty_progression}</strong>
                </span>
              </div>
              <p className="text-sm text-secondary leading-relaxed">
                {data.adaptiveSummary.summary_text}
              </p>
            </div>
          </ReportSection>
        )}

        {/* Question-by-Question Breakdown */}
        <ReportSection title="Question-by-Question Breakdown" icon={FileText} className="mb-8" defaultOpen={true}>
          <div className="space-y-4">
            {(data.questionAnalysis || []).length > 0 ? (
              data.questionAnalysis.map((q, idx) => {
                const isExpanded = expandedQuestion === idx;
                const available = q.skipped || evaluationAvailable(q);
                const qScore = available ? q.score ?? 0 : null;
                const reference = referenceAnswer(q);
                const conceptual = q.rubric_version === CONCEPTUAL_RUBRIC || data.rubricVersion === CONCEPTUAL_RUBRIC;
                const optionalSuggestions = conceptual && q.answer_status === 'CORRECT';
                const statusBadge = !available ? { bg: 'bg-warning-surface text-warning', label: 'Evaluation unavailable' } : q.skipped
                  ? { label: 'Skipped', bg: 'bg-surface text-secondary' }
                  : (conceptual ? q.answer_status === 'CORRECT' : qScore >= 75)
                  ? { label: conceptual ? 'Correct' : 'Strong', bg: 'bg-success-surface text-success border border-emerald-300' }
                  : (conceptual ? q.answer_status === 'PARTIAL' : qScore >= 50)
                  ? { label: 'Partial', bg: 'bg-warning-surface text-warning border border-amber-300' }
                  : { label: 'Needs Practice', bg: 'bg-danger-surface text-danger border border-red-300' };

                return (
                  <div
                    key={idx}
                    className="report-question rounded-lg border border-line bg-surface overflow-hidden transition-colors hover:border-line"
                  >
                    {/* Header bar */}
                    <button
                      aria-expanded={isExpanded}
                      onClick={() => setExpandedQuestion(isExpanded ? null : idx)}
                      className="w-full flex items-center justify-between p-4 text-left hover:bg-subtle transition-colors"
                    >
                      <div className="flex items-center gap-3 flex-1 min-w-0 pr-3">
                        <span className="w-7 h-7 rounded-lg bg-surface flex items-center justify-center text-xs font-semibold text-secondary flex-shrink-0">
                          {q.question_order || q.questionOrder || idx + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-semibold text-heading break-words">
                            {q.question || `Question ${idx + 1}`}
                          </p>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="text-xs text-secondary">{q.topic || 'General'}</span>
                            <span className="text-secondary">•</span>
                            <span className="text-xs text-secondary">{q.difficulty || 'Medium'}</span>
                            {Boolean(q.is_follow_up || q.isFollowUp) && (
                              <span className="px-1.5 py-0.5 rounded text-xs font-semibold bg-selected text-primary border border-primary">
                                Follow-Up
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="flex items-center gap-3">
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusBadge.bg}`}>
                          {statusBadge.label}
                        </span>
                        <span className="text-sm tabular-nums font-semibold text-heading w-10 text-right">
                          {available ? `${qScore}%` : '—'}
                        </span>
                        {isExpanded ? (
                          <ChevronUp className="w-4 h-4 text-secondary" />
                        ) : (
                          <ChevronDown className="w-4 h-4 text-secondary" />
                        )}
                      </div>
                    </button>

                    {/* Expandable details */}
                    {isExpanded && (
                      <div className="px-4 pb-4 pt-2 border-t border-line space-y-3.5 animate-fade-in text-sm">
                        {/* Question Text Full */}
                        <div>
                          <span className="text-xs font-semibold text-secondary uppercase ">Prompt</span>
                          <p className="text-heading font-medium mt-0.5">{q.question}</p>
                        </div>

                        {/* Candidate Answer */}
                        <div>
                          <span className="text-xs font-semibold text-secondary uppercase ">Your Response</span>
                          <div className="mt-1 p-3 rounded-lg bg-surface border border-line text-secondary tabular-nums text-xs leading-relaxed whitespace-pre-wrap">
                            {q.candidate_answer || q.candidateAnswer || (q.skipped ? '<Question was skipped>' : '<No answer recorded>')}
                          </div>
                        </div>

                        {!available && <p role="status" className="text-warning">Evaluation unavailable. This response has no valid evaluation score.</p>}
                        {/* Dimensions Breakdown for this question */}
                        {!q.skipped && available && (
                          <div>
                            <span className="text-xs font-semibold text-secondary uppercase  mb-1 block">Dimension Marks</span>
                            <div className={"grid grid-cols-2 gap-2 " + (conceptual ? 'sm:grid-cols-3' : 'sm:grid-cols-4')}>
                              <div className="p-2 rounded bg-subtle border border-line text-center">
                                <span className="text-xs text-secondary block">{conceptual ? 'Technical Accuracy' : 'Technical'}</span>
                                <span className="tabular-nums font-semibold text-xs text-primary">
                                  {dimensionMark(q.technical_accuracy ?? q.technicalAccuracy)}
                                </span>
                              </div>
                              <div className="p-2 rounded bg-subtle border border-line text-center">
                                <span className="text-xs text-secondary block">Relevance</span>
                                <span className="tabular-nums font-semibold text-xs text-cyan-800">
                                  {dimensionMark(q.relevance)}
                                </span>
                              </div>
                              {!conceptual && <div className="p-2 rounded bg-subtle border border-line text-center">
                                <span className="text-xs text-secondary block">Depth</span>
                                <span className="tabular-nums font-semibold text-xs text-violet-800">
                                  {dimensionMark(q.depth)}
                                </span>
                              </div>}
                              <div className="p-2 rounded bg-subtle border border-line text-center">
                                <span className="text-xs text-secondary block">Clarity</span>
                                <span className="tabular-nums font-semibold text-xs text-success">
                                  {dimensionMark(q.clarity)}
                                </span>
                              </div>
                            </div>
                          </div>
                        )}

                        {/* Question-level strengths & improvements */}
                        {available && Array.isArray(q.strengths) && q.strengths.length > 0 && (
                          <div className="p-2.5 rounded bg-success-surface border border-emerald-300">
                            <span className="text-xs font-semibold text-success block mb-1">Key Strengths:</span>
                            <ul className="list-disc list-inside text-xs text-secondary space-y-0.5">
                              {q.strengths.map((s, si) => <li key={si}>{s}</li>)}
                            </ul>
                          </div>
                        )}

                        {available && Array.isArray(q.improvements) && q.improvements.length > 0 && (
                          <div className={"p-2.5 rounded border " + (optionalSuggestions ? 'bg-selected border-primary' : 'bg-danger-surface border-red-300')}>
                            <span className={"text-xs font-semibold block mb-1 " + (optionalSuggestions ? 'text-primary' : 'text-danger')}>
                              {optionalSuggestions ? OPTIONAL_SUGGESTIONS_HEADING : 'Areas to Improve'}
                            </span>
                            <ul className="list-disc list-inside text-xs text-secondary space-y-0.5">
                              {q.improvements.map((imp, ii) => <li key={ii}>{optionalSuggestions ? suggestionText(imp) : imp}</li>)}
                            </ul>
                          </div>
                        )}

                        {( 
                          <div className="p-2.5 rounded bg-selected border border-primary">
                            <span className="text-xs font-semibold text-primary block mb-1">Model Answer Reference:</span>
                            <p className="text-xs text-secondary mb-2">Illustrative reference, not a required script. Use your own real experience; valid alternative answers receive credit.</p>
                            <p className="text-xs text-secondary leading-relaxed">
                              {reference || 'A model answer is unavailable for this question.'}
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })
            ) : (
              <p className="text-sm text-secondary italic">No question-level breakdown available.</p>
            )}
          </div>
        </ReportSection>

        {/* Actionable Recommendations */}
        <ReportSection title="Preparation & Study Recommendations" icon={Lightbulb} className="mb-8" defaultOpen={true}>
          <div className="space-y-3">
            {(data.recommendations || []).length > 0 ? (
              data.recommendations.map((rec, i) => (
                <div key={i} className="flex items-start gap-3 p-3.5 rounded-lg bg-selected border border-primary">
                  <div className="w-6 h-6 rounded-full bg-selected flex items-center justify-center flex-shrink-0 text-primary font-semibold text-xs">
                    {i + 1}
                  </div>
                  <p className="text-sm text-heading leading-relaxed">{rec}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-secondary italic">No specific recommendations generated.</p>
            )}
          </div>
        </ReportSection>

        {/* Action Buttons */}
        <div className="flex flex-col sm:flex-row gap-4 justify-center pt-4">
          <Button variant="secondary" icon={RotateCcw} onClick={handlePracticeAgain}>
            Practice Again
          </Button>
          <Button variant="secondary" icon={FileText} onClick={() => navigate('/history')}>
            View Interview History
          </Button>
          <Button icon={LayoutDashboard} onClick={() => navigate('/dashboard')}>
            Go to Dashboard
          </Button>
        </div>
      </div>
    </div>
  );
}
