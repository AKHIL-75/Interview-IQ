import apiClient from './client';
import { timingSpan, timingEvent } from './performance';

const sdkImport = () => {
  const done = timingSpan('captions.sdk_import');
  return import('microsoft-cognitiveservices-speech-sdk').finally(done);
};
export async function getCaptionConfig(signal) {
  const done = timingSpan('captions.config');
  try {
    const config = await apiClient.get('/speech/stt-config', { signal, timeoutMs: 10000 });
    return config?.enabled === true && typeof config.language === 'string' && config.language ? config : { enabled: false };
  } finally { done(); }
}

// A session-owned destination stays live across recorder streams. SDK 1.52's
// PcmRecorder(false) releases its input nodes, not supplied MediaStream tracks.
// Only this tap owns/stops destination tracks; recorder tracks are never changed.
export class LiveCaptionSession {
  constructor({ recognizerRef, onConfig, onInterim, onFinal, onError }) {
    Object.assign(this, { recognizerRef, onConfig, onInterim, onFinal, onError });
    this.abort = new AbortController();
    this.turn = 0;
    this.stopPending = Promise.resolve();
  }
  async token() {
    const done = timingSpan('captions.token');
    try {
      const value = await apiClient.post('/speech/stt-token', {}, { signal: this.abort.signal, timeoutMs: 15000 });
      if (!value?.token || !value.region || !(value.expires_in_s > 0)) throw new Error('Captions unavailable');
      return value;
    } finally { done(); }
  }
  prepare() {
    if (this.preparing) return this.preparing;
    this.preparing = this.initialize().catch(() => {
      if (!this.recognizer) {
        this.destination?.stream.getTracks().forEach(track => track.stop());
        this.context?.close().catch(() => {});
        this.context = this.destination = null;
      }
      if (!this.closed) this.fail();
    });
    return this.preparing;
  }
  async initialize() {
    // Import overlaps config; token is requested only after enabled is confirmed.
    const modulePromise = sdkImport().then(module => module.default || module);
    modulePromise.catch(() => {});
    // A failed request is recoverable through prepare()'s error/Retry path.
    // Only an explicit disabled response should disable captions silently.
    const config = await getCaptionConfig(this.abort.signal);
    if (this.closed) return;
    this.config = config;
    this.onConfig(config);
    if (!config.enabled) return;
    const [sdk, authorization] = await Promise.all([modulePromise, this.token()]);
    if (this.closed) return;
    sdk.SpeechRecognizer.enableTelemetry(false);
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    this.context = new AudioContext();
    this.destination = this.context.createMediaStreamDestination();
    let speech;
    if (config.endpoint) {
      const endpoint = new URL(config.endpoint);
      endpoint.pathname = '/stt/speech/recognition/conversation/cognitiveservices/v1'; endpoint.search = '';
      speech = sdk.SpeechConfig.fromEndpoint(endpoint);
      speech.authorizationToken = authorization.token;
    } else speech = sdk.SpeechConfig.fromAuthorizationToken(authorization.token, authorization.region);
    speech.speechRecognitionLanguage = config.language;
    this.audio = sdk.AudioConfig.fromStreamInput(this.destination.stream);
    const done = timingSpan('captions.recognizer_creation');
    this.recognizer = new sdk.SpeechRecognizer(speech, this.audio);
    this.recognizerRef.current = this.recognizer;
    done();
    this.sdk = sdk;
    this.connection = sdk.Connection.fromRecognizer(this.recognizer);
    const connected = timingSpan('captions.connection_open');
    this.connection.connected = () => { if (!this.closed) connected(); };
    // Pre-opening is optional; failed pre-open is retried by the SDK at start.
    this.connection.openConnection(() => {}, () => {});
    this.scheduleRefresh(authorization.expires_in_s);
  }
  scheduleRefresh(expires) {
    clearTimeout(this.refreshTimer);
    this.refreshTimer = setTimeout(async () => {
      try {
        const authorization = await this.token();
        if (this.closed) return;
        this.recognizer.authorizationToken = authorization.token;
        this.scheduleRefresh(authorization.expires_in_s);
      } catch { if (!this.closed) this.fail(); }
    }, Math.min(480000, expires * 800));
  }
  fail() {
    this.stop();
    this.failed = true;
    this.onError();
  }
  async retry() {
    if (this.closed) return;
    this.failed = false;
    if (!this.recognizer) {
      this.preparing = null;
      await this.prepare();
    } else {
      try {
        const authorization = await this.token();
        if (this.closed) return;
        this.recognizer.authorizationToken = authorization.token;
        this.scheduleRefresh(authorization.expires_in_s);
      } catch { this.fail(); return; }
    }
  }
  async start(stream, questionId, attempt) {
    const turn = ++this.turn;
    const firstInterim = timingSpan('captions.active_to_first_interim');
    await this.prepare();
    await this.stopPending;
    const current = () => !this.closed && turn === this.turn;
    if (!current() || !this.recognizer || this.failed) return;
    try {
      await this.context.resume();
      if (!current()) return;
      this.source = this.context.createMediaStreamSource(stream);
      this.source.connect(this.destination);
      this.running = true;
      const recognizer = this.recognizer;
      const gate = this.resultGate = { open: true };
      recognizer.recognizing = (_, event) => {
        if (!current() || !this.running) return;
        firstInterim();
        this.pendingInterim = event.result.text || '';
        if (!this.interimTimer) this.interimTimer = setTimeout(() => {
          this.interimTimer = null;
          if (current() && this.running) this.onInterim(questionId, this.pendingInterim, attempt);
        }, 100);
      };
      // Keep this question's final handler until stop completes, so a late final
      // is saved to the old question, never to the next candidate turn.
      recognizer.recognized = (_, event) => {
        if (this.closed || !gate.open || event.result.reason !== this.sdk.ResultReason.RecognizedSpeech) return;
        clearTimeout(this.interimTimer); this.interimTimer = null;
        this.onInterim(questionId, '', attempt);
        if (event.result.text?.trim()) {
          timingEvent('transcript.azure_final', { attempt });
          this.onFinal(questionId, event.result.text.trim(), attempt);
        }
      };
      recognizer.canceled = (_, event) => {
        if (current() && this.running && event.reason === this.sdk.CancellationReason.Error) this.fail();
      };
      recognizer.sessionStopped = () => { if (current() && this.running) this.fail(); };
      recognizer.startContinuousRecognitionAsync(() => {}, () => { if (current()) this.fail(); });
    } catch { if (current()) this.fail(); }
  }
  stop() {
    ++this.turn;
    clearTimeout(this.interimTimer); this.interimTimer = null;
    this.source?.disconnect(); this.source = null;
    if (!this.running) return;
    this.running = false;
    const gate = this.resultGate;
    this.stopPending = new Promise(resolve => {
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true; gate.open = false; clearTimeout(timer);
        if (this.finishDrain === done) this.finishDrain = null;
        resolve();
      };
      const timer = setTimeout(done, 10000);
      this.finishDrain = done;
      try { this.recognizer.stopContinuousRecognitionAsync(done, done); } catch { done(); }
    });
  }
  async finish() {
    this.stop();
    await this.stopPending;
  }
  dispose() {
    if (this.closed) return;
    this.stop(); this.closed = true;
    this.abort.abort(); clearTimeout(this.refreshTimer); this.finishDrain?.();
    if (this.recognizer) {
      this.recognizer.recognizing = this.recognizer.recognized = this.recognizer.canceled = this.recognizer.sessionStopped = undefined;
      if (this.connection) this.connection.connected = this.connection.disconnected = undefined;
      try { this.connection?.closeConnection(() => {}, () => {}); this.connection?.close(); } catch { /* Already closed. */ }
      try { this.recognizer.close(() => {}, () => {}); } catch { /* Already closed. */ }
    }
    this.recognizerRef.current = null;
    try { this.audio?.close(); } catch { /* Already closed. */ }
    this.destination?.stream.getTracks().forEach(track => track.stop());
    this.context?.close().catch(() => {});
  }
}
