import { createContext, useContext, useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useAuth } from './AuthContext';
import { createSubmissionPipeline } from '../services/submissionPipeline';
import {
  parseResume as parseResumeApi,
  parseJobDescription as parseJobDescriptionApi,
  analyzeResumeJobMatch as analyzeResumeJobMatchApi,
  generateInterviewQuestions as generateInterviewQuestionsApi,
  evaluateCandidateAnswer as evaluateCandidateAnswerApi,
  getAdaptiveNextQuestion as getAdaptiveNextQuestionApi,
  startAdaptiveInterview as startAdaptiveInterviewApi,
  persistInterviewReport as persistInterviewReportApi,
} from '../services/api';

const InterviewContext = createContext(null);

export const ACTIVE_SESSION_KEY = 'interviewiq_active_session';

const initialSetup = {
  inferenceEngine: import.meta.env?.VITE_DEFAULT_INFERENCE_ENGINE === 'aws' ? 'aws' : 'local',
  resume: null,
  jobDescription: '',
  candidateProfile: null,
  jobProfile: null,
  analysis: null,
  interviewType: 'Technical',
  subject: null,
  difficulty: 'Medium',
  interviewMode: 'STATIC',
  questionCount: 10,
  mode: 'Text',
  role: 'Software Engineer',
};

/**
 * Safely loads and validates the active session from localStorage.
 * Removes corrupted or invalid entries without crashing.
 */
function loadActiveSession() {
  try {
    const stored = localStorage.getItem(ACTIVE_SESSION_KEY);
    if (!stored) return null;

    const parsed = JSON.parse(stored);
    if (!parsed || typeof parsed !== 'object') {
      localStorage.removeItem(ACTIVE_SESSION_KEY);
      return null;
    }

    // Must have a session ID, valid questions array, and active status
    if (
      !parsed.sessionId ||
      !Array.isArray(parsed.questions) ||
      parsed.questions.length === 0 ||
      parsed.status !== 'active'
    ) {
      localStorage.removeItem(ACTIVE_SESSION_KEY);
      return null;
    }

    const totalQ = parsed.questions.length;
    let idx = typeof parsed.currentQuestionIndex === 'number' ? parsed.currentQuestionIndex : 0;
    if (idx < 0) idx = 0;
    if (idx >= totalQ) idx = totalQ - 1;
    parsed.currentQuestionIndex = idx;

    if (!Array.isArray(parsed.answers)) parsed.answers = [];
    if (!Array.isArray(parsed.skippedQuestions)) parsed.skippedQuestions = [];
    if (!parsed.currentQuestionStartedAt) parsed.currentQuestionStartedAt = Date.now();
    if (typeof parsed.consecutiveFollowUps !== 'number') parsed.consecutiveFollowUps = 0;
    if (!parsed.adaptiveDecision) parsed.adaptiveDecision = null;
    if (!parsed.interviewPlan) parsed.interviewPlan = null;
    if (!parsed.interviewState) parsed.interviewState = null;
    if (typeof parsed.conversationalLeadIn !== 'string') parsed.conversationalLeadIn = '';
    if (typeof parsed.isInterviewEnded !== 'boolean') parsed.isInterviewEnded = false;

    // Invariant: If current question has not yet been answered, clear any stale transition lead-in
    const curQ = parsed.questions[parsed.currentQuestionIndex];
    const hasAnsweredCurQ = curQ && parsed.answers.some(a => a.questionId === curQ.id);
    if (!hasAnsweredCurQ) {
      parsed.conversationalLeadIn = '';
    }

    return parsed;
  } catch (err) {
    console.warn('[InterviewContext] Purging corrupted active session from localStorage:', err);
    try {
      localStorage.removeItem(ACTIVE_SESSION_KEY);
    } catch {
      // ignore
    }
    return null;
  }
}

