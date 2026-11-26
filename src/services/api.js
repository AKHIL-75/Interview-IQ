/** Real backend API service layer. */

import apiClient from './client';

const inferenceTimeout = import.meta.env?.VITE_DEFAULT_INFERENCE_ENGINE === 'aws' ? { timeoutMs: 330000 } : {};

function inferenceOptions(engine) {
  return engine ? { ...inferenceTimeout, headers: { 'X-Inference-Engine': engine } } : inferenceTimeout;
}

export function getInferenceEngines(signal) {
  return apiClient.get('/inference/engines', { signal, timeoutMs: 6000 });
}


// ─── Real Backend API Calls ─────────────────────────────────────

/**
 * Check if the FastAPI backend is running and healthy.
 * Calls: GET /api/v1/health
 * 
 * @returns {Promise<{status: string, service: string, version: string}>}
 * @throws {Error} If backend is unreachable or returns an error
 */
export async function checkBackendHealth() {
  return apiClient.get('/health');
}

/**
 * Parse a real PDF or DOCX resume through the backend.
 * Calls: POST /api/v1/resume/parse
 */
export async function parseResume(file, engine) {
  const formData = new FormData();
  formData.append('file', file);
  return apiClient.upload('/resume/parse', formData, inferenceOptions(engine));
}

/**
 * Parse a real job description text through the backend with Qwen3.
 * Calls: POST /api/v1/job/parse
 * 
 * @param {string} text - Raw job description text
 * @returns {Promise<{success: boolean, raw_text_length: number, job_profile: object, processing_time_ms: number}>}
 */
export async function parseJobDescription(text, engine) {
  return apiClient.post('/job/parse', { text }, inferenceOptions(engine));
}

/**
 * Compute semantic skill matching and gap analysis using Sentence Transformers.
 * Calls: POST /api/v1/analysis/match
 * 
 * @param {object} candidateProfile - CandidateProfile from Phase 4
 * @param {object} jobProfile - JobProfile from Phase 5
 * @param {number} threshold - Cosine similarity threshold (default: 0.60)
 * @returns {Promise<object>} MatchAnalysisResponse
 */
export async function analyzeResumeJobMatch(candidateProfile, jobProfile, threshold = 0.60) {
  return apiClient.post('/analysis/match', {
    candidate_profile: candidateProfile,
    job_profile: jobProfile,
    threshold,
  });
}

/**
 * Generate personalized interview questions using local Qwen3 through Ollama.
 * Calls: POST /api/v1/interview/generate-questions
 * 
 * @param {object} params
 * @param {object} params.candidateProfile - CandidateProfile from Phase 4
 * @param {object} params.jobProfile - JobProfile from Phase 5
 * @param {object} [params.analysis] - MatchAnalysisResponse from Phase 6
 * @param {string} [params.interviewType] - 'Technical' | 'HR' | 'Mixed'
 * @param {string} [params.difficulty] - 'Easy' | 'Medium' | 'Hard'
 * @param {number} [params.questionCount] - Number of questions (1-15)
 * @returns {Promise<{success: boolean, questions: Array, count: number, interview_type: string, difficulty: string, role: string}>}
 */
export async function generateInterviewQuestions({
  inferenceEngine,
  candidateProfile,
  jobProfile,
  analysis,
  interviewType = 'Technical',
  subject = null,
  difficulty = 'Medium',
  questionCount = 10,
}) {
  return apiClient.post('/interview/generate-questions', {
    candidate_profile: candidateProfile,
    job_profile: jobProfile,
    analysis: analysis || null,
    interview_type: interviewType,
    subject,
    difficulty,
    question_count: questionCount,
  }, inferenceOptions(inferenceEngine));
}

/**
 * Evaluate a candidate's answer using the Phase 10 Answer Evaluation Engine via local Qwen3.
 * Calls: POST /api/v1/evaluation/evaluate
 *
 * @param {object} params
 * @param {string} params.question - The question asked
 * @param {string} params.candidateAnswer - The candidate's submitted answer text
 * @param {string} [params.expectedAnswer] - Optional expected / reference answer
 * @param {string} [params.jobTitle] - Target job title
 * @param {string} [params.category] - 'Technical' | 'HR' | 'Behavioral' | 'Mixed'
 * @param {string} [params.difficulty] - 'Easy' | 'Medium' | 'Hard'
 * @param {Array<string>} [params.relevantSkills] - Relevant technologies / skills
 * @returns {Promise<{score: number, technicalAccuracy: number, clarity: number, depth: number, relevance: number, strengths: Array<string>, improvements: Array<string>, suggestedAnswer: string}>}
 */
