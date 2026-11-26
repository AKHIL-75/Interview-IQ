import React from 'react';
import { act, create } from 'react-test-renderer';
import { describe, test, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import MicLevelMeter from '../src/components/MicLevelMeter';
import Stage from '../src/components/ImmersiveInterviewStage';
import ControlBar from '../src/components/InterviewControlBar';
import CaptionsOverlay from '../src/components/CaptionsOverlay';
import Toast from '../src/components/Toast';
import { ToastProvider, useToast } from '../src/context/ToastContext';
import apiClient from '../src/services/client';
import { LiveCaptionSession } from '../src/services/liveCaptions';
import { transcribeAudio as realTranscribe } from '../src/services/api.js';

const settle = async () => { for (let n = 0; n < 15; n++) await Promise.resolve(); };
const storage = () => { const map = new Map(); return { getItem: k => map.get(k) ?? null, setItem: (k, v) => map.set(k, v), entries: () => [...map] }; };
let f, view, toast, original;
function Probe() { toast = useToast(); return <Toast/>; }
function input(id = 'q1', mode = 'Voice') {
  return { session: { sessionId: 'caption-session', answers: [], startedAt: Date.now() }, setup: { mode, role: 'Engineer', questionCount: 5 },
    questions: [{ id }], currentQuestion: { id, question: 'Private question ' + id }, currentQuestionIndex: id === 'q2' ? 1 : 0, answers: [],
    saveDraft: (id, answer) => f.saved.push({ id, answer }), submitAnswer: async answer => { f.events.push('submit'); f.submissions.push(answer); return { end_interview: false }; },
    nextQuestion: () => true, handleFinish: async () => { f.finished++; } };
}
const tree = props => <ToastProvider><Stage {...props}/><Probe/></ToastProvider>;
async function mount(props = input()) { await act(async () => { view = create(tree(props)); await settle(); }); }
const controls = () => view.root.findByType(ControlBar).props;
async function tick(t, ms) { await act(async () => { t.mock.timers.tick(ms); await settle(); }); }
async function begin(t) { await act(async () => f.spoken.at(-1).onEnd()); await tick(t, 401); }
async function final(text) { await act(async () => f.recognizers.at(-1).recognized(null, { result: { reason: 'speech', text } })); }

describe('live candidate captions', () => {
  beforeEach(() => {
    original = { get: apiClient.get, post: apiClient.post, upload: apiClient.upload, fetch: globalThis.fetch };
    f = { spoken: [], recognizers: [], contexts: [], nodes: [], pushes: [], streams: [], tokenCalls: 0, configCalls: 0, audioCaptures: 0, videoCaptures: 0, events: [], submissions: [], saved: [], finished: 0, config: { enabled: true, language: 'en-IN' } };
    globalThis.localStorage = storage(); globalThis.sessionStorage = storage();
    const node = () => ({ connect() {}, disconnect() { this.disconnected = true; } });
    class AudioContext {
      constructor() { this.audioWorklet = { addModule: async () => {} }; this.destination = {}; this.state = 'running'; f.contexts.push(this); }
      createMediaStreamSource(stream) { this.stream = stream; const source = node(); f.nodes.push(source); return source; }
      createMediaStreamDestination() { const track = { stops: 0, stop() { this.stops++; } }; this.destinationTrack = track; return { stream: { active: true, getTracks: () => [track] } }; }
      createGain() { return { ...node(), gain: { value: 1 } }; }
      createAnalyser() { return { ...node(), frequencyBinCount: 4, getByteFrequencyData: array => array.fill(20) }; }
      resume() { return Promise.resolve(); }
      close() { this.closed = true; return Promise.resolve(); }
    }
    class AudioWorkletNode { constructor() { Object.assign(this, node()); this.port = {}; f.nodes.push(this); } }
    f.keys = new Set();
    globalThis.window = { AudioContext, AudioWorkletNode, addEventListener: (name, fn) => f.keys.add(fn), removeEventListener: (name, fn) => f.keys.delete(fn) };
    globalThis.document = { querySelector: () => null };
    globalThis.requestAnimationFrame = () => 1; globalThis.cancelAnimationFrame = () => {};
    Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: async options => {
      if (options.audio) f.audioCaptures++; else f.videoCaptures++;
      const track = { readyState: 'live', stops: 0, stop() { this.stops++; this.readyState = 'ended'; } };
      const stream = { active: true, getTracks: () => [track], getAudioTracks: () => [track], getVideoTracks: () => [track], track };
      f.streams.push(stream); return stream;
    } } } });
    globalThis.MediaRecorder = class {
      static isTypeSupported() { return true; }
      constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; }
      start() { this.state = 'recording'; }
      stop() { f.events.push('recorder-stop'); this.state = 'inactive'; this.ondataavailable?.({ data: new Blob(['audio']) }); queueMicrotask(() => this.onstop?.()); }
    };
    let voice = { name: 'en-US-JennyNeural' };
    globalThis.__voice = { speak: (text, options) => f.spoken.push({ text, ...options }), stop() {}, clearCache() {}, isSpeaking: () => false,
      getCurrentVoice: () => voice, selectVoice: name => { voice = { name }; } };
    globalThis.__transcribe = async (...args) => { f.events.push('transcribe'); f.uploadOptions = args[2]; return { success: true, text: 'Backend truth' }; };
    apiClient.get = async path => { assert.equal(path, '/speech/stt-config'); f.configCalls++; if (f.configError) throw Error('offline'); return f.config; };
    apiClient.post = async (path, body, options) => { assert.equal(path, '/speech/stt-token'); assert.ok(options.signal); f.tokenCalls++; if (f.tokenError) throw Error('sensitive-upstream'); return { token: 'test-short-lived-token', region: 'centralindia', expires_in_s: 600 }; };
    class Recognizer {
      static enableTelemetry(value) { assert.equal(value, false); }
      constructor(config, audio) { this.config = config; this.audio = audio; f.recognizers.push(this); }
      startContinuousRecognitionAsync(ok) { this.starts = (this.starts || 0) + 1; f.events.push('caption-start'); ok(); }
      stopContinuousRecognitionAsync(ok) { f.events.push('caption-stop'); this.stopped = true; ok(); }
      close(ok) { this.closed = true; ok(); }
    }
    globalThis.__captionSdk = { SpeechRecognizer: Recognizer, Connection: { fromRecognizer: () => { const connection = { openConnection() { f.events.push('preopen'); this.connected?.(); }, closeConnection() { this.closed = true; }, close() {} }; f.connection = connection; return connection; } }, CancellationReason: { Error: 'error' }, ResultReason: { RecognizedSpeech: 'speech' },
      SpeechConfig: { fromAuthorizationToken: (token, region) => ({ token, region }), fromEndpoint: endpoint => ({ endpoint }) },
      AudioStreamFormat: { getWaveFormatPCM: (...args) => { assert.deepEqual(args, [16000, 16, 1]); return {}; } },
      AudioInputStream: { createPushStream: () => { const push = { write(buffer) { this.buffer = buffer; }, close() { this.closed = true; } }; f.pushes.push(push); return push; } },
      AudioConfig: { fromStreamInput: push => ({ push, close() { this.closed = true; } }) } };
  });
  afterEach(async () => {
    if (view) await act(async () => view.unmount()); view = null;
    Object.assign(apiClient, { get: original.get, post: original.post, upload: original.upload }); globalThis.fetch = original.fetch;
    delete globalThis.__transcribe;
  });

  test('Stage 3: exact Azure final is submitted without a second transcription', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    const original = 'At Quartz Harbor, I used a B-tree index on order_id; the canary phrase is violet comet 47.';
    await final(original);
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, original);
    await act(async () => controls().onDoneAnswering());
    assert.deepEqual(f.submissions, [original]);
    assert.equal(f.events.filter(event => event === 'transcribe').length, 0);
    assert.ok(f.saved.every(row => row.answer === original));
    console.info(JSON.stringify({ synthetic: true, azure_final: original, caption_state: original, submitted: f.submissions[0], first_mismatch: null }));
  });
  test('explicitly disabled config hides captions silently and still submits', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
    for (const mode of ['Voice', 'Camera']) {
      f.config = { enabled: false };
      globalThis.sessionStorage = storage();
      await mount(input('q1', mode)); await begin(t);
      assert.equal(controls().captionsAvailable, false); assert.equal(f.tokenCalls, 0); assert.equal(toast.toasts.length, 0);
      await act(async () => controls().onDoneAnswering());
      assert.equal(f.uploadOptions, undefined);
      await act(async () => view.unmount()); view = null;
    }
    assert.equal(f.submissions.length, 2);
  });
  test('config connection failure is visible and Retry restores captions on the current recording', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
    for (const mode of ['Voice', 'Camera']) {
      globalThis.sessionStorage = storage();
      f.configError = true;
      const configCalls = f.configCalls, tokenCalls = f.tokenCalls, captures = f.audioCaptures;
      await mount(input('q1', mode));
      assert.equal(f.configCalls, configCalls + 1);
      assert.equal(f.tokenCalls, tokenCalls);
      assert.equal(toast.toasts.length, 1);
      assert.match(JSON.stringify(view.toJSON()), /Captions unavailable/);
      await begin(t);
      assert.equal(controls().isRecording, true);
      const stream = f.contexts.findLast(context => context.stream).stream;
      await tick(t, 6000);
      assert.equal(toast.toasts.length, 0);
      assert.equal(view.root.findAllByProps({ 'aria-label': 'Your live captions' }).length, 1);
      f.configError = false;
      await act(async () => { await view.root.findByProps({ 'aria-label': 'Retry live captions' }).props.onClick(); await settle(); });
      assert.equal(f.configCalls, configCalls + 2);
      assert.equal(f.tokenCalls, tokenCalls + 1);
      assert.equal(f.audioCaptures, captures + 1);
      assert.equal(controls().captionsAvailable, true);
      assert.equal(f.recognizers.at(-1).starts, 1);
      const exact = 'Recovered Azure final: violet comet 47.';
      await act(async () => controls().onToggleCaptions());
      await final(exact);
      assert.match(JSON.stringify(view.toJSON()), /Recovered Azure final: violet comet 47\./);
      assert.equal(stream.track.stops, 0);
      await act(async () => controls().onDoneAnswering());
      assert.equal(f.submissions.at(-1), exact);
      assert.equal(f.events.filter(event => event === 'transcribe').length, 0);
      await act(async () => view.unmount()); view = null;
    }
  });
  test('continued config failure keeps Retry available and does not block fallback submission', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
    f.configError = true;
    await mount(); await begin(t);
    await tick(t, 6000);
    await act(async () => view.root.findByProps({ 'aria-label': 'Retry live captions' }).props.onClick());
    assert.equal(f.configCalls, 2);
    assert.equal(f.tokenCalls, 0);
    assert.equal(controls().isRecording, true);
    await tick(t, 6000);
    assert.equal(toast.toasts.length, 0);
    assert.equal(view.root.findAllByProps({ 'aria-label': 'Retry live captions' }).length, 1);
    await act(async () => controls().onDoneAnswering());
    assert.deepEqual(f.submissions, ['Backend truth']);
    assert.equal(f.events.filter(event => event === 'transcribe').length, 1);
  });
  test('only starts after TTS plus 400ms and active recording; repeat pauses captions', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount();
    assert.equal(f.tokenCalls, 1); assert.equal(f.audioCaptures, 0); assert.equal(f.recognizers.length, 1); assert.equal(f.recognizers[0].starts, undefined); assert.ok(f.events.includes('preopen'));
    await act(async () => f.spoken[0].onEnd()); await tick(t, 399);
    await act(async () => controls().onToggleMic());
    assert.equal(f.audioCaptures, 0); assert.equal(f.tokenCalls, 1);
    await tick(t, 2); assert.equal(f.audioCaptures, 1); assert.equal(f.recognizers.length, 1);
    assert.equal(f.recognizers[0].config.speechRecognitionLanguage, 'en-IN');
    assert.equal(f.contexts.filter(context => context.stream === f.streams[0]).length, 2); // level meter + caption tap
    await act(async () => controls().onRepeatQuestion());
    assert.equal(f.recognizers[0].closed, undefined); assert.equal(f.recognizers[0].stopped, true); assert.equal(controls().isSpeaking, true);
    assert.equal(view.root.findByType(CaptionsOverlay).props.speaking, true);
  });
  test('mute transcribes without submit; unmute makes exactly one new recording capture', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    await act(async () => controls().onToggleMic());
    assert.equal(f.submissions.length, 0); assert.equal(f.events.filter(x => x === 'transcribe').length, 1);
    assert.ok(f.events.indexOf('caption-stop') < f.events.indexOf('recorder-stop'));
    await act(async () => controls().onToggleMic());
    assert.equal(f.audioCaptures, 2); assert.equal(f.recognizers.length, 1); assert.equal(f.recognizers[0].starts, 2);
    assert.equal(f.streams[1].track.stops, 0);
  });
  test('Done stops captions first and double-click submits exact final exactly once', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t); await final('Preview only');
    const done = controls().onDoneAnswering;
    await act(async () => Promise.all([done(), done()]));
    assert.deepEqual(f.submissions, ['Preview only']);
    assert.ok(f.events.indexOf('caption-stop') < f.events.indexOf('recorder-stop'));
    assert.equal(f.events.filter(x => x === 'transcribe').length, 0);
    assert.equal(f.uploadOptions, undefined);
    assert.ok(f.saved.every(item => item.answer === 'Preview only'));
  });
  test('no final plus double Done produces exactly one upload and submission', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    const done = controls().onDoneAnswering;
    await act(async () => Promise.all([done(), done()]));
    assert.equal(f.events.filter(event => event === 'transcribe').length, 1);
    assert.deepEqual(f.submissions, ['Backend truth']);
  });
  test('captions toggle only changes visibility; new question retains saved transcript', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t); await final('First answer');
    await act(async () => controls().onToggleCaptions());
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'First answer');
    await act(async () => controls().onToggleCaptions());
    assert.equal(f.recognizers[0].closed, undefined); assert.equal(f.tokenCalls, 1);
    await act(async () => view.update(tree(input('q2'))));
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, '');
    await act(async () => view.update(tree(input('q1'))));
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'First answer');
  });
  test('interim throttles; text stays at 3s and fades at 8s', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 1000 }); await mount(); await begin(t);
    await act(async () => controls().onToggleCaptions());
    for (const text of ['a', 'ab', 'abc']) f.recognizers[0].recognizing(null, { result: { text } });
    assert.equal(view.root.findByType(CaptionsOverlay).props.interim, ''); await tick(t, 100);
    assert.equal(view.root.findByType(CaptionsOverlay).props.interim, 'abc'); await final('Final words');
    await tick(t, 3000); assert.match(JSON.stringify(view.toJSON()), /opacity-100/);
    await tick(t, 5001); assert.match(JSON.stringify(view.toJSON()), /opacity-0/);
  });
  test('8 minute token refresh retains text and never stops recording tracks', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t); await final('Stored before refresh');
    const first = f.recognizers[0]; await tick(t, 480000);
    assert.equal(first.closed, undefined); assert.equal(f.recognizers.length, 1); assert.equal(first.starts, 1); assert.equal(first.authorizationToken, 'test-short-lived-token'); assert.equal(f.tokenCalls, 2); assert.equal(f.audioCaptures, 1);
    assert.equal(f.streams[0].track.stops, 0);
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'Stored before refresh');
    await final('After refresh'); assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'Stored before refresh After refresh');
    assert.ok(!JSON.stringify([...localStorage.entries(), ...sessionStorage.entries(), view.toJSON()]).includes('test-short-lived-token'));
  });
  test('custom endpoint uses authorizationToken and backend language', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
    f.config = { enabled: true, language: 'en-IN', endpoint: 'https://test.cognitiveservices.azure.com' };
    await mount(); await begin(t);
    const config = f.recognizers[0].config;
    assert.equal(config.endpoint.href, 'https://test.cognitiveservices.azure.com/stt/speech/recognition/conversation/cognitiveservices/v1');
    assert.equal(config.authorizationToken, 'test-short-lived-token'); assert.equal(config.speechRecognitionLanguage, 'en-IN');
  });
  test('token failure shows inline error plus Retry, then recording still submits', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); f.tokenError = true;
    await mount(); await begin(t);
    assert.match(JSON.stringify(view.toJSON()), /Captions unavailable/); assert.equal(toast.toasts.length, 1);
    assert.equal(controls().isRecording, true); assert.equal(f.streams[0].track.stops, 0);
    f.tokenError = false; await act(async () => toast.toasts[0].action.onClick());
    assert.equal(f.recognizers.length, 1);
    await act(async () => controls().onDoneAnswering()); assert.deepEqual(f.submissions, ['Backend truth']);
  });
  test('recognition error cannot leak upstream details or block submission; toast expires', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    await act(async () => f.recognizers[0].canceled(null, { reason: 'error', errorDetails: 'sensitive-upstream' }));
    assert.equal(f.streams[0].track.stops, 0); assert.equal(toast.toasts.length, 1);
    assert.ok(!JSON.stringify(view.toJSON()).includes('sensitive-upstream'));
    await tick(t, 6000); assert.equal(toast.toasts.length, 0);
    await act(async () => controls().onDoneAnswering()); assert.deepEqual(f.submissions, ['Backend truth']);
  });
  test('single End button confirms, cancels safely, then releases resources', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    const endButtons = () => view.root.findAllByType('button').filter(button => button.children.includes('End Interview'));
    assert.equal(endButtons().length, 1);
    await act(async () => endButtons()[0].props.onClick()); assert.equal(f.finished, 0);
    await act(async () => view.root.findAllByType('button').find(button => button.children.includes('Keep interviewing')).props.onClick());
    assert.equal(f.streams[0].track.stops, 0);
    await act(async () => endButtons()[0].props.onClick());
    await act(async () => view.root.findAllByType('button').find(button => button.children.includes('Confirm end')).props.onClick());
    assert.equal(f.finished, 1); assert.equal(f.recognizers[0].closed, true); assert.equal(f.streams[0].track.stops, 1);
    assert.ok(f.contexts.every(context => context.closed));
  });
  test('TTS failure adds recovery status and retry keeps one visible question', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount();
    const question = () => view.root.findByProps({ 'aria-label': 'Current question' }).findByType('p').children;
    const recovery = () => view.root.findAllByProps({ role: 'status' })
      .filter(node => node.props.className?.includes('iiq-recovery'));
    assert.deepEqual(question(), ['Private question q1']);
    assert.equal(recovery().length, 0);
    await act(async () => f.spoken[0].onError());
    assert.equal(recovery().length, 1);
    assert.match(recovery()[0].findByType('p').children.join(''), /Interviewer voice unavailable/);
    assert.equal(JSON.stringify(view.toJSON()).split('Private question q1').length - 1, 1);
    await act(async () => controls().onRepeatQuestion());
    assert.equal(f.spoken.length, 2);
    await act(async () => f.spoken[1].onEnd());
    assert.equal(recovery().length, 0);
    assert.deepEqual(question(), ['Private question q1']);
  });
  test('voice popover and interviewer tile use actual selected voice', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount();
    assert.match(JSON.stringify(view.toJSON()), /Jenny/);
    await act(async () => view.root.findByProps({ 'aria-label': 'Interviewer voice' }).props.onClick());
    await act(async () => view.root.findByType('select').props.onChange({ target: { value: 'en-IN-NeerjaNeural' } }));
    const tile = view.root.findByProps({ 'aria-label': 'AI Interviewer' });
    assert.ok(JSON.stringify(tile.findByType('h3').children).includes('Neerja'));
  });
  test('repeated mount/unmount and late token response leak no capture or captions', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
    for (let i = 0; i < 3; i++) {
      globalThis.sessionStorage = storage(); await mount(); await begin(t);
      await act(async () => view.unmount()); view = null;
      assert.ok(f.recognizers.every(recognizer => recognizer.closed));
      assert.ok(f.contexts.every(context => context.closed));
      assert.equal(f.keys.size, 0);
    }
    let resolve;
    apiClient.post = () => new Promise(done => { resolve = done; });
    globalThis.sessionStorage = storage(); await mount(); await begin(t);
    const before = f.recognizers.length;
    await act(async () => view.unmount()); view = null;
    await act(async () => { resolve({ token: 'late-token', region: 'centralindia', expires_in_s: 600 }); await settle(); });
    assert.equal(f.recognizers.length, before);
    const requests = f.tokenCalls; await tick(t, 480000); assert.equal(f.tokenCalls, requests);
  });
  test('shortcuts work and ignore typing, repeats and dialogs', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    const send = (key, typing = false) => [...f.keys].forEach(fn => fn({ key, target: { closest: () => typing }, preventDefault() {} }));
    await act(async () => send('c', true)); assert.equal(controls().captionsEnabled, false);
    await act(async () => send('c')); assert.equal(controls().captionsEnabled, true);
    await act(async () => controls().onEndInterview());
    await act(async () => send('m')); assert.equal(controls().isRecording, true);
  });
  test('all Azure upload callers allow the 630s server budget plus 30s transport margin', async () => {
    const calls = []; apiClient.upload = async (...args) => { calls.push(args); return {}; };
    await realTranscribe(new Blob(['audio']), 'audio/webm');
    await realTranscribe(new Blob(['audio']), 'audio/webm', { azureEnabled: true });
    assert.deepEqual(calls.map(call => call[2].timeoutMs), [660000, 660000]);
  });
  test('interim/final updates are isolated from the stage; panel follows the video', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    await act(async () => controls().onToggleCaptions());
    const stageProps = view.root.findByProps({ 'data-interview-stage': 'true' }).props;
    f.recognizers[0].recognizing(null, { result: { text: 'interim' } }); await tick(t, 100);
    assert.equal(view.root.findByProps({ 'data-interview-stage': 'true' }).props, stageProps);
    await final('Complete final');
    assert.equal(view.root.findByProps({ 'data-interview-stage': 'true' }).props, stageProps);
    const column = view.root.findByProps({ className: 'iiq-video-column' });
    const candidate = column.findAllByType('div').find(node => node.props.className?.includes('iiq-candidate'));
    assert.equal(candidate.findAllByProps({ 'aria-label': 'Your live captions' }).length, 0);
    assert.equal(column.findAllByProps({ 'aria-label': 'Your live captions' }).length, 1);
    const starts = f.recognizers[0].starts;
    await act(async () => controls().onToggleCaptions());
    assert.equal(column.findAllByProps({ 'aria-label': 'Your live captions' }).length, 0);
    assert.equal(f.recognizers[0].starts, starts); assert.equal(f.recognizers[0].stopped, undefined);
    const css = readFileSync('src/index.css', 'utf8');
    assert.match(css, /iiq-video-column:has\(\.iiq-caption-panel\)/);
    assert.match(css, /grid-template-columns: minmax\(0, 1fr\) 290px/);
    assert.match(css, /@media \(max-width: 1023px\)/);
    assert.equal(candidate.findAllByType(MicLevelMeter).length, 0);
  });
  test('consecutive questions reuse recognizer and drain finals into the old question', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    let finishStop;
    const recognizer = f.recognizers[0];
    recognizer.stopContinuousRecognitionAsync = done => { finishStop = done; };
    await act(async () => view.update(tree(input('q2'))));
    await final('Late final from q1');
    await begin(t); assert.equal(recognizer.starts, 1);
    await act(async () => { finishStop(); await settle(); });
    assert.equal(f.recognizers.length, 1); assert.equal(recognizer.starts, 2);
    await final('Answer q2');
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'Answer q2');
    await act(async () => view.update(tree(input('q1'))));
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'Late final from q1');
  });
  test('End control cannot shrink out of the header and desktop/mobile layout has no video overlays', () => {
    const source = readFileSync('src/components/ImmersiveInterviewStage.jsx', 'utf8');
    const css = readFileSync('src/index.css', 'utf8');
    assert.match(source, /iiq-header[^"\n]*shrink-0 flex/);
    assert.match(source, /iiq-header-actions flex shrink-0/);
    assert.match(source, /ref=\{endButtonRef\} className="iiq-focus shrink-0 whitespace-nowrap/);
    assert.equal((source.match(/>End Interview<\/button>/g) || []).length, 1);
    assert.match(css, /\.iiq-header \{ flex-wrap: wrap/);
    assert.match(css, /\.iiq-progress \{ flex: 1 1 100%; order: 3/);
    assert.match(css, /backdrop-filter: none/);
  });
  test('refresh failure is recoverable without replacing the recognizer or recorder', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t); await final('Keep this');
    f.tokenError = true; await tick(t, 480000);
    assert.equal(f.streams[0].track.stops, 0); assert.equal(f.recognizers.length, 1);
    f.tokenError = false; await act(async () => toast.toasts[0].action.onClick());
    assert.equal(f.recognizers.length, 1); assert.equal(f.recognizers[0].starts, 2);
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'Keep this');
  });
  test('pending initialization cannot start after mute, and late callbacks cannot write after unmount', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] });
    let resolve; apiClient.post = () => new Promise(done => { resolve = done; });
    await mount(); await begin(t);
    await act(async () => controls().onToggleMic());
    await act(async () => { resolve({ token: 'test-token', region: 'centralindia', expires_in_s: 600 }); await settle(); });
    assert.equal(f.recognizers.length, 1); assert.equal(f.recognizers[0].starts, undefined);
    await act(async () => controls().onToggleMic());
    const lateFinal = f.recognizers[0].recognized;
    await act(async () => view.unmount()); view = null;
    lateFinal(null, { result: { reason: 'speech', text: 'late' } });
    assert.equal(f.recognizers[0].recognized, undefined); assert.equal(f.recognizers[0].recognizing, undefined);
    assert.ok(f.contexts.filter(context => context.destinationTrack).every(context => context.destinationTrack.stops === 1));
    assert.equal(f.connection.closed, true); assert.equal(f.keys.size, 0);
  });
  test('Repeat resets only the current attempt and rejects late finals/interims', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t); await final('Old attempt, amber otter 12.');
    const oldFinal = f.recognizers[0].recognized, oldInterim = f.recognizers[0].recognizing;
    await act(async () => controls().onRepeatQuestion());
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, '');
    await act(async () => { oldFinal(null, { result: { reason: 'speech', text: 'Late old answer' } }); oldInterim(null, { result: { text: 'Late interim' } }); });
    await tick(t, 100);
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, '');
    const repeats = f.spoken.length;
    await act(async () => controls().onRepeatQuestion()); assert.equal(f.spoken.length, repeats);
    await begin(t); await final('New attempt, violet comet 47.');
    await act(async () => oldFinal(null, { result: { reason: 'speech', text: 'Late old result again' } }));
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'New attempt, violet comet 47.');
    assert.equal(f.recognizers.length, 1); assert.equal(f.submissions.length, 0);
    await act(async () => controls().onDoneAnswering());
    assert.deepEqual(f.submissions, ['New attempt, violet comet 47.']);
  });
  test('Done drains final result, never submits interim, and ignores callbacks after sealing', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    f.recognizers[0].recognizing(null, { result: { text: 'Wrong interim' } }); await tick(t, 100);
    const callback = f.recognizers[0].recognized;
    f.recognizers[0].stopContinuousRecognitionAsync = done => { f.events.push('caption-stop'); callback(null, { result: { reason: 'speech', text: 'Exact final: quartz harbor 47.' } }); done(); };
    await act(async () => controls().onDoneAnswering());
    assert.deepEqual(f.submissions, ['Exact final: quartz harbor 47.']);
    await act(async () => callback(null, { result: { reason: 'speech', text: 'Too late' } }));
    const transcript = view.root.findByProps({ 'aria-label': 'Recorded answer transcript' });
    assert.deepEqual(transcript.findByType('p').children, ['Exact final: quartz harbor 47.']);
    assert.equal(view.root.findAllByType(CaptionsOverlay).length, 0);
    assert.deepEqual(f.submissions, ['Exact final: quartz harbor 47.']);
  });
  test('pending final drain is released by unmount without submitting or leaking timers', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    let stopped;
    f.recognizers[0].stopContinuousRecognitionAsync = done => { stopped = done; };
    let pending;
    await act(async () => { pending = controls().onDoneAnswering(); await settle(); });
    await act(async () => view.unmount()); view = null;
    await pending;
    stopped();
    assert.equal(f.submissions.length, 0);
    assert.ok(f.recognizers.every(recognizer => recognizer.closed));
    await tick(t, 10001);
    assert.equal(f.submissions.length, 0);
  });
  test('late upload from the previous question cannot overwrite the new answer or mute it', async t => {
    t.mock.timers.enable({ apis: ['setTimeout', 'Date'] }); await mount(); await begin(t);
    let resolve, pending;
    globalThis.__transcribe = () => new Promise(done => { resolve = done; });
    await act(async () => { pending = controls().onDoneAnswering(); await settle(); });
    assert.ok(resolve);
    await act(async () => view.update(tree(input('q2')))); await begin(t);
    await final('Current answer, violet comet 47.');
    await act(async () => { resolve({ success: true, text: 'Stale upload' }); await pending; });
    assert.equal(controls().isRecording, true);
    assert.equal(view.root.findByType(CaptionsOverlay).props.text, 'Current answer, violet comet 47.');
    assert.equal(f.submissions.length, 0);
    await act(async () => controls().onDoneAnswering());
    assert.deepEqual(f.submissions, ['Current answer, violet comet 47.']);
  });
  test('meter paints at about 15Hz without React state and cancels RAF', async () => {
    const frames = new Map(); let id = 0, reads = 0;
    globalThis.requestAnimationFrame = fn => { frames.set(++id, fn); return id; };
    globalThis.cancelAnimationFrame = key => frames.delete(key);
    window.AudioContext.prototype.createAnalyser = () => ({ frequencyBinCount: 4, getByteFrequencyData: data => { reads++; data.fill(30); }, disconnect() {} });
    const nodes = [];
    await act(async () => { view = create(<MicLevelMeter isActive stream={{}}/>, { createNodeMock: element => {
      const mock = { children: Array.from({ length: 12 }, () => ({ style: {} })) }; nodes.push(mock); return mock;
    } }); });
    const props = view.root.findByType('div').props;
    for (let time = 0; time <= 1000; time += 16) {
      const current = [...frames]; frames.clear(); current.forEach(([, frame]) => frame(time));
    }
    assert.ok(reads >= 12 && reads <= 16); assert.equal(view.root.findByType('div').props, props);
    await act(async () => view.unmount()); view = null;
    assert.equal(frames.size, 0); assert.ok(f.contexts.every(context => context.closed));
  });
});