export function InterviewProvider({ children }) {
  const { user, loading: authLoading } = useAuth();
  const initialSession = useMemo(() => loadActiveSession(), []);

  const [session, setSession] = useState(initialSession);
  const [setup, setSetup] = useState(() => {
    if (initialSession?.interviewConfig) {
      return { ...initialSetup, ...initialSession.interviewConfig,
        interviewType: initialSession.interviewConfig.interviewType ?? initialSession.interviewPlan?.interview_type ?? null };
    }
    return initialSetup;
  });
  const [currentStep, setCurrentStep] = useState(0);
  const [questions, setQuestions] = useState(() => initialSession?.questions || []);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(() => initialSession?.currentQuestionIndex || 0);
  const [answers, setAnswers] = useState(() => initialSession?.answers || []);
  const [skippedQuestions, setSkippedQuestions] = useState(() => initialSession?.skippedQuestions || []);
  const [consecutiveFollowUps, setConsecutiveFollowUps] = useState(() => initialSession?.consecutiveFollowUps || 0);
  const [adaptiveDecision, setAdaptiveDecision] = useState(() => initialSession?.adaptiveDecision || null);
  const [submissionStage, setSubmissionStage] = useState(null);
  const isAdaptiveLoading = Boolean(submissionStage);
  const [interviewPlan, setInterviewPlan] = useState(() => initialSession?.interviewPlan || null);
  const [interviewState, setInterviewState] = useState(() => initialSession?.interviewState || null);
  const [conversationalLeadIn, setConversationalLeadIn] = useState(() => initialSession?.conversationalLeadIn || '');
  const [isInterviewEnded, setIsInterviewEnded] = useState(() => initialSession?.isInterviewEnded || false);
  const [currentQuestionStartedAt, setCurrentQuestionStartedAt] = useState(
    () => initialSession?.currentQuestionStartedAt || Date.now()
  );
  const [feedback, setFeedback] = useState(null);
  const [evaluation, setEvaluation] = useState(null);
  const [report, setReport] = useState(null);
  const [isInterviewActive, setIsInterviewActive] = useState(() => !!initialSession && initialSession.status === 'active');

  const updateSetup = useCallback((data) => {
    setSetup(prev => {
      const next = { ...prev, ...data };
      if (next.interviewType !== 'Technical') next.subject = null;
      return next;
    });
  }, []);

  const sessionRef = useRef(initialSession);
  const draftKey = user?.id ? `interviewiq_setup_engine:${user.id}` : null;
  const setInferenceEngine = useCallback((engine) => {
    if (!['local', 'aws'].includes(engine) || sessionRef.current?.status === 'active') return;
    try { if (draftKey) sessionStorage.setItem(draftKey, engine); } catch { /* storage optional */ }
    updateSetup({ inferenceEngine: engine, resume: null, candidateProfile: null, resumeId: null,
      jobProfile: null, jobDescriptionId: null, analysis: null });
  }, [draftKey, updateSetup]);
  const persistSession = useCallback((updatedSession) => {
    sessionRef.current = updatedSession;
    setSession(updatedSession);
    try {
      localStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(updatedSession));
    } catch (err) {
      console.error('[InterviewContext] Failed to persist session to localStorage:', err);
    }
  }, []);

  const isResumeParsingRef = useRef(false);
  const parseResume = useCallback(async (file) => {
    if (!file) {
      updateSetup({ resume: null, candidateProfile: null, resumeId: null });
      return null;
    }
    if (isResumeParsingRef.current) {
      console.warn('[InterviewContext] parseResume already in progress — ignoring duplicate invocation');
      return null;
    }
    isResumeParsingRef.current = true;
    try {
      const response = await parseResumeApi(file, setup.inferenceEngine);
      updateSetup({
        resume: file,
        candidateProfile: response.candidate_profile,
        resumeId: response.resume_id || null,
      });
      return response.candidate_profile;
    } finally {
      isResumeParsingRef.current = false;
    }
  }, [updateSetup, setup.inferenceEngine]);

  const isJobParsingRef = useRef(false);
  const parseJobDescription = useCallback(async (text) => {
    if (!text || !text.trim()) {
      updateSetup({ jobDescription: '', jobProfile: null, jobDescriptionId: null });
      return null;
    }
    if (isJobParsingRef.current) {
      console.warn('[InterviewContext] parseJobDescription already in progress — ignoring duplicate invocation');
      return null;
    }
    isJobParsingRef.current = true;
    try {
      const response = await parseJobDescriptionApi(text, setup.inferenceEngine);
      const roleTitle = response.job_profile?.role_title;
      updateSetup({
        jobDescription: text,
        jobProfile: response.job_profile,
        jobDescriptionId: response.job_description_id || null,
        role: roleTitle && roleTitle !== 'Not specified' ? roleTitle : setup.role,
      });
      return response.job_profile;
    } finally {
      isJobParsingRef.current = false;
    }
  }, [setup.role, setup.inferenceEngine, updateSetup]);

  const analyzeMatch = useCallback(async (threshold = 0.60) => {
    if (!setup.candidateProfile || !setup.jobProfile) {
      return null;
    }
    const response = await analyzeResumeJobMatchApi(
      setup.candidateProfile,
      setup.jobProfile,
      threshold
    );
    updateSetup({ analysis: response });
    return response;
  }, [setup.candidateProfile, setup.jobProfile, updateSetup]);

  const startInterview = useCallback(async () => {
    if (!['Technical', 'HR', 'Mixed'].includes(setup.interviewType)) {
      throw new Error('Select a valid interview type before starting.');
    }
    if (!setup.candidateProfile || !setup.jobProfile) {
      throw new Error('Please complete resume and job description setup before starting the interview.');
    }

    const now = Date.now();
    let firstQuestion;
    let plan = null;
    let state = null;
    let sessionId = `session-${now}-${Math.random().toString(36).substring(2, 7)}`;

    try {
      const response = await startAdaptiveInterviewApi({
        inferenceEngine: setup.inferenceEngine,
        candidateProfile: setup.candidateProfile,
        jobProfile: setup.jobProfile,
        analysis: setup.analysis,
        interviewType: setup.interviewType,
        subject: setup.subject || null,
        difficulty: setup.difficulty || 'Medium',
        interviewMode: setup.interviewMode || 'STATIC',
        questionCount: setup.questionCount || 10,
        mode: setup.mode || 'Text',
        role: setup.role || 'Software Engineer',
        resumeId: setup.resumeId || null,
        jobDescriptionId: setup.jobDescriptionId || null,
      });
      if (response && response.first_question) {
        firstQuestion = response.first_question;
        plan = response.interview_plan;
        state = response.interview_state;
        if (response.session_id) sessionId = response.session_id;
      }
    } catch (startErr) {
      throw startErr;
    }
    if (!firstQuestion?.id || !firstQuestion?.question || !sessionId) {
      throw new Error('The interview service did not return a valid session. Please retry.');
    }

    const initialQuestions = [firstQuestion];

    const newSession = {
      sessionId,
      userId: user?.id,
      createdAt: now,
      startedAt: now,
      status: 'active',
      questions: initialQuestions,
      currentQuestionIndex: 0,
      answers: [],
      skippedQuestions: [],
      consecutiveFollowUps: 0,
      adaptiveDecision: null,
      conversationalLeadIn: '',
      interviewPlan: plan,
      interviewState: state,
      isInterviewEnded: false,
      currentQuestionStartedAt: now,
      completedAt: null,
      interviewConfig: {
        inferenceEngine: setup.inferenceEngine,
        role: setup.role,
        interviewType: setup.interviewType,
        subject: plan?.subject || null,
        difficulty: setup.difficulty,
        interviewMode: setup.interviewMode || 'STATIC',
        questionCount: setup.questionCount,
        mode: setup.mode,
        candidateProfile: setup.candidateProfile,
        jobProfile: setup.jobProfile,
        analysis: setup.analysis,
      },
    };

    setQuestions(initialQuestions);
    setCurrentQuestionIndex(0);
    setAnswers([]);
    setSkippedQuestions([]);
    setConsecutiveFollowUps(0);
    setAdaptiveDecision(null);
    setInterviewPlan(plan);
    setInterviewState(state);
    setIsInterviewEnded(false);
    setConversationalLeadIn('');
    setCurrentQuestionStartedAt(now);
    setFeedback(null);
    setEvaluation(null);
    setIsInterviewActive(true);

    persistSession(newSession);
    try { if (draftKey) sessionStorage.removeItem(draftKey); } catch { /* storage optional */ }
    return initialQuestions;
  }, [
    user?.id,
    draftKey,
    setup.candidateProfile,
    setup.jobProfile,
    setup.analysis,
    setup.interviewType,
    setup.inferenceEngine,
    setup.subject,
    setup.difficulty,
    setup.interviewMode,
    setup.questionCount,
    setup.mode,
    setup.role,
    setup.resumeId,
    setup.jobDescriptionId,
    persistSession,
  ]);

  const pipelineRef = useRef(null);
  if (!pipelineRef.current) {
    pipelineRef.current = createSubmissionPipeline({
      evaluate: params => {
        setSubmissionStage('Evaluating your answer');
        return evaluateCandidateAnswerApi(params);
      },
      adapt: params => {
        const config = sessionRef.current?.interviewConfig;
        const finalTurn = config?.interviewMode === 'STATIC' && params.questionHistory.length >= config.questionCount;
        setSubmissionStage(finalTurn ? 'Finishing your interview' : 'Preparing your next question');
        return getAdaptiveNextQuestionApi(params);
      },
      getSession: () => sessionRef.current,
      save: persistSession,
    });
  }

  const submitAnswer = useCallback(async (answerText, answerSource) => {
    try {
      const result = await pipelineRef.current.submit(answerText, answerSource);
      const saved = sessionRef.current;
      setAnswers(saved.answers);
      setQuestions(saved.questions);
      setEvaluation(result.evaluation);
      setFeedback(result.feedback);
      setAdaptiveDecision(result.adaptive);
      setInterviewPlan(saved.interviewPlan);
      setInterviewState(saved.interviewState);
      setConsecutiveFollowUps(saved.consecutiveFollowUps);
      setIsInterviewEnded(saved.isInterviewEnded);
      setConversationalLeadIn(result.lead_in);
      return result;
    } catch (err) {
      if ([503, 504].includes(err.status)) {
        const engine = sessionRef.current?.interviewConfig?.inferenceEngine === 'aws' ? 'AWS CPU' : 'Local GPU';
        throw new Error(`${err.message} Retry this answer with ${engine}, the engine saved for this interview.`, { cause: err });
      }
      throw err;
    } finally {
      if (sessionRef.current) setAnswers(sessionRef.current.answers);
      setSubmissionStage(null);
    }
  }, []);

  const nextQuestion = useCallback(() => {
    const saved = sessionRef.current;
    const current = saved?.questions[saved.currentQuestionIndex];
    const record = saved?.answers.find(a => a.questionId === current?.id);
    if (!record?.evaluation || !record.adaptiveComplete) return false;
    if (saved.isInterviewEnded) return false;
    const nextIndex = saved.currentQuestionIndex + 1;
    if (!saved.questions[nextIndex]) return false;
    const updated = { ...saved, currentQuestionIndex: nextIndex,
      currentQuestionStartedAt: Date.now(), conversationalLeadIn: '', adaptiveDecision: null, draft: null };
    persistSession(updated);
    setCurrentQuestionIndex(nextIndex);
    setCurrentQuestionStartedAt(updated.currentQuestionStartedAt);
    setEvaluation(null);
    setFeedback(null);
    setAdaptiveDecision(null);
    setConversationalLeadIn('');
    return true;
  }, [persistSession]);

  // Explicit skip is evaluated as a real non-answer through the same engine.
  const skipQuestion = useCallback(() => submitAnswer("I don't know"), [submitAnswer]);
  const handleTimeout = skipQuestion;

  const saveDraft = useCallback((questionId, text) => {
    const saved = sessionRef.current;
    if (!saved || saved.questions[saved.currentQuestionIndex]?.id !== questionId) return;
    if (saved.answers.some(a => a.questionId === questionId && a.adaptiveComplete)) return;
    persistSession({ ...saved, draft: { questionId, text } });
  }, [persistSession]);

  const finishRef = useRef(null);
  const generateReport = useCallback(() => {
    if (finishRef.current) return finishRef.current;
    finishRef.current = (async () => {
      if (pipelineRef.current.isBusy()) throw new Error('Please wait for your answer to finish saving.');
      const saved = sessionRef.current;
      if (!saved) throw new Error('No interview session to complete.');
      const result = await persistInterviewReportApi({
        session_id: saved.sessionId,
        role: saved.interviewConfig.role,
        interview_type: saved.interviewConfig.interviewType,
        difficulty: saved.interviewConfig.difficulty,
        answers: saved.answers, questions: saved.questions,
        total_questions: saved.interviewConfig.questionCount,
        duration_secs: Math.max(0, Math.round((Date.now() - saved.startedAt) / 1000)),
        interview_plan: saved.interviewPlan, interview_state: saved.interviewState,
      });
      if (!result?.persisted || !result.report) throw new Error('Report could not be saved. Your interview is preserved; retry End Interview.');
      setReport(result.report);
      setIsInterviewActive(false);
      persistSession({ ...saved, status: 'completed', completedAt: Date.now() });
      localStorage.removeItem(ACTIVE_SESSION_KEY);
      return result.report;
    })().finally(() => { finishRef.current = null; });
    return finishRef.current;
  }, [persistSession]);

  const resetInterview = useCallback(() => {
    setSetup(initialSetup);
    setCurrentStep(0);
    setQuestions([]);
    setCurrentQuestionIndex(0);
    setAnswers([]);
    setSkippedQuestions([]);
    setConsecutiveFollowUps(0);
    setAdaptiveDecision(null);
    setInterviewPlan(null);
    setInterviewState(null);
    setConversationalLeadIn('');
    setIsInterviewEnded(false);
    setFeedback(null);
    setEvaluation(null);
    setReport(null);
    setIsInterviewActive(false);
    setSession(null);
    sessionRef.current = null;

    try {
      localStorage.removeItem(ACTIVE_SESSION_KEY);
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    if (!authLoading && sessionRef.current && sessionRef.current.userId !== user?.id) resetInterview();
  }, [user?.id, authLoading, resetInterview]);

  const draftOwner = useRef(undefined);
  useEffect(() => {
    if (authLoading || draftOwner.current === draftKey) return;
    draftOwner.current = draftKey;
    if (sessionRef.current?.status === 'active') return;
    let engine = initialSetup.inferenceEngine;
    try {
      const savedEngine = draftKey && sessionStorage.getItem(draftKey);
      if (savedEngine === 'local' || savedEngine === 'aws') engine = savedEngine;
    } catch { /* storage optional */ }
    setSetup({ ...initialSetup, inferenceEngine: engine });
  }, [draftKey, authLoading]);

  // Derived progress statistics
  const progressPercentage = useMemo(() => {
    if (setup.interviewMode === 'DYNAMIC') {
      return Math.min(100, Math.round((answers.length / 10) * 100));
    }
    const maxQ = setup.questionCount || 10;
    return Math.min(100, Math.round((answers.length / maxQ) * 100));
  }, [setup.interviewMode, setup.questionCount, answers.length]);

  const answeredCount = useMemo(() => {
    return answers.filter(a => !a.skipped).length;
  }, [answers]);

  const skippedCount = useMemo(() => {
    return skippedQuestions.length;
  }, [skippedQuestions]);

  const remainingCount = useMemo(() => {
    if (setup.interviewMode === 'DYNAMIC') {
      return Math.max(0, 10 - answers.length);
    }
    const maxQ = setup.questionCount || 10;
    return Math.max(0, maxQ - answers.length);
  }, [setup.interviewMode, setup.questionCount, answers.length]);

  return (
    <InterviewContext.Provider value={{
      setup, updateSetup, setInferenceEngine, currentStep, setCurrentStep,
      session,
      questions, currentQuestionIndex, currentQuestion: questions[currentQuestionIndex],
      answers, skippedQuestions, currentQuestionStartedAt,
      consecutiveFollowUps, adaptiveDecision, isAdaptiveLoading, submissionStage,
      interviewPlan, interviewState, conversationalLeadIn, isInterviewEnded,
      feedback, evaluation, report,
      isInterviewActive,
      progressPercentage, answeredCount, skippedCount, remainingCount,
      parseResume, parseJobDescription, analyzeMatch, startInterview, submitAnswer,
      nextQuestion, skipQuestion, handleTimeout, generateReport, resetInterview, saveDraft,
    }}>
      {children}
    </InterviewContext.Provider>
  );
}

export const useInterview = () => {
  const ctx = useContext(InterviewContext);
  if (!ctx) throw new Error('useInterview must be used within InterviewProvider');
  return ctx;
};

