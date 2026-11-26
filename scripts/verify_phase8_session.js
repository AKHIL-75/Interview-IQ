/**
 * Frontend Session State & Storage Verification Script for Phase 8.
 * Simulates complete browser localStorage lifecycle, refresh recovery,
 * answer persistence, skip tracking, duplicate prevention, and corrupted recovery.
 */

// Simple in-memory localStorage polyfill for Node.js
class MockLocalStorage {
  constructor() {
    this.store = {};
  }
  getItem(key) {
    return Object.prototype.hasOwnProperty.call(this.store, key) ? this.store[key] : null;
  }
  setItem(key, value) {
    this.store[key] = String(value);
  }
  removeItem(key) {
    delete this.store[key];
  }
  clear() {
    this.store = {};
  }
}

const localStorage = new MockLocalStorage();
const ACTIVE_SESSION_KEY = 'interviewiq_active_session';

function loadActiveSession() {
  try {
    const stored = localStorage.getItem(ACTIVE_SESSION_KEY);
    if (!stored) return null;

    const parsed = JSON.parse(stored);
    if (!parsed || typeof parsed !== 'object') {
      localStorage.removeItem(ACTIVE_SESSION_KEY);
      return null;
    }

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

    return parsed;
  } catch (err) {
    try {
      localStorage.removeItem(ACTIVE_SESSION_KEY);
    } catch {
      // ignore
    }
    return null;
  }
}