export async function evaluateCandidateAnswer({
  inferenceEngine,
  sessionId, questionId,
  question,
  candidateAnswer,
  answerSource,
  expectedAnswer = null,
  jobTitle = 'Software Engineer',
  category = 'Technical',
  difficulty = 'Medium',
  relevantSkills = [],
  stage = null,
  topic = null,
}) {
  return apiClient.post('/evaluation/evaluate', {
    session_id: sessionId, question_id: questionId,
    question,
    candidate_answer: candidateAnswer,
    ...(answerSource ? { answer_source: answerSource } : {}),
    expected_answer: expectedAnswer || null,
    job_title: jobTitle,
    category,
    difficulty,
    relevant_skills: relevantSkills || [],
    stage: stage || null,
    topic: topic || null,
  }, inferenceOptions(inferenceEngine));
}

/**
 * Start an adaptive interview session with realistic planning and Question 1.
 * Calls: POST /api/v1/interview/start
 */
export async function startAdaptiveInterview({
  inferenceEngine,
  candidateProfile,
  jobProfile,
  analysis,
  interviewType = 'Technical',
  subject = null,
  difficulty = 'Medium',
  interviewMode = 'STATIC',
  questionCount = 10,
  mode = 'Text',
  role = 'Software Engineer',
  resumeId = null,
  jobDescriptionId = null,
}) {
  return apiClient.post('/interview/start', {
    candidate_profile: candidateProfile,
    job_profile: jobProfile,
    analysis: analysis || null,
    interview_type: interviewType,
    subject,
    difficulty,
    interview_mode: interviewMode,
    question_count: questionCount,
    mode,
    role,
    resume_id: resumeId,
    job_description_id: jobDescriptionId,
  }, inferenceOptions(inferenceEngine));
}

/**
 * Determine adaptive decision and retrieve next follow-up/challenge question via local Qwen3.
 * Calls: POST /api/v1/interview/next-question
 *
 * @param {object} params
 * @param {string} [params.sessionId] - Session ID
 * @param {string} params.previousQuestion - The question that was answered
 * @param {string} params.candidateAnswer - The candidate's submitted answer
 * @param {object} params.evaluation - The Phase 10 evaluation output
 * @param {string} [params.category] - 'Technical' | 'HR'
 * @param {string} [params.difficulty] - 'Easy' | 'Medium' | 'Hard'
 * @param {Array<string>} [params.relevantSkills] - Relevant technologies
 * @param {string} [params.currentTopic] - Topic of the previous question
 * @param {number} [params.consecutiveFollowUps] - Count of consecutive follow-ups
 * @param {Array<string>} [params.questionHistory] - Previous questions asked
 * @param {Array<object>} [params.answerHistory] - Previous answer records
 * @param {string} [params.role] - Target role title
 * @param {string} [params.interviewMode] - 'STATIC' | 'DYNAMIC'
 * @param {object} [params.interviewPlan] - Plan state
 * @param {object} [params.interviewState] - Dynamic tracking state
 * @param {object} [params.candidateProfile] - Resume profile
 * @param {object} [params.jobProfile] - Job profile
 * @returns {Promise<{decision: string, reason: string, targetSkill: string, targetConcept: string, difficulty: string, nextDifficulty: string, isFollowUp: boolean, question: object|null, end_interview: boolean, conversational_lead_in: string}>}
 */
