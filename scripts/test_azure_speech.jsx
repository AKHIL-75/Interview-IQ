import React from 'react';
import { act, create } from 'react-test-renderer';
import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import AzureSpeechProvider from '../src/services/azureSpeechProvider';
import VoiceSelector from '../src/components/InterviewerVoiceSelector';
import { AZURE_VOICES, DEFAULT_AZURE_VOICE, VOICE_STORAGE_KEY, VOICE_PREVIEW_TEXT } from '../src/services/azureVoices';
import realVoiceService from '../src/services/interviewerVoiceService.js';
import apiClient from '../src/services/client';
import Stage from '../src/components/ImmersiveInterviewStage';
import ControlBar from '../src/components/InterviewControlBar';
import CaptionsOverlay from '../src/components/CaptionsOverlay';
import QuestionCard from '../src/components/QuestionCard';
import { createSubmissionPipeline } from '../src/services/submissionPipeline';
import './test_live_captions.jsx';

const blob = new Blob(['ID3-mock-audio'], { type: 'audio/mpeg' });
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };
function providerFixture(synthesize = async () => blob, blocked = false) {
  const audio = [], revoked = [], calls = [];
  const provider = new AzureSpeechProvider({
    synthesize: (text, signal, voice) => { calls.push({ text, signal, voice }); return synthesize(text, signal, voice); },
    createAudio: url => {
      const item = { url, play: async () => { if (blocked) throw Error('Autoplay blocked'); },
        pause() { this.paused = true; }, removeAttribute() {}, load() {} };
      audio.push(item); return item;
    },
    urls: { createObjectURL: () => `blob:${audio.length}`, revokeObjectURL: url => revoked.push(url) },
  });
  return { provider, audio, revoked, calls };
}

test('same pending question makes one request; replay reuses audio; URLs are released', async () => {
  const pending = deferred();
  const f = providerFixture(() => pending.promise);
  let starts = 0, ends = 0;
  const first = f.provider.speak('Question', { onStart: () => starts++, onEnd: () => ends++ });
  await f.provider.speak('Question');
  assert.equal(f.calls.length, 1);
  pending.resolve(blob); await first;
  f.audio[0].onplaying(); f.audio[0].onplaying(); f.audio[0].onended();
  assert.equal(starts, 1); assert.equal(ends, 1); assert.equal(f.revoked.length, 1);
  await f.provider.speak('Question');
  assert.equal(f.calls.length, 1); assert.equal(f.audio.length, 2);
  f.provider.stop(); assert.equal(f.revoked.length, 2);
});

test('new question aborts pending audio and ignores a late response', async () => {
  const pending = deferred();
  const f = providerFixture(text => text === 'Old' ? pending.promise : Promise.resolve(blob));
  let stale = 0;
  const old = f.provider.speak('Old', { onEnd: () => stale++, onError: () => stale++ });
  await f.provider.speak('New');
  assert.equal(f.calls[0].signal.aborted, true);
  pending.resolve(blob); await old;
  assert.equal(f.audio.length, 1); assert.equal(stale, 0);
  f.provider.stop();
});

test('stopping playback suppresses stale terminal events and cache can be cleared', async () => {
  const f = providerFixture(); let ends = 0;
  await f.provider.speak('Question', { onEnd: () => ends++ });
  const late = f.audio[0].onended;
  f.provider.stop(); late();
  assert.equal(ends, 0); assert.equal(f.audio[0].paused, true);
  assert.equal(f.provider.isSpeaking(), false);
  f.provider.clearCache(); await f.provider.speak('Question');
  assert.equal(f.calls.length, 2); f.provider.stop();
});

test('network failures, empty audio and blocked playback end safely without speaking', async () => {
  for (const f of [providerFixture(async () => { throw Error('offline'); }),
    providerFixture(async () => new Blob([])), providerFixture(undefined, true)]) {
    let errors = 0;
    await f.provider.speak('Question', { onError: () => errors++ });
    assert.equal(errors, 1); assert.equal(f.provider.isSpeaking(), false);
    assert.equal(f.revoked.length, f.audio.length);
  }
});

