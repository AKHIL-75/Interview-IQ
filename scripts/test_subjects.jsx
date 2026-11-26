import test, { beforeEach, after } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { create, act } from 'react-test-renderer';
import { MemoryRouter } from 'react-router-dom';
import { InterviewProvider, useInterview, ACTIVE_SESSION_KEY } from '../src/context/InterviewContext';
import { ToastProvider } from '../src/context/ToastContext';
import InterviewPage from '../src/pages/InterviewPage';
import ReportPage from '../src/pages/ReportPage';
import SetupPage from '../src/pages/InterviewSetupPage';
import { startAdaptiveInterview, generateInterviewQuestions, getAdaptiveNextQuestion } from '../src/services/api';
import FileUpload from '../src/components/FileUpload';

const storage = new Map();
const draftStorage = new Map();
globalThis.sessionStorage = { getItem: key => draftStorage.get(key), setItem: (key, value) => draftStorage.set(key, value),
  removeItem: key => draftStorage.delete(key) };
globalThis.localStorage = { getItem: k => storage.get(k) || null, setItem: (k, v) => storage.set(k, v), removeItem: k => storage.delete(k) };
globalThis.window = {};
let context, view, calls;
const ev = { score: 20, technicalAccuracy: 20, relevance: 30, depth: 20, clarity: 50 };
function Probe() { context = useInterview(); return null; }
async function mount(child = <InterviewPage />, route = '/') {
  await act(async () => { view = create(<MemoryRouter initialEntries={[route]}><ToastProvider><InterviewProvider><Probe />{child}</InterviewProvider></ToastProvider></MemoryRouter>); });
}
beforeEach(async () => {
  if (view) await act(async () => view.unmount());
  storage.clear(); calls = [];
  draftStorage.clear();
  globalThis.httpGet = async () => ({ local: true, aws: false });
  globalThis.httpPost = async (url, body) => {
    calls.push({ url, body });
    if (url === '/interview/start') return { session_id: 'subject-session',
      first_question: { id: 'q1', question: 'What is a Java primitive type?', topic: 'Java', difficulty: 'Medium', category: 'Technical' },
      interview_plan: { subject: body.subject, mode: 'STATIC' }, interview_state: { subject: body.subject, current_difficulty: 'Medium', questions_asked: 1 } };
    if (url === '/evaluation/evaluate') return ev;
    if (url === '/interview/next-question') return { decision: 'RECOVERY_QUESTION', isFollowUp: true,
      question: { id: 'q2', question: 'What does a Java variable hold?', topic: 'Java', category: 'Technical', difficulty: 'Easy' },
      interview_plan: body.interview_plan, interview_state: { subject: 'Java', current_difficulty: 'Easy', questions_asked: 2 } };
    if (url === '/interview/report') return { persisted: true, report: { overall_score: 20, scores: { subject: 'Java' }, question_analysis: [] } };
    if (url === '/analysis/match') return { match_score: 80, skills_found: [], gap_skills: [] };
    throw new Error(`Unexpected route ${url}`);
  };
});

test('API preserves optional general mode and forwards subject for both generators', async () => {
  await startAdaptiveInterview({ subject: 'OOP' });
  assert.equal(calls[0].body.subject, 'OOP');
  await startAdaptiveInterview({});
  assert.equal(calls[1].body.subject, null);
  globalThis.httpPost = async (url, body) => { assert.equal(url, '/interview/generate-questions'); assert.equal(body.subject, 'Java'); };
  await generateInterviewQuestions({ subject: 'Java' });
});

test('engine selection checks availability and keeps an unavailable selection until explicitly changed', async () => {
  let resolve;
  globalThis.httpGet = () => new Promise(r => { resolve = r; });
  await mount(<SetupPage />);
  const radio = engine => view.root.findByProps({ type: 'radio', value: engine });
  assert.equal(radio('local').props.checked, true);
  assert.equal(radio('aws').props.disabled, true);
  assert.match(JSON.stringify(view.toJSON()), /Checking/);
  await act(async () => resolve({ local: true, aws: false }));
  assert.equal(radio('aws').props.disabled, true);
  const retry = () => view.root.findAllByType('button').find(b => b.children.includes('Check availability'));
  await act(async () => retry().props.onClick());
  await act(async () => resolve({ local: true, aws: true }));
  await act(async () => radio('aws').props.onChange());
  assert.equal(context.setup.inferenceEngine, 'aws');
  await act(async () => view.unmount());
  globalThis.httpGet = async () => ({ local: true, aws: false });
  await mount(<SetupPage />);
  assert.equal(radio('aws').props.checked, true);
  assert.equal(radio('aws').props.disabled, true);
  assert.match(JSON.stringify(view.toJSON()), /Selected engine unavailable/);
  await act(async () => radio('local').props.onChange());
  assert.equal(context.setup.inferenceEngine, 'local');
});