export async function getAdaptiveNextQuestion({
  sessionId = null,
  previousQuestion,
  candidateAnswer = '',
  evaluation,
  category = 'Technical',
  difficulty = 'Medium',
  relevantSkills = [],
  currentTopic = 'General',
  consecutiveFollowUps = 0,
  questionHistory = [],
  answerHistory = [],
  role = 'Software Engineer',
  interviewMode = 'STATIC',
  interviewPlan = null,
  interviewState = null,
  candidateProfile = null,
  jobProfile = null,
  analysis = null,
}) {
  const savedId = sessionId || interviewPlan?.session_id || interviewState?.session_id || null;
  // Local replay checkpoints include prior responses and feedback for the UI.
  // Adaptive history needs just the question, answer, identity and evaluation.
  const history = answerHistory.map(({ questionId, question, answer, evaluation }) =>
    ({ questionId, question, answer, evaluation }));
  return apiClient.post('/interview/next-question', {
    previous_question: previousQuestion,
    candidate_answer: candidateAnswer,
    evaluation: evaluation ? {
      score: evaluation?.score ?? 0,
      answer_status: evaluation?.answer_status ?? null,
      technicalAccuracy: evaluation?.technicalAccuracy || 0,
      relevance: evaluation?.relevance || 0,
      clarity: evaluation?.clarity || 0,
      strengths: evaluation?.strengths || [],
      improvements: evaluation?.improvements || [],
      suggestedAnswer: evaluation?.suggestedAnswer || '',
    } : null,
    category,
    difficulty,
    relevant_skills: relevantSkills,
    current_topic: currentTopic,
    consecutive_follow_ups: consecutiveFollowUps,
    question_history: questionHistory,
    answer_history: history,
    role,
    interview_mode: interviewMode,
    interview_plan: interviewPlan,
    interview_state: interviewState,
    candidate_profile: candidateProfile,
    job_profile: jobProfile,
    analysis,
    session_id: savedId,
  }, inferenceOptions());
}

/**
 * Persist a completed interview report to Supabase via backend POST /api/v1/interview/report.
 *
 * @param {object} reportData - Final report data
 * @returns {Promise<object>}
 */
export async function persistInterviewReport(reportData) {
  return apiClient.post('/interview/report', reportData);
}

/**
 * Fetch historical interview sessions and reports from Supabase via backend GET /api/v1/interview/history.
 *
 * @returns {Promise<{success: boolean, count: number, history: Array, reports: Array}>}
 */
export async function fetchInterviewHistory() {
  return apiClient.get('/interview/history');
}

export const getInterviewHistory = fetchInterviewHistory;

/**
 * Fetch real database-backed dashboard analytics via backend GET /api/v1/interview/analytics.
 *
 * @returns {Promise<{success: boolean, analytics: object}>}
 */
export async function fetchDashboardAnalytics() {
  return apiClient.get('/interview/analytics');
}

export const getInterviewAnalytics = fetchDashboardAnalytics;
export const getDashboardStats = fetchDashboardAnalytics;

/**
 * Fetch a single historical interview report by report UUID or session ID via backend GET /api/v1/interview/report/:id.
 *
 * @param {string} reportOrSessionId
 * @returns {Promise<{success: boolean, report: object}>}
 */
export async function fetchReportById(reportOrSessionId) {
  if (!reportOrSessionId) throw new Error('Report or session ID is required');
  return apiClient.get(`/interview/report/${encodeURIComponent(reportOrSessionId)}`);
}

export const getReportById = fetchReportById;

/**
 * Transcribe an audio blob using Azure Speech via backend.
 * Calls: POST /api/v1/audio/transcribe (multipart/form-data)
 *
 * Phase 15 — Voice Interview Mode
 *
 * @param {Blob} audioBlob - Audio blob from MediaRecorder
 * @param {string} [mimeType] - MIME type of the audio (e.g. 'audio/webm;codecs=opus')
 * @returns {Promise<{success: boolean, text: string, language: string, duration_seconds: number, processing_time_ms: number, model: string}>}
 */
export async function transcribeAudio(audioBlob, mimeType = 'audio/webm', options = {}) {
  if (!audioBlob || audioBlob.size === 0) {
    throw new Error('No audio data to transcribe.');
  }

  // Determine file extension from MIME type
  const extMap = {
    'audio/webm': '.webm',
    'audio/webm;codecs=opus': '.webm',
    'audio/ogg': '.ogg',
    'audio/ogg;codecs=opus': '.ogg',
    'audio/mp4': '.mp4',
    'audio/wav': '.wav',
    'audio/mpeg': '.mp3',
  };
  const ext = extMap[mimeType] || '.webm';
  const filename = `recording${ext}`;

  const formData = new FormData();
  formData.append('file', audioBlob, filename);
  if (typeof options.vadFilter === 'boolean') formData.append('vad_filter', String(options.vadFilter));

  // Server budget is at most 630 s from admission, including its queue wait.
  return apiClient.upload('/audio/transcribe', formData, { timeoutMs: 660000 });
}