test('all five voices propagate to the existing authenticated endpoint', async () => {
  const original = apiClient.postBlob;
  const f = providerFixture();
  const real = new AzureSpeechProvider({ createAudio: f.provider.createAudio, urls: f.provider.urls });
  const sent = [];
  apiClient.postBlob = async (path, payload, options) => {
    assert.equal(path, '/speech/synthesize');
    assert.ok(options.signal instanceof AbortSignal);
    sent.push(payload); return blob;
  };
  try {
    for (const voice of AZURE_VOICES) {
      real.setVoice(voice.name);
      await real.speak('Question'); real.stop();
    }
    assert.deepEqual(sent, AZURE_VOICES.map(v => ({ text: 'Question', voice: v.name })));
    assert.equal(real.setVoice('unsupported'), false);
    assert.equal(real.getCurrentVoice().name, AZURE_VOICES.at(-1).name);
  } finally { real.stop(); apiClient.postBlob = original; }
});

test('cache separates voices, reuses unchanged previews, and stays bounded', async () => {
  const f = providerFixture();
  for (let pass = 0; pass < 2; pass++) {
    for (const voice of AZURE_VOICES) {
      f.provider.setVoice(voice.name);
      await f.provider.speak(VOICE_PREVIEW_TEXT); f.provider.stop();
    }
  }
  assert.equal(f.calls.length, 5);
  for (let n = 0; n < 12; n++) { await f.provider.speak(`Question ${n}`); f.provider.stop(); }
  assert.equal(f.provider.cache.size, 8);
  f.provider.clearCache(); assert.equal(f.provider.cache.size, 0);
});

test('switching voices cancels pending and playing audio and suppresses late results', async () => {
  const pending = deferred();
  const f = providerFixture((text, signal, voice) => voice === DEFAULT_AZURE_VOICE ? pending.promise : blob);
  let canceled = 0;
  const old = f.provider.speak('Question', { onCancel: () => canceled++ });
  f.provider.setVoice('en-IN-NeerjaNeural');
  await f.provider.speak('Question');
  pending.resolve(blob); await old;
  assert.equal(f.calls[0].signal.aborted, true);
  assert.equal(canceled, 1); assert.equal(f.audio.length, 1);
  assert.equal(f.provider.cache.size, 1);
  f.provider.setVoice('en-US-BrianNeural');
  assert.equal(f.audio[0].paused, true); assert.equal(f.revoked.length, 1);
  assert.equal(f.provider.isSpeaking(), false);
});

test('selection persists and restores without overwriting it during initialization', () => {
  assert.equal(new AzureSpeechProvider().getCurrentVoice().name, DEFAULT_AZURE_VOICE);
  assert.equal(localStorage.getItem(VOICE_STORAGE_KEY), null);
  for (const voice of AZURE_VOICES) {
    new AzureSpeechProvider().setVoice(voice.name);
    assert.equal(localStorage.getItem(VOICE_STORAGE_KEY), voice.name);
    assert.equal(new AzureSpeechProvider().getCurrentVoice().name, voice.name);
  }
  localStorage.setItem(VOICE_STORAGE_KEY, 'unsupported');
  assert.equal(new AzureSpeechProvider().getCurrentVoice().name, DEFAULT_AZURE_VOICE);
  globalThis.localStorage = { getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); } };
  const f = new AzureSpeechProvider();
  assert.equal(f.getCurrentVoice().name, DEFAULT_AZURE_VOICE);
  assert.equal(f.setVoice('en-IN-AaravNeural'), true);
});

test('authenticated binary client refreshes once and returns MP3', async () => {
  const original = globalThis.fetch;
  let calls = 0, refreshes = 0;
  globalThis.__auth = { refreshSession: async () => { refreshes++; return { data: { session: { access_token: 'new-mock-token' } } }; } };
  globalThis.fetch = async (url, config) => {
    assert.match(url, /\/api\/v1\/speech\/synthesize$/);
    assert.equal(config.headers.Authorization, 'Bearer mock-token');
    assert.deepEqual(JSON.parse(config.body), { text: 'Question' });
    return ++calls === 1 ? new Response('{}', { status: 401 }) : new Response(blob);
  };
  try {
    const result = await apiClient.postBlob('/speech/synthesize', { text: 'Question' });
    assert.equal(result.type, 'audio/mpeg'); assert.equal(calls, 2); assert.equal(refreshes, 1);
  } finally { globalThis.fetch = original; }
});

test('binary client rejects non-audio and propagates cancellation to fetch', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => new Response('{}', { headers: { 'Content-Type': 'application/json' } });
    await assert.rejects(apiClient.postBlob('/speech/synthesize', { text: 'Question' }), /audio is unavailable/);
    const controller = new AbortController(); controller.abort();
    globalThis.fetch = async (_, config) => { assert.equal(config.signal.aborted, true); throw new DOMException('Canceled', 'AbortError'); };
    await assert.rejects(apiClient.postBlob('/speech/synthesize', { text: 'Question' }, { signal: controller.signal }));
  } finally { globalThis.fetch = original; }
});

