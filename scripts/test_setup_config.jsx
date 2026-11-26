import test from 'node:test';
import assert from 'node:assert/strict';
import React, { useState } from 'react';
import { act, create } from 'react-test-renderer';
import InterviewSetupConfig from '../src/components/InterviewSetupConfig';

globalThis.document = { addEventListener() {}, removeEventListener() {} };
const base = { role: 'Full Stack Engineer', interviewType: 'Technical', subject: null, difficulty: 'Medium', interviewMode: 'STATIC', questionCount: 10, mode: 'Text', candidateProfile: { extracted_skills: ['Java', 'SQL', 'React', 'CSS', 'HTML', 'Git', 'DSA', 'OOP', 'Testing'] } };
function mount(overrides = {}) {
  let view;
  const cameraEvents = new Map();
  const camera = {
    videoWidth: 640, videoHeight: 480, srcObject: null,
    addEventListener(name, callback) { cameraEvents.set(name, callback); },
    removeEventListener(name) { cameraEvents.delete(name); },
  };
  const draw = { frames: 0, drawImage() { this.frames += 1; } };
  const calls = { started: 0, back: 0, changes: [] };
  function Harness() {
    const [setup, setSetup] = useState({ ...base, ...overrides });
    return <InterviewSetupConfig setup={setup} updateSetup={(patch) => { calls.changes.push(patch); setSetup((old) => ({ ...old, ...patch })); }} generatingQuestions={false} onStart={() => { calls.started += 1; }} onBack={() => { calls.back += 1; }} />;
  }
  act(() => { view = create(<Harness />, { createNodeMock: ({ type }) => {
    if (type === 'video') return camera;
    if (type === 'canvas') return { getContext: () => draw };
    return null;
  } }); });
  const buttons = () => view.root.findAllByType('button');
  const textContent = (item) => typeof item === 'string' ? item : (item.children || []).map(textContent).join('');
  const button = (text) => buttons().find((item) => textContent(item).includes(text));
  const group = (label) => view.root.findByProps({ role: 'radiogroup', 'aria-label': label });
  const radio = (label, index) => group(label).findAllByProps({ role: 'radio' })[index];
  return { view, calls, button, radio, group, camera, draw, cameraEvents, start: () => buttons().find((item) => item.props.children?.includes?.('Start Interview')) };
}
function mediaMock({ muted = false } = {}) {
  const tracks = [];
  const constraints = [];
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { permissions: {
    query() { assert.fail('Readiness should use the result of getUserMedia'); },
  }, mediaDevices: { getUserMedia: async (options) => {
    constraints.push(options);
    const kind = options.video ? 'video' : 'audio';
    const track = { kind, readyState: 'live', muted, stopped: false, stop() { this.stopped = true; this.readyState = 'ended'; } };
    tracks.push(track);
    return { getTracks: () => [track], getAudioTracks: () => kind === 'audio' ? [track] : [], getVideoTracks: () => kind === 'video' ? [track] : [] };
  } } } });
  return { tracks, constraints };
}

test('existing setup updates, radio keyboard navigation, summary, and start/back handlers', async () => {
  const ui = mount();
  act(() => ui.radio('Difficulty', 1).props.onKeyDown({ key: 'ArrowRight', preventDefault() {} }));
  assert.deepEqual(ui.calls.changes.at(-1), { difficulty: 'Hard' });
  assert.equal(ui.radio('Difficulty', 2).props['aria-checked'], true);
  act(() => ui.radio('Maximum questions', 2).props.onClick());
  assert.match(JSON.stringify(ui.view.toJSON()), /Static · 15 questions/);
  act(() => ui.radio('Interview style', 1).props.onClick());
  assert.equal(ui.view.root.findAll((node) => node.props.inert === '').length, 1);
  assert.match(JSON.stringify(ui.view.toJSON()), /Dynamic · 5–20 questions/);
  act(() => ui.radio('Interview type', 1).props.onClick());
  assert.deepEqual(ui.calls.changes.at(-1), { interviewType: 'HR', subject: null });
  assert.equal(ui.start().props.disabled, false);
  act(() => ui.start().props.onClick());
  act(() => ui.button('Back').props.onClick());
  assert.equal(ui.calls.started, 1);
  assert.equal(ui.calls.back, 1);
  act(() => ui.view.unmount());
});

test('combobox search commits original subject values; skills expand', () => {
  const ui = mount();
  act(() => ui.view.root.findByProps({ 'aria-haspopup': 'listbox' }).props.onClick());
  let input = ui.view.root.findByProps({ role: 'combobox' });
  act(() => input.props.onChange({ target: { value: 'database' } }));
  assert.equal(ui.view.root.findAllByProps({ role: 'option' }).length, 1);
  input = ui.view.root.findByProps({ role: 'combobox' });
  act(() => input.props.onKeyDown({ key: 'Enter', preventDefault() {} }));
  assert.deepEqual(ui.calls.changes.at(-1), { subject: 'DBMS and SQL' });
  act(() => ui.button('+3 more').props.onClick());
  assert.ok(ui.button('Show less'));
  act(() => ui.view.unmount());
});