test('selected engine reaches upload, JD and start, restores on refresh and locks during interview', async () => {
  globalThis.httpGet = async () => ({ local: true, aws: true });
  const routed = [];
  const originalPost = globalThis.httpPost;
  globalThis.httpUpload = async (url, data, options) => {
    assert.ok(data instanceof FormData);
    routed.push([url, options.headers['X-Inference-Engine']]);
    return { candidate_profile: { extracted_skills: ['Java'] } };
  };
  globalThis.httpPost = async (url, body, options) => {
    routed.push([url, options?.headers?.['X-Inference-Engine']]);
    if (url === '/job/parse') return { job_profile: { required_skills: ['Java'] } };
    return originalPost(url, body);
  };
  await mount(<SetupPage />);
  const radio = engine => view.root.findByProps({ type: 'radio', value: engine });
  await act(async () => radio('aws').props.onChange());
  await act(async () => view.root.findByType(FileUpload).props.onFileSelect(new Blob(['fixture'])));
  await act(async () => context.parseJobDescription('A Java development position.'));
  await act(async () => context.startInterview());
  assert.deepEqual(routed, [['/resume/parse', 'aws'], ['/job/parse', 'aws'], ['/interview/start', 'aws']]);
  assert.equal(context.session.interviewConfig.inferenceEngine, 'aws');
  await act(async () => view.unmount());
  await mount(<SetupPage />);
  assert.equal(radio('aws').props.checked, true);
  assert.equal(radio('local').props.disabled, true);
  await act(async () => context.setInferenceEngine('local'));
  assert.equal(context.setup.inferenceEngine, 'aws');
});

test('start, answer, refresh and next submission retain scope, history and current difficulty', async () => {
  await mount();
  await act(async () => context.updateSetup({ candidateProfile: {}, jobProfile: {}, subject: 'Java', mode: 'Text' }));
  await act(async () => context.startInterview());
  assert.equal(calls[0].body.subject, 'Java');
  assert.match(JSON.stringify(view.toJSON()), /Java/);
  await act(async () => context.submitAnswer('A Java primitive is a class'));
  await act(async () => context.nextQuestion());
  await act(async () => context.saveDraft('q2', 'My saved answer'));
  await act(async () => view.unmount());
  await mount();
  assert.equal(context.setup.subject, 'Java');
  assert.equal(context.currentQuestion.id, 'q2');
  assert.equal(context.currentQuestion.difficulty, 'Easy');
  assert.equal(context.interviewState.current_difficulty, 'Easy');
  assert.equal(context.questions.length, 2);
  assert.equal(context.answers.length, 1);
  assert.equal(context.session.draft.text, 'My saved answer');
  globalThis.httpPost = async (url, body) => {
    if (url === '/evaluation/evaluate') { assert.equal(body.difficulty, 'Easy'); return ev; }
    assert.equal(body.interview_plan.subject, 'Java');
    assert.equal(body.question_history.length, 2);
    assert.equal(body.answer_history.length, 2);
    const checkpoint = JSON.parse(storage.get(ACTIVE_SESSION_KEY));
    const legacyBytes = Buffer.byteLength(JSON.stringify({ ...body, answer_history: checkpoint.answers }));
    const requestBytes = Buffer.byteLength(JSON.stringify(body));
    assert.ok(requestBytes < legacyBytes);
    if (process.env.IIQ_PROFILE_PAYLOAD) console.info('adaptive request bytes', { legacyBytes, requestBytes });
    for (const entry of body.answer_history) {
      assert.ok(entry.questionId && entry.question && entry.answer && entry.evaluation);
      assert.equal(entry.result, undefined);
      assert.equal(entry.feedback, undefined);
    }
    return { decision: 'END_INTERVIEW', end_interview: true };
  };
  await act(async () => context.submitAnswer('My saved answer'));
  assert.equal(context.isInterviewEnded, true);
});

test('old saved sessions without subject remain restorable', async () => {
  storage.set(ACTIVE_SESSION_KEY, JSON.stringify({ sessionId: 'legacy', userId: 'test-owner', status: 'active',
    questions: [{ id: 'q1', question: 'Introduce yourself' }], answers: [], currentQuestionIndex: 0, interviewConfig: { mode: 'Text' } }));
  await mount();
  assert.equal(context.setup.subject, null);
  assert.equal(context.currentQuestion.question, 'Introduce yourself');
});

test('saved report reopened by History URL displays subject from persisted scores', async () => {
  globalThis.httpGet = async () => ({ report: { id: 'saved', overall_score: 70, scores: { subject: 'OOP' }, question_analysis: [] } });
  await mount(<ReportPage />, '/report?id=saved');
  assert.match(JSON.stringify(view.toJSON()), /OOP/);
});