let spoken, stops;
function storage() { const map = new Map(); return { getItem: k => map.get(k) ?? null, setItem: (k, v) => map.set(k, String(v)) }; }
beforeEach(() => {
  apiClient.get = async () => ({ enabled: false });
  spoken = []; stops = 0;
  globalThis.localStorage = storage(); globalThis.sessionStorage = storage(); globalThis.window = {};
  globalThis.__voice = { stop() { stops++; }, clearCache() {}, isSpeaking: () => false,
    speak: (text, options) => spoken.push({ text, ...options }) };
});
function props(id = 'q1', sessionId = 'session-one') {
  return { session: { sessionId, answers: [], startedAt: Date.now() },
    currentQuestion: { id, question: `Question ${id}` }, currentQuestionIndex: 0, answers: [],
    setup: { mode: 'Voice' }, saveDraft() {}, nextQuestion() {}, handleFinish: async () => {} };
}

test('selector previews on demand, prevents duplicates, displays playback, and restores selection', async () => {
  const pending = deferred(), f = providerFixture(() => pending.promise);
  realVoiceService.activeProvider = f.provider; globalThis.__voice = realVoiceService;
  let view;
  try {
    await act(async () => { view = create(<VoiceSelector />); });
    assert.equal(f.calls.length, 0);
    assert.equal(view.root.findAllByProps({ type: 'radio' }).length, 5);
    const preview = () => view.root.findByProps({ 'aria-label': 'Preview Neerja' });
    act(() => { preview().props.onClick(); preview().props.onClick(); });
    assert.equal(f.calls.length, 1); assert.equal(f.calls[0].voice, 'en-IN-NeerjaNeural');
    assert.equal(f.calls[0].text, VOICE_PREVIEW_TEXT);
    assert.equal(preview().props.disabled, true);
    assert.match(JSON.stringify(view.toJSON()), /Loading/);
    await act(async () => { pending.resolve(blob); });
    act(() => f.audio[0].onplaying());
    assert.match(JSON.stringify(view.toJSON()), /Playing/);
    act(() => f.audio[0].onended());
    assert.equal(preview().props.disabled, false);
    await act(async () => preview().props.onClick());
    assert.equal(f.calls.length, 1);
    await act(async () => view.unmount());
    assert.equal(f.audio.at(-1).paused, true);
    await act(async () => { view = create(<VoiceSelector />); });
    assert.equal(view.root.findByProps({ type: 'radio', value: 'en-IN-NeerjaNeural' }).props.checked, true);
  } finally { if (view) await act(async () => view.unmount()); f.provider.stop(); }
});

test('selector reports preview failure, permits retry, and cancels synthesis on navigation', async () => {
  let attempts = 0;
  const pending = deferred();
  const f = providerFixture(async () => { if (++attempts === 1) throw Error('offline'); return pending.promise; });
  realVoiceService.activeProvider = f.provider; globalThis.__voice = realVoiceService;
  let view;
  try {
    await act(async () => { view = create(<VoiceSelector />); });
    await act(async () => view.root.findByProps({ 'aria-label': 'Preview Brian' }).props.onClick());
    assert.match(JSON.stringify(view.toJSON()), /Voice preview is unavailable/);
    assert.equal(view.root.findByProps({ 'aria-label': 'Preview Brian' }).props.disabled, false);
    act(() => view.root.findByProps({ 'aria-label': 'Preview Brian' }).props.onClick());
    await act(async () => view.unmount());
    assert.equal(f.calls[1].signal.aborted, true);
    await act(async () => pending.resolve(blob));
    assert.equal(f.audio.length, 0);
  } finally { if (view) await act(async () => view.unmount()); f.provider.stop(); }
});

