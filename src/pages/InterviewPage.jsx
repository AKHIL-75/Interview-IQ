import { useState, useEffect, useMemo, useCallback, useRef, lazy, Suspense } from 'react';
import { useNavigate } from 'react-router-dom';
import { Brain, Clock, Sparkles, ArrowRight, Camera, CameraOff, Mic, MicOff } from 'lucide-react';
import { useInterview } from '../context/InterviewContext';
import { useToast } from '../context/ToastContext';
import QuestionCard from '../components/QuestionCard';
import AnswerBox from '../components/AnswerBox';
import CameraPreview from '../components/CameraPreview';
import InterviewProgress from '../components/InterviewProgress';
import Card from '../components/Card';
import InterviewLobby from '../components/InterviewLobby';
const ImmersiveInterviewStage = lazy(() => import('../components/ImmersiveInterviewStage'));
import { interviewTopics } from '../data/mockQuestions';
import { timingEvent } from '../services/performance.js';

export default function InterviewPage() {
  const {
    session,
    questions,
    currentQuestionIndex,
    currentQuestion,
    answers,
    currentQuestionStartedAt,
    evaluation,
    adaptiveDecision,
    submissionStage,
    interviewPlan,
    interviewState,
    conversationalLeadIn,
    isInterviewEnded,
    setup,
    progressPercentage,
    submitAnswer,
    skipQuestion,
    nextQuestion,
    handleTimeout,
    generateReport, saveDraft,
  } = useInterview();

  // Camera state for Camera mode
  const [cameraEnabled, setCameraEnabled] = useState(setup.mode === 'Camera');
  const [cameraPermission, setCameraPermission] = useState('unknown');

  const { success, info, error } = useToast();
  const navigate = useNavigate();

  const [submitting, setSubmitting] = useState(false);
  const [skipping, setSkipping] = useState(false);

  // Check if current question already has an answer saved
  const currentAnswerRecord = useMemo(() => {
    if (!currentQuestion) return null;
    return answers.find(a => a.questionId === currentQuestion.id) || null;
  }, [answers, currentQuestion]);

  const [conversationalResponse, setConversationalResponse] = useState('');
  const [showInterviewerResponse, setShowInterviewerResponse] = useState(false);

  // Reset conversational response when question changes
  useEffect(() => {
    setShowInterviewerResponse(false);
    setConversationalResponse('');
    if (currentQuestion?.id) timingEvent('text.question_rendered');
  }, [currentQuestion?.id]);

  // Strict Invariant: Transition state is ONLY valid after current question is evaluated
  const hasCurrentAnswer = Boolean(
    currentAnswerRecord &&
    (currentAnswerRecord.answer || currentAnswerRecord.skipped) &&
    currentAnswerRecord.evaluation
  );

  const isTransitionActive = Boolean(
    hasCurrentAnswer &&
    (showInterviewerResponse || currentAnswerRecord?.adaptiveComplete) &&
    !submitting &&
    !skipping
  );

  // Timestamp-based timer: accurately reconstructs elapsed seconds upon mount/refresh
  const [timer, setTimer] = useState(() => {
    if (!currentQuestionStartedAt) return 0;
    return Math.max(0, Math.floor((Date.now() - currentQuestionStartedAt) / 1000));
  });

  useEffect(() => {
    const updateTimer = () => {
      if (!currentQuestionStartedAt) return;
      const elapsed = Math.max(0, Math.floor((Date.now() - currentQuestionStartedAt) / 1000));
      setTimer(elapsed);


    };

    updateTimer();
    const interval = setInterval(updateTimer, 1000);
    return () => clearInterval(interval);
  }, [currentQuestionStartedAt, submitting, skipping]);

  const [aiMessages, setAiMessages] = useState([
    { text: 'Welcome! I\'ll be your AI interviewer today. Take your time with each question.', type: 'info' }
  ]);

  // Dynamic topics from interviewPlan roadmap or fallback to questions
  const topics = useMemo(() => {
    if (interviewPlan?.planned_sequence && interviewPlan.planned_sequence.length > 0) {
      const uniquePlanTopics = Array.from(new Set(interviewPlan.planned_sequence.map(p => p.topic || p.stage)));
      return uniquePlanTopics.map((topicName) => {
        const isCompleted = questions.some(q => (q.topic === topicName || q.stage === topicName) && answers.some(a => a.questionId === q.id));
        const isCurrent = currentQuestion && (currentQuestion.topic === topicName || currentQuestion.stage === topicName);
        return {
          name: topicName,
          status: isCurrent ? 'current' : isCompleted ? 'completed' : 'pending',
        };
      });
    }

    if (!questions || questions.length === 0) return interviewTopics;

    const uniqueTopics = Array.from(new Set(questions.map(q => q.topic || 'General')));
    return uniqueTopics.map((topicName) => {
      const qWithTopic = questions.filter(q => (q.topic || 'General') === topicName);
      const isCompleted = qWithTopic.every(q => answers.some(a => a.questionId === q.id));
      const isCurrent = currentQuestion && (currentQuestion.topic || 'General') === topicName;

      return {
        name: topicName,
        status: isCurrent ? 'current' : isCompleted ? 'completed' : 'pending',
      };
    });
  }, [interviewPlan, questions, answers, currentQuestion]);

  // Session guard: only redirect to setup if no questions are loaded
  useEffect(() => {
    if (!questions || questions.length === 0) {
      navigate('/interview/setup');
    }
  }, [questions, navigate]);

  const formatTimer = (s) => {
    const m = Math.floor(s / 60).toString().padStart(2, '0');
    const sec = (s % 60).toString().padStart(2, '0');
    return `${m}:${sec}`;
  };

  const isDynamic = setup.interviewMode === 'DYNAMIC';

  const handleSubmit = async (answer, answerSource) => {
    if (submitting || skipping) return;
    timingEvent('text.submit_clicked');
    setSubmitting(true);
    setShowInterviewerResponse(false);

    try {
      const result = await submitAnswer(answer, answerSource);

      // Build natural conversational interviewer reaction
      let leadIn = result?.lead_in || conversationalLeadIn;
      if (!leadIn) {
        if (result?.end_interview || isInterviewEnded) {
          leadIn = "Thank you for answering thoroughly. That covers all target competencies for today.";
        } else {
          leadIn = "Thank you for your response. Let's move to the next area.";
        }
      }

      setConversationalResponse(leadIn);
      setShowInterviewerResponse(true);

      // Add to AI Interviewer chat transcript
      setAiMessages(prev => [
        ...prev,
        { text: leadIn, type: 'interviewer' }
      ]);
    } catch (err) {
      error(err.message || 'Submission failed. Your answer is preserved; retry.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleSkip = () => handleSubmit("I don't know");

  const handleNext = () => {
    setShowInterviewerResponse(false);
    setConversationalResponse('');
    const hasMore = nextQuestion();
    if (!hasMore || isInterviewEnded) {
      handleFinish().catch(() => {});
    } else {
      setAiMessages(prev => [
        ...prev,
        { text: 'Next question ready. Best of luck!', type: 'info' }
      ]);
    }
  };

  const finishingRef = useRef(false);
  const handleFinish = async () => {
    if (finishingRef.current) return;
    finishingRef.current = true;
    try {
      const rep = await generateReport();
      success('Interview completed and report saved.');
      navigate(`/report?session_id=${encodeURIComponent(session?.sessionId || rep.session_id)}`);
    } catch (err) {
      error(err.message || 'Unable to save your report. Please retry.');
      throw err;
    } finally { finishingRef.current = false; }
  };
  const isImmersiveMode = setup.mode === 'Voice' || setup.mode === 'Camera';
  const isResumedSession = Boolean(answers.length > 0 || currentQuestionIndex > 0);
  const [hasJoinedLobby, setHasJoinedLobby] = useState(() => !isImmersiveMode || isResumedSession);

  if (!currentQuestion) {
    return (
      <div className="content-area flex items-center justify-center min-h-[60vh]">
        <p className="text-secondary">Loading interview...</p>
      </div>
    );
  }

  if (isImmersiveMode) {
    if (!hasJoinedLobby) {
      return (
        <InterviewLobby
          role={setup.subject ? `${setup.subject} · ${setup.role || 'Software Engineer'}` : (setup.role || 'Software Engineer')}
          interviewType={setup.interviewType || 'Technical'}
          difficulty={currentQuestion?.difficulty || setup.difficulty || 'Medium'}
          mode={setup.mode}
          onJoinInterview={() => setHasJoinedLobby(true)}
        />
      );
    }

    return (
      <Suspense fallback={<div className="min-h-screen bg-page text-heading p-8" role="status">Loading interview...</div>}><ImmersiveInterviewStage
        session={session}
        saveDraft={saveDraft}
        submissionStage={submissionStage}
        questions={questions}
        currentQuestionIndex={currentQuestionIndex}
        currentQuestion={currentQuestion}
        answers={answers}
        currentQuestionStartedAt={currentQuestionStartedAt}
        isInterviewEnded={isInterviewEnded}
        setup={setup}
        submitAnswer={submitAnswer}
        skipQuestion={skipQuestion}
        nextQuestion={nextQuestion}
        handleFinish={handleFinish}
        isResumed={isResumedSession}
      /></Suspense>
    );
  }

  const isLastQuestion = (!isDynamic && currentQuestionIndex >= (setup.questionCount || 10) - 1) || isInterviewEnded;

  return (
    <div className="text-interview min-h-screen bg-page">
      {/* Top bar */}
      <div className="border-b border-line bg-surface  px-4 py-3">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center  ">
              <Brain className="w-4 h-4 text-white" />
            </div>
            <div>
              <span className="text-sm font-medium text-heading">Mock Interview</span>
              <span className="text-xs text-secondary ml-2">— {setup.subject ? `${setup.subject} · ` : ''}{setup.role}</span>
              <span className="text-xs tabular-nums px-2 py-0.5 rounded ml-2 bg-subtle text-primary">
                {isDynamic ? 'Dynamic Mode' : `Static (${setup.questionCount || 10} Qs)`}
              </span>
              {(setup.mode === 'Voice' || setup.mode === 'Camera') && (
                <span className="text-xs tabular-nums px-2 py-0.5 rounded ml-1 bg-success-surface text-success border border-emerald-300">
                  {setup.mode === 'Camera' ? '📹 Camera' : '🎤 Voice'}
                </span>
              )}
            </div>
          </div>
          <div className="flex items-center gap-4">
            {/* Camera toggle for Camera mode */}
            {setup.mode === 'Camera' && (
              <button
                onClick={() => setCameraEnabled(!cameraEnabled)}
                className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
                  cameraEnabled
                    ? 'bg-success-surface border border-emerald-300 text-success hover:bg-emerald-50'
                    : 'bg-subtle border border-line text-secondary hover:text-secondary'
                }`}
                title={cameraEnabled ? 'Turn off camera' : 'Turn on camera'}
              >
                {cameraEnabled ? <Camera className="w-3.5 h-3.5" /> : <CameraOff className="w-3.5 h-3.5" />}
                {cameraEnabled ? 'Cam On' : 'Cam Off'}
              </button>
            )}
            <div className="flex items-center gap-2 text-secondary">
              <Clock className="w-4 h-4" />
              <span className="text-sm tabular-nums">{formatTimer(timer)}</span>
            </div>
            <button
              onClick={() => handleFinish().catch(() => {})}
              className="min-h-11 rounded-md px-3 text-sm text-danger hover:bg-danger-surface transition-colors"
            >
              End Interview
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto p-4 md:p-6">
        <div className="grid lg:grid-cols-[220px_minmax(0,1fr)_250px] xl:grid-cols-[240px_minmax(0,1fr)_280px] gap-6">
          {/* Left — Progress */}
          <div className="hidden lg:block">
            <Card>
              <InterviewProgress
                topics={topics}
                currentIndex={currentQuestionIndex}
                totalQuestions={isDynamic ? 0 : (setup.questionCount || 10)}
                answeredCount={answers.length}
                isDynamic={isDynamic}
              />
            </Card>
          </div>

          {/* Center — Question & Answer */}
          <div className="space-y-6">
            {/* Mobile progress */}
            <div className="lg:hidden">
              <div className="flex justify-between items-center mb-2">
                <span className="text-sm text-secondary">
                  {isDynamic ? `Question ${currentQuestionIndex + 1} (Dynamic)` : `Question ${currentQuestionIndex + 1} of ${setup.questionCount || 10}`}
                </span>
                <span className="text-sm text-secondary tabular-nums">{progressPercentage}%</span>
              </div>
              <div className="h-1.5 bg-subtle rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-500"
                  style={{ width: `${progressPercentage}%` }}
                />
              </div>
            </div>

            {/* Camera Preview for Camera mode */}
            {setup.mode === 'Camera' && (
              <CameraPreview
                enabled={cameraEnabled}
                onPermissionChange={setCameraPermission}
              />
            )}

            <Card>
              <QuestionCard
                question={currentQuestion.question}
                number={currentQuestionIndex + 1}
                total={isDynamic ? 0 : (setup.questionCount || 10)}
                difficulty={currentQuestion.difficulty}
                topic={currentQuestion.topic}
                focus={currentQuestion.focus}
                stage={currentQuestion.stage}
                isDynamic={isDynamic}
              />
            </Card>

            {/* Show conversational response or answer box */}
            {isTransitionActive ? (
              <Card className="animate-fade-in-up border border-primary bg-surface ">
                <div className="flex items-center gap-3 mb-4">
                  <div className="w-8 h-8 rounded-lg bg-selected border border-primary flex items-center justify-center">
                    <Brain className="w-4 h-4 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-base font-semibold text-heading">Interviewer Response</h3>
                    <p className="text-xs text-secondary">Listening and adapting dynamically</p>
                  </div>
                </div>

                <div className="p-5 rounded-lg bg-selected border border-primary mb-6">
                  <p className="text-base md:text-lg text-heading italic leading-relaxed">
                    "{conversationalResponse || 'Your answer is saved. Continue your interview.'}"
                  </p>
                </div>

                <div className="flex gap-3">
                  {isLastQuestion ? (
                    <button
                      onClick={() => handleFinish().catch(() => {})}
                      className="btn-primary w-full flex items-center justify-center gap-2 py-3"
                    >
                      Complete Interview & View Report <ArrowRight className="w-4 h-4" />
                    </button>
                  ) : (
                    <button
                      onClick={handleNext}
                      className="btn-primary w-full flex items-center justify-center gap-2 py-3"
                    >
                      Proceed to Next Question <ArrowRight className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </Card>
            ) : (
              <AnswerBox
                key={currentQuestion.id}
                onSubmit={handleSubmit}
                onDraftChange={text => saveDraft(currentQuestion.id, text)}
                readOnly={Boolean(currentAnswerRecord?.evaluation)}
                onSkip={() => handleSkip(false)}
                mode={setup.mode}
                loading={submitting || skipping}
                submissionStage={submissionStage}
                initialAnswer={currentAnswerRecord?.answer || (session?.draft?.questionId === currentQuestion.id ? session.draft.text : '')}
              />
            )}
          </div>

          {/* Right — AI Panel */}
          <div className="hidden lg:block">
            <Card>
              <div className="flex items-center gap-2 mb-4">
                <Brain className="w-5 h-5 text-primary" />
                <h3 className="text-sm font-semibold text-heading">AI Interviewer</h3>
              </div>
              <div className="space-y-3 max-h-[60vh] overflow-y-auto">
                {aiMessages.map((msg, i) => (
                  <div key={i} className={`text-sm p-3 rounded-lg ${
                    msg.type === 'interviewer'
                      ? 'bg-selected border border-primary text-primary italic'
                      : msg.type === 'positive'
                        ? 'bg-success-surface border border-emerald-300 text-success'
                        : msg.type === 'suggestion'
                          ? 'bg-warning-surface border border-amber-300 text-warning'
                          : 'bg-subtle text-secondary'
                  }`}>
                    {msg.text}
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
