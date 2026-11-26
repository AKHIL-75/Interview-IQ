import { timingSpan, timingEvent } from './performance.js';
/** Serial, resumable evaluation -> adaptive commit. No UI or speech callback can bypass it. */
export function createSubmissionPipeline({ evaluate, adapt, getSession, save }) {
  let pending = null;
  async function run(text, answerSource) {
    let session = getSession();
    const question = session?.questions[session.currentQuestionIndex];
    const answer = String(text || '').trim();
    if (!question || !answer) throw new Error('Enter an answer before submitting.');
    let record = session.answers.find(a => a.questionId === question.id);
    if (record?.adaptiveComplete) return record.result;
    if (record?.evaluation && record.answer !== answer) {
      throw new Error('This answer was evaluated. Retry with the saved answer to finish progression.');
    }
    const sessionId = session.sessionId;
    const assertCurrent = () => {
      const latest = getSession();
      const active = latest?.questions[latest.currentQuestionIndex];
      const committed = latest?.answers.find(item => item.questionId === question.id);
      if (latest?.sessionId !== sessionId || active?.id !== question.id || (committed && committed.answer !== answer)) {
        throw new Error('This response belongs to an earlier interview attempt. Current progress was preserved.');
      }
    };
    const config = session.interviewConfig;
    if (!record?.evaluation) {
      timingEvent('evaluation.request');
      const evaluation = await evaluate({ sessionId: session.sessionId, questionId: question.id, question: question.question, candidateAnswer: answer,
        answerSource,
        expectedAnswer: question.expected_aspects?.join('; '), jobTitle: config.role,
        category: question.category, difficulty: question.difficulty, relevantSkills: [question.topic],
        stage: question.stage, topic: question.topic });
      timingEvent('evaluation.received');
      assertCurrent();
      if ([evaluation?.evaluation_status, evaluation?.answer_status].some(status => ['FAILED', 'ERROR', 'UNAVAILABLE'].includes(status))) {
        throw new Error('Evaluation is unavailable. Your answer is preserved; please retry.');
      }
      for (const key of ['score', 'technicalAccuracy', 'relevance', 'clarity']) {
        if (!Number.isFinite(evaluation?.[key]) || evaluation[key] < 0 || evaluation[key] > 100) {
          throw new Error('Evaluation returned invalid scores. Your answer is preserved; please retry.');
        }
      }
      record = { questionId: question.id, question: question.question, answer, evaluation,
        feedback: { ...evaluation, overallScore: evaluation.score, scores: { ...evaluation, communication: evaluation.clarity } }, skipped: false,
        startedAt: session.currentQuestionStartedAt, submittedAt: Date.now(),
        timeSpent: Math.max(0, Math.round((Date.now() - session.currentQuestionStartedAt) / 1000)),
        adaptiveComplete: false };
      session = { ...session, answers: [...session.answers.filter(a => a.questionId !== question.id), record],
        draft: { questionId: question.id, text: answer } };
      save(session); // checkpoint: adaptive retry never evaluates the answer twice
    }
    timingEvent('adaptive.request');
    const adaptive = await adapt({ sessionId: session.sessionId, previousQuestion: question.question,
      candidateAnswer: record.answer, evaluation: record.evaluation, category: question.category,
      difficulty: question.difficulty, relevantSkills: [question.topic], currentTopic: question.topic,
      consecutiveFollowUps: session.consecutiveFollowUps,
      questionHistory: session.questions.slice(0, session.currentQuestionIndex + 1).map(q => q.question),
      answerHistory: session.answers, role: config.role, interviewMode: config.interviewMode,
      interviewPlan: session.interviewPlan, interviewState: session.interviewState,
      candidateProfile: config.candidateProfile, jobProfile: config.jobProfile, analysis: config.analysis });
    timingEvent('next_question.received');
    assertCurrent();
    const ended = adaptive?.end_interview === true || adaptive?.decision === 'END_INTERVIEW';
    if (!adaptive || (!ended && (!adaptive.question?.id || !adaptive.question?.question))) {
      throw new Error('No next question was returned. Retry to continue your saved answer.');
    }
    if (!ended && session.questions.some(q => q.id === adaptive.question.id || q.question === adaptive.question.question)) {
      throw new Error('The service returned a duplicate question. Retry to continue.');
    }
    const result = { evaluation: record.evaluation, feedback: record.feedback, adaptive,
      end_interview: ended, lead_in: adaptive.conversational_lead_in || '' };
    save({ ...session, answers: session.answers.map(a => a.questionId === question.id ? { ...record, adaptiveComplete: true, result } : a),
      questions: ended ? session.questions : [...session.questions, adaptive.question],
      interviewPlan: adaptive.interview_plan || session.interviewPlan,
      interviewState: adaptive.interview_state || session.interviewState,
      adaptiveDecision: adaptive, isInterviewEnded: ended, conversationalLeadIn: result.lead_in,
      consecutiveFollowUps: adaptive.isFollowUp ? session.consecutiveFollowUps + 1 : 0, draft: null });
    return result;
  }
  return {
    isBusy: () => !!pending,
    submit(text, answerSource) {
      if (pending) return pending;
      const finishTiming = timingSpan('submission');
      pending = run(text, answerSource).finally(() => { finishTiming(); pending = null; });
      return pending;
    },
  };
}