test('switching preview ignores old completion and media errors release playback for retry', async () => {
  const pending = deferred(), f = providerFixture((text, signal, voice) => voice === 'en-IN-NeerjaNeural' ? pending.promise : blob);
  realVoiceService.activeProvider = f.provider; globalThis.__voice = realVoiceService;
  let view;
  try {
    await act(async () => { view = create(<VoiceSelector />); });
    act(() => view.root.findByProps({ 'aria-label': 'Preview Neerja' }).props.onClick());
    await act(async () => view.root.findByProps({ 'aria-label': 'Preview Brian' }).props.onClick());
    assert.equal(f.calls[0].signal.aborted, true);
    await act(async () => pending.resolve(blob));
    assert.equal(f.audio.length, 1);
    assert.equal(view.root.findByProps({ 'aria-label': 'Preview Brian' }).props.disabled, true);
    act(() => f.audio[0].onerror());
    assert.equal(f.provider.isSpeaking(), false);
    assert.equal(f.revoked.length, 1);
    assert.match(JSON.stringify(view.toJSON()), /Voice preview is unavailable/);
    await act(async () => view.root.findByProps({ 'aria-label': 'Preview Brian' }).props.onClick());
    assert.equal(f.calls.length, 2); // Valid cached MP3 remains available after a playback error.
    assert.equal(f.audio.length, 2);
  } finally { if (view) await act(async () => view.unmount()); f.provider.stop(); }
});

test('changing voice during an interview cancels speech without changing drafts and uses new voice for follow-ups', async () => {
  const f = providerFixture();
  realVoiceService.activeProvider = f.provider; globalThis.__voice = realVoiceService;
  let view, advances = 0, saves = 0;
  try {
    const input = { ...props(), saveDraft: () => saves++, nextQuestion: () => advances++ };
    await act(async () => { view = create(<Stage {...input} />); });
    assert.equal(f.calls[0].voice, DEFAULT_AZURE_VOICE);
    await act(async () => view.root.findByProps({ 'aria-label': 'Interviewer voice' }).props.onClick());
    await act(async () => view.root.findByType('select').props.onChange({ target: { value: 'en-IN-PrabhatNeural' } }));
    assert.equal(f.audio[0].paused, true);
    assert.equal(view.root.findByType(ControlBar).props.isSpeaking, false);
    assert.equal(view.root.findByType(CaptionsOverlay).props.question, undefined);
    assert.deepEqual(view.root.findByProps({ 'aria-label': 'Current question' }).findByType('p').children, ['Question q1']);
    assert.equal(advances, 0); assert.equal(saves, 0);
    await act(async () => view.root.findByType(ControlBar).props.onToggleVoice());
    const restored = { ...input, session: { ...input.session, draft: { questionId: 'restored', text: 'Preserved draft' } }, currentQuestion: { id: 'restored', question: 'Restored question' } };
    await act(async () => view.update(<Stage {...restored} />));
    await act(async () => view.root.findByType('select').props.onChange({ target: { value: 'en-IN-AaravNeural' } }));
    assert.equal(view.root.findByType(ControlBar).props.canDoneAnswer, true);
    assert.match(JSON.stringify(view.toJSON()), /Answer ready/);
    assert.equal(saves, 0);
    await act(async () => view.root.findByType(ControlBar).props.onToggleVoice());
    await act(async () => view.update(<Stage {...props('follow-up')} />));
    assert.equal(f.calls.at(-1).voice, 'en-IN-AaravNeural');
    assert.equal(f.calls.at(-1).text, 'Question follow-up');
  } finally { if (view) await act(async () => view.unmount()); f.provider.stop(); }
});

test('rerenders speak once; a new question speaks; session changes cancel audio', async () => {
  let view;
  try {
    await act(async () => { view = create(<Stage {...props()} />); });
    await act(async () => view.update(<Stage {...props()} />));
    assert.equal(spoken.length, 1);
    await act(async () => view.update(<Stage {...props('q2')} />));
    assert.deepEqual(spoken.map(s => s.text), ['Question q1', 'Question q2']);
    const before = stops;
    await act(async () => view.update(<Stage {...props('q2', 'session-two')} />));
    assert.equal(spoken.length, 3); assert.ok(stops > before);
  } finally { if (view) await act(async () => view.unmount()); }
});

test('voice off cancels audio, keeps question readable, suppresses next speech, and preserves answer', async () => {
  let view;
  try {
    await act(async () => { view = create(<Stage {...props()} />); });
    const before = stops;
    await act(async () => view.root.findByType(ControlBar).props.onToggleVoice());
    assert.ok(stops > before);
    assert.equal(view.root.findByType(ControlBar).props.voiceEnabled, false);
    assert.deepEqual(view.root.findByProps({ 'aria-label': 'Current question' }).findByType('p').children, ['Question q1']);
    const restored = props('restored'); restored.session.draft = { questionId: 'restored', text: 'Candidate draft' };
    await act(async () => view.update(<Stage {...restored} />));
    await act(async () => view.root.findByType(ControlBar).props.onToggleVoice());
    assert.equal(view.root.findByType(ControlBar).props.canDoneAnswer, true);
    await act(async () => view.root.findByType(ControlBar).props.onRepeatQuestion());
    assert.equal(spoken.length, 2); assert.equal(spoken[1].text, 'Question restored');
    await act(async () => view.root.findByType(ControlBar).props.onToggleVoice());
    await act(async () => view.update(<Stage {...props('q2')} />));
    assert.equal(spoken.length, 2);
  } finally { if (view) await act(async () => view.unmount()); }
});