test('report distinguishes unavailable evaluation from zero and never displays an echoed reference', async () => {
  const question = 'How did you resolve a disagreement?';
  globalThis.httpGet = async () => ({ report: { id: 'saved', overall_score: 0, question_analysis: [
    { question, candidate_answer: 'I listened.', score: 0, evaluation_status: 'FAILED', improvements: ['False failure feedback'], suggested_answer: question },
    { question: 'What is SQL?', candidate_answer: "I don't know", score: 0, technical_accuracy: 0, relevance: 0, depth: 0, clarity: 0, answer_status: 'NON_ANSWER', suggested_answer: 'SQL is a language for querying relational data.' }
  ] } });
  await mount(<ReportPage />, '/report?id=saved');
  const expand = async text => {
    const button = view.root.findAllByType('button').find(b => b.findAllByType('p').some(p => p.children.includes(text)));
    assert.ok(button); await act(async () => button.props.onClick());
  };
  await expand(question);
  let rendered = JSON.stringify(view.toJSON());
  assert.match(rendered, /Evaluation unavailable/);
  assert.match(rendered, /A model answer is unavailable/);
  assert.doesNotMatch(rendered, /False failure feedback/);
  await expand('What is SQL?');
  rendered = JSON.stringify(view.toJSON());
  assert.match(rendered, /SQL is a language for querying relational data/);
  assert.match(rendered, /0%/);
});

test('setup combobox selects subject and changing to HR clears it', async () => {
  globalThis.document = { addEventListener() {}, removeEventListener() {} };
  await mount(<SetupPage />);
  await act(async () => context.updateSetup({ resume: { name: 'fixture.pdf' }, candidateProfile: { extracted_skills: ['Java'] }, jobProfile: { required_skills: ['Java'] }, analysis: { match_score: 80 } }));
  const click = async label => {
    const button = view.root.findAllByType('button').find(b => b.findAll(n => typeof n.type === 'string').some(n => n.children.some(c => typeof c === 'string' && c.includes(label))));
    assert.ok(button, label);
    await act(async () => button.props.onClick());
  };
  await click('Continue');
  await click('Continue to Analysis');
  await click('Continue to Interview Setup');
  const dropdown = view.root.findByProps({ 'aria-haspopup': 'listbox' });
  await act(async () => dropdown.props.onClick());
  const option = view.root.findAllByProps({ role: 'option' }).find(node => node.children.includes('Object-Oriented Programming (OOP)'));
  await act(async () => option.props.onClick());
  assert.equal(context.setup.subject, 'OOP');
  await click('HR');
  assert.equal(context.setup.subject, null);
  assert.equal(view.root.findByProps({ 'aria-haspopup': 'listbox' }).props.disabled, true);
});


 test('missing evaluator result stays missing in adaptive API payload', async () => {
  globalThis.httpPost = async (url, body) => { assert.equal(body.evaluation, null); return {}; };
  await getAdaptiveNextQuestion({ previousQuestion: 'What is a Java class?' });
});


test('Your Response renders the exact submitted transcript, separate from feedback', async () => {
  const answer = 'At Quartz Harbor, I used a B-tree index on order_id; the canary phrase is violet comet 47.';
  const question = 'How does a SQL index work, and what trade-offs does it introduce?';
  globalThis.httpGet = async () => ({ report: { id: 'integrity', overall_score: 75, question_analysis: [
    { question, candidate_answer: answer, candidateAnswer: 'Stale alias', score: 75, suggested_answer: 'Different model answer.' }
  ] } });
  await mount(<ReportPage />, '/report?id=integrity');
  const button = view.root.findAllByType('button').find(b => b.findAllByType('p').some(p => p.children.includes(question)));
  await act(async () => button.props.onClick());
  const label = view.root.findAllByType('span').find(p => p.children.includes('Your Response'));
  assert.ok(label);
  assert.equal(label.parent.findAllByType('div').at(-1).children.join(''), answer);
});


test('API evaluation payload keeps the exact answer and current question identity', async () => {
  const answer = 'At Quartz Harbor, I used a B-tree index on order_id; the canary phrase is violet comet 47.';
  await mount();
  await act(async () => context.updateSetup({ candidateProfile: {}, jobProfile: {}, mode: 'Text' }));
  await act(async () => context.startInterview());
  await act(async () => context.submitAnswer(answer));
  const evaluation = calls.find(call => call.url === '/evaluation/evaluate').body;
  assert.equal(evaluation.candidate_answer, answer);
  assert.equal(evaluation.question_id, 'q1');
  assert.equal(evaluation.session_id, 'subject-session');
  assert.equal(context.answers[0].answer, answer);
});

test('report preserves the saved 49/F aggregate with strong individual answers and follow-ups', async () => {
  globalThis.httpGet = async () => ({ report: { overall_score: 49, scores: { grade: 'F' },
    question_analysis: [86, 74, 48, 38, 0].map((score, i) => ({ question: `Calibration question ${i}`, candidate_answer: 'Synthetic response', score, is_follow_up: i > 2 })) } });
  await mount(<ReportPage />, '/report?id=calibration');
  const rendered = JSON.stringify(view.toJSON());
  assert.match(rendered, /Unsatisfactory Performance/);
  for (const value of ['49', '86%', '74%', '48%', '38%', '0%', 'F']) {
    assert.ok(view.root.findAll(n => n.children?.some(c => c === value || c === Number(value))).length, `missing ${value}`);
  }
});

after(async () => { if (view) await act(async () => view.unmount()); });