test('temporarily muted live microphone is ready and released before interview starts', async () => {
  const { tracks, constraints } = mediaMock({ muted: true });
  const ui = mount({ mode: 'Voice' });
  assert.equal(ui.start().props.disabled, true);
  await act(async () => ui.button('Test devices').props.onClick());
  assert.deepEqual(constraints, [{ audio: true }]);
  assert.equal(ui.start().props.disabled, false);
  assert.equal(tracks[0].stopped, true);
  act(() => ui.start().props.onClick());
  assert.equal(ui.calls.started, 1);
  act(() => ui.radio('Answer mode', 2).props.onClick());
  assert.equal(ui.start().props.disabled, true);
  act(() => ui.radio('Answer mode', 0).props.onClick());
  assert.equal(ui.start().props.disabled, false);
  act(() => ui.view.unmount());
});

test('camera preview keeps one frame and releases both devices before start', async () => {
  const { tracks, constraints } = mediaMock();
  const ui = mount({ mode: 'Camera' });
  await act(async () => ui.button('Test devices').props.onClick());
  assert.deepEqual(constraints, [{ audio: true }, { video: true }]);
  assert.equal(tracks[0].stopped, true);
  assert.equal(tracks[1].stopped, false);
  assert.equal(ui.start().props.disabled, true);
  assert.ok(ui.camera.srcObject);
  act(() => ui.cameraEvents.get('loadeddata')());
  assert.equal(ui.start().props.disabled, false);
  assert.equal(ui.draw.frames, 1);
  assert.equal(ui.camera.srcObject, null);
  assert.ok(tracks.every((track) => track.stopped));
  assert.equal(ui.view.root.findByType('canvas').props.hidden, false);
  act(() => ui.view.unmount());
});

test('leaving during a camera preview releases its tracks before a frame arrives', async () => {
  const { tracks } = mediaMock();
  const ui = mount({ mode: 'Camera' });
  await act(async () => ui.button('Test devices').props.onClick());
  act(() => ui.view.unmount());
  assert.ok(tracks.every((track) => track.stopped));
  assert.equal(ui.camera.srcObject, null);
});

test('permission denial and device, hardware, and initialization failures have distinct states and allow retry', async () => {
  mediaMock();
  const ui = mount({ mode: 'Voice' });
  for (const [name, label] of [
    ['NotAllowedError', 'Permission denied'],
    ['NotFoundError', 'Unavailable'],
    ['OverconstrainedError', 'Unavailable'],
    ['NotReadableError', 'Device error'],
    ['AbortError', 'Initialization failed'],
    ['Error', 'Initialization failed'],
  ]) {
    navigator.mediaDevices.getUserMedia = async () => { throw Object.assign(new Error('internal message'), { name }); };
    await act(async () => ui.button('Test devices').props.onClick());
    assert.equal(ui.start().props.disabled, true);
    const output = JSON.stringify(ui.view.toJSON());
    assert.ok(output.includes(`"${label}"`), `Expected ${label} for ${name}`);
    assert.ok(!output.includes('internal message'));
  }
  mediaMock();
  await act(async () => ui.button('Test devices').props.onClick());
  assert.equal(ui.start().props.disabled, false);
  act(() => ui.view.unmount());
});

test('a resolved stream missing an audio track is an initialization failure and all tracks are stopped', async () => {
  const { tracks } = mediaMock();
  const getMedia = navigator.mediaDevices.getUserMedia;
  navigator.mediaDevices.getUserMedia = () => getMedia({ video: true });
  const ui = mount({ mode: 'Voice' });
  await act(async () => ui.button('Test devices').props.onClick());
  assert.match(JSON.stringify(ui.view.toJSON()), /Initialization failed/);
  assert.equal(ui.start().props.disabled, true);
  assert.equal(tracks[0].stopped, true);
  act(() => ui.view.unmount());
});

test('late permission responses after mode changes are discarded and stopped', async () => {
  const { tracks } = mediaMock();
  const getMedia = navigator.mediaDevices.getUserMedia;
  let resolve;
  navigator.mediaDevices.getUserMedia = () => new Promise((done) => { resolve = done; });
  const ui = mount({ mode: 'Voice' });
  let pending;
  act(() => { pending = ui.button('Test devices').props.onClick(); });
  act(() => ui.radio('Answer mode', 0).props.onClick());
  await act(async () => { resolve(await getMedia({ audio: true })); await pending; });
  assert.equal(tracks[0].stopped, true);
  assert.equal(ui.start().props.disabled, false);
  act(() => ui.view.unmount());
});