test('refresh does not automatically replay the question; explicit repeat still works', async () => {
  let view;
  try {
    await act(async () => { view = create(<Stage {...props()} />); });
    await act(async () => view.unmount());
    await act(async () => { view = create(<Stage {...props()} />); });
    assert.equal(spoken.length, 1);
    await act(async () => view.root.findByType(ControlBar).props.onRepeatQuestion());
    assert.equal(spoken.length, 2);
  } finally { if (view) await act(async () => view.unmount()); }
});

test('unmount before deferred playback cancels the request', async () => {
  let view;
  act(() => { view = create(<Stage {...props()} />); });
  act(() => view.unmount());
  await Promise.resolve();
  assert.equal(spoken.length, 0);
});

test('audio failure retains question and microphone answering without advancing', async () => {
  let view, advances = 0;
  try {
    await act(async () => { view = create(<Stage {...props()} nextQuestion={() => advances++} />); });
    await act(async () => spoken[0].onError());
    assert.match(JSON.stringify(view.toJSON()), /Question q1/);
    assert.equal(view.root.findByType(ControlBar).props.isSpeaking, false);
    assert.equal(view.root.findAllByType('textarea').length, 0);
    assert.equal(view.root.findByType(ControlBar).props.canRecord, true);
    assert.equal(advances, 0);
  } finally { if (view) await act(async () => view.unmount()); }
});

test('project question stays identical in text view, speech, evaluation and follow-up but hidden in live captions', async () => {
  const question = { id: 'project-q', question: 'For your GardenTrack project, explain how you implemented reminders.',
    topic: 'GardenTrack', stage: 'PROJECT', category: 'Technical', difficulty: 'Medium',
    expected_aspects: ['Address the specific question asked'] };
  let view, card;
  try {
    await act(async () => { card = create(<QuestionCard question={question.question} topic={question.topic} />); });
    assert.equal(card.root.findByType('h2').children.join(''), question.question);
    for (const mode of ['Voice', 'Camera']) {
      await act(async () => { view = create(<Stage {...props('project-q', mode)} currentQuestion={question} setup={{ mode }} />); });
      assert.equal(spoken.at(-1).text, question.question);
      await act(async () => view.root.findByType(ControlBar).props.onToggleCaptions());
      assert.equal(view.root.findByType(CaptionsOverlay).props.question, undefined);
      assert.deepEqual(view.root.findByProps({ 'aria-label': 'Current question' }).findByType('p').children, [question.question]);
      assert.equal(JSON.stringify(view.toJSON()).split(question.question).length - 1, 1);
      await act(async () => view.unmount()); view = null;
    }
    let saved = { sessionId: 'project-session', questions: [question], currentQuestionIndex: 0, answers: [],
      currentQuestionStartedAt: Date.now(), interviewConfig: { role: 'Engineer', interviewMode: 'STATIC' } };
    let evaluated, followed;
    const pipeline = createSubmissionPipeline({ getSession: () => saved, save: value => { saved = value; },
      evaluate: async input => { evaluated = input; return { score: 70, technicalAccuracy: 70, relevance: 70, depth: 70, clarity: 70,
        suggestedAnswer: 'Describe the reminders you actually implemented for GardenTrack.' }; },
      adapt: async input => { followed = input; return { decision: 'END_INTERVIEW', end_interview: true }; } });
    await pipeline.submit('I implemented the reminder screen.');
    assert.equal(evaluated.question, question.question);
    assert.equal(evaluated.expectedAnswer, question.expected_aspects.join('; '));
    assert.equal(followed.previousQuestion, question.question);
    assert.deepEqual(followed.questionHistory, [question.question]);
    assert.equal(saved.answers[0].question, question.question);
    assert.match(saved.answers[0].evaluation.suggestedAnswer, /GardenTrack/);
  } finally {
    if (view) await act(async () => view.unmount());
    if (card) await act(async () => card.unmount());
  }
});