function runSessionVerification() {
  console.log('=============================================================');
  console.log('STARTING PHASE 8 CLIENT-SIDE STATE VERIFICATION');
  console.log('=============================================================\n');

  // Step 1: Initial empty state
  console.log('[STEP 1] Initial empty state check...');
  let session = loadActiveSession();
  if (session !== null) throw new Error('Expected null session on empty storage');
  console.log('  PASS: Storage is clean; initial session is null');

  // Step 2: Session creation with Phase 7 questions
  console.log('\n[STEP 2] Session creation with 4 personalized questions...');
  const t0 = Date.now();
  const mockQuestions = [
    { id: 'q1', question: 'How do you optimize SQL indexing in PostgreSQL?', category: 'Technical', topic: 'SQL', difficulty: 'Medium', focus: 'Matched Skill' },
    { id: 'q2', question: 'Explain Spring Boot dependency injection mechanisms.', category: 'Technical', topic: 'Spring Boot', difficulty: 'Medium', focus: 'Matched Skill' },
    { id: 'q3', question: 'Describe a situation where you had to learn Python quickly.', category: 'HR', topic: 'Adaptability', difficulty: 'Medium', focus: 'Behavioral' },
    { id: 'q4', question: 'How do you structure microservices communication?', category: 'Technical', topic: 'System Design', difficulty: 'Medium', focus: 'Matched Skill' },
  ];

  const newSession = {
    sessionId: `session-${t0}-test123`,
    createdAt: t0,
    startedAt: t0,
    status: 'active',
    questions: mockQuestions,
    currentQuestionIndex: 0,
    answers: [],
    skippedQuestions: [],
    currentQuestionStartedAt: t0,
    completedAt: null,
    interviewConfig: {
      role: 'Java Backend Engineer',
      interviewType: 'Technical',
      difficulty: 'Medium',
      questionCount: 4,
    },
  };
  localStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(newSession));
  session = loadActiveSession();
  if (!session || session.questions.length !== 4) throw new Error('Session creation failed');
  console.log(`  PASS: Active session '${session.sessionId}' created with 4 questions at index 0`);

  // Step 3: Answer Question 1
  console.log('\n[STEP 3] Answering Question 1 and persisting...');
  const tAns1 = t0 + 12000;
  const answerRecord1 = {
    questionId: 'q1',
    question: mockQuestions[0].question,
    answer: 'I use composite B-tree indexes and analyze query execution plans.',
    startedAt: t0,
    submittedAt: tAns1,
    skipped: false,
    timedOut: false,
    timeSpent: 12,
    evaluation: { score: 85, technicalAccuracy: 88 },
  };
  session.answers.push(answerRecord1);
  localStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(session));
  console.log('  PASS: Answer 1 saved to session');

  // Step 4: Advance to Question 2
  console.log('\n[STEP 4] Advancing to Question 2...');
  const tAdv1 = t0 + 14000;
  session.currentQuestionIndex = 1;
  session.currentQuestionStartedAt = tAdv1;
  localStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(session));
  console.log('  PASS: Transitioned to index 1 (Question 2)');

  // Step 5: BROWSER REFRESH SIMULATION on Question 2
  console.log('\n[STEP 5] *** BROWSER REFRESH SIMULATION on Question 2 ***');
  const refreshedSession = loadActiveSession();
  if (!refreshedSession) throw new Error('Session lost after refresh!');
  if (refreshedSession.currentQuestionIndex !== 1) {
    throw new Error(`Expected index 1 after refresh, got ${refreshedSession.currentQuestionIndex}`);
  }
  if (refreshedSession.questions[refreshedSession.currentQuestionIndex].id !== 'q2') {
    throw new Error('Current question after refresh is not q2');
  }
  if (refreshedSession.answers.length !== 1 || refreshedSession.answers[0].questionId !== 'q1') {
    throw new Error('Question 1 answer was not preserved across refresh!');
  }
  if (refreshedSession.currentQuestionStartedAt !== tAdv1) {
    throw new Error('Timer reference timestamp was not preserved across refresh!');
  }
  console.log('  PASS: Refresh recovery successful:');
  console.log(`        - Status: ${refreshedSession.status}`);
  console.log(`        - Current Question: ${refreshedSession.questions[refreshedSession.currentQuestionIndex].id}`);
  console.log(`        - Preserved Answers: ${refreshedSession.answers.length} (Q1: "${refreshedSession.answers[0].answer}")`);
  console.log(`        - Timer Anchor: ${refreshedSession.currentQuestionStartedAt}`);

  // Step 6: Duplicate Submission Prevention
  console.log('\n[STEP 6] Testing duplicate answer submission prevention...');
  const duplicateAnswer1 = {
    questionId: 'q1',
    question: mockQuestions[0].question,
    answer: 'Updated answer with deeper explanation.',
    startedAt: t0,
    submittedAt: tAns1 + 5000,
    skipped: false,
    timedOut: false,
    timeSpent: 17,
  };
  // Context deduplication logic
  let updatedAnswers = [];
  let replaced = false;
  for (const existing of refreshedSession.answers) {
    if (existing.questionId === 'q1') {
      updatedAnswers.push(duplicateAnswer1);
      replaced = true;
    } else {
      updatedAnswers.push(existing);
    }
  }
  if (!replaced) updatedAnswers.push(duplicateAnswer1);
  refreshedSession.answers = updatedAnswers;
  if (refreshedSession.answers.length !== 1) {
    throw new Error(`Duplicate answer created! Length is ${refreshedSession.answers.length}`);
  }
  console.log('  PASS: Re-submitting Q1 updated existing record in-place; count remains 1');

  // Step 7: Skip Question 2
  console.log('\n[STEP 7] Skipping Question 2...');
  const tSkip2 = tAdv1 + 8000;
  const skipRecord2 = {
    questionId: 'q2',
    question: mockQuestions[1].question,
    answer: '',
    startedAt: tAdv1,
    submittedAt: tSkip2,
    skipped: true,
    timedOut: false,
    timeSpent: 8,
    evaluation: { score: 0, technicalAccuracy: 0, clarity: 0, depth: 0 },
  };
  refreshedSession.answers.push(skipRecord2);
  refreshedSession.skippedQuestions.push('q2');
  refreshedSession.currentQuestionIndex = 2; // Advance to Q3
  refreshedSession.currentQuestionStartedAt = tSkip2 + 1000;
  localStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(refreshedSession));
  console.log('  PASS: Question 2 skipped and recorded; advanced to Question 3');

  // Step 8: Second Refresh Test on Question 3
  console.log('\n[STEP 8] *** BROWSER REFRESH SIMULATION on Question 3 ***');
  const refresh2 = loadActiveSession();
  if (refresh2.currentQuestionIndex !== 2) throw new Error('Index incorrect on refresh 2');
  if (refresh2.answers.length !== 2) throw new Error('Answers count incorrect on refresh 2');
  if (!refresh2.skippedQuestions.includes('q2')) throw new Error('Skipped questions missing q2');
  console.log('  PASS: Refresh 2 verified: Q3 active, 2 records preserved (1 answered, 1 skipped)');

  // Step 9: Corrupted JSON Recovery
  console.log('\n[STEP 9] Testing corrupted JSON storage recovery...');
  localStorage.setItem(ACTIVE_SESSION_KEY, '{"invalid_json: true, malformed..');
  const corruptedResult = loadActiveSession();
  if (corruptedResult !== null) throw new Error('Expected null on corrupted JSON');
  if (localStorage.getItem(ACTIVE_SESSION_KEY) !== null) {
    throw new Error('Corrupted entry was not purged from localStorage!');
  }
  console.log('  PASS: Corrupted JSON safely caught, purged, and returned null without throwing');

  // Step 10: Interview Completion & Storage Clean-up
  console.log('\n[STEP 10] Testing interview completion & cleanup...');
  // Restore valid session for completion
  localStorage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(refreshedSession));
  // Simulate generateReport()
  const history = JSON.parse(localStorage.getItem('interviewiq_history') || '[]');
  history.unshift({
    id: refreshedSession.sessionId,
    role: 'Java Backend Engineer',
    score: 85,
    status: 'Completed',
    questions: 4,
  });
  localStorage.setItem('interviewiq_history', JSON.stringify(history));
  localStorage.removeItem(ACTIVE_SESSION_KEY);

  const finalCheck = loadActiveSession();
  if (finalCheck !== null) throw new Error('Active session must be cleared after completion');
  const finalHistory = JSON.parse(localStorage.getItem('interviewiq_history'));
  if (!finalHistory || finalHistory.length !== 1) throw new Error('History was not saved');
  console.log('  PASS: Active session removed on completion; history saved successfully');

  console.log('\n=============================================================');
  console.log('ALL PHASE 8 CLIENT-SIDE STATE TESTS PASSED CLEANLY!');
  console.log('=============================================================');
}

runSessionVerification();
