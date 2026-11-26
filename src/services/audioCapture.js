import { timingEvent } from './performance.js';
/** Owns one transient recording. Cancel never transcribes; finish settles once. */
export class AudioCapture {
  constructor() { this.epoch = 0; this.recorder = null; this.stream = null; this.pending = null; }
  async start(onSilence) {
    this.cancel();
    const epoch = this.epoch;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') throw new Error('Recording is unsupported. Please type your answer.');
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    if (epoch !== this.epoch) { stream.getTracks().forEach(t => t.stop()); return null; }
    this.stream = stream;
    try {
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'].find(t => MediaRecorder.isTypeSupported(t));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
      this.recorder = recorder;
      const chunks = [];
      this.pending = new Promise((resolve, reject) => {
        this.reject = reject;
        recorder.ondataavailable = e => { if (e.data?.size) chunks.push(e.data); };
        recorder.onerror = () => { this.release(); reject(new Error('Recording failed. Please retry or type your answer.')); };
        recorder.onstop = () => {
          timingEvent('recording.stop_event');
          this.release();
          const blob = new Blob(chunks, { type: recorder.mimeType || mimeType || 'audio/webm' });
          timingEvent('recording.blob_ready', { bytes: blob.size });
          if (blob.size) resolve(blob); else reject(new Error('No audio captured. Please retry or type your answer.'));
        };
      });
      this.pending.catch(() => {}); // cancellation may precede the consumer's finish()
      recorder.start(250);
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx && onSilence) {
        try {
          this.audio = new AudioCtx();
          this.source = this.audio.createMediaStreamSource(stream);
          this.analyser = this.audio.createAnalyser();
          this.analyser.fftSize = 256;
          this.source.connect(this.analyser);
          const values = new Uint8Array(this.analyser.frequencyBinCount);
          let spoken = false, quietSince = null;
          const sample = () => {
            if (epoch !== this.epoch || recorder.state !== 'recording') return;
            this.analyser.getByteFrequencyData(values);
            const average = values.reduce((a, b) => a + b, 0) / values.length;
            if (average > 15) { spoken = true; quietSince = null; }
            else if (spoken) {
              quietSince ??= Date.now();
              if (Date.now() - quietSince > 3500) { onSilence(); return; }
            }
            this.frame = requestAnimationFrame(sample);
          };
          sample();
        } catch { /* Manual Done remains available when Web Audio is unavailable. */ }
      }
      return stream;
    } catch (error) { this.cancel(); throw error; }
  }
  release() {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.source?.disconnect();
    this.analyser?.disconnect();
    this.audio?.close().catch(() => {});
    this.audio = this.source = this.analyser = null;
    this.stream?.getTracks().forEach(t => t.stop());
    this.stream = null;
  }
  finish() {
    if (!this.pending) return Promise.reject(new Error('No recording to finish.'));
    if (this.recorder?.state === 'recording') { timingEvent('recording.stop_requested'); this.recorder.stop(); }
    return this.pending;
  }
  cancel() {
    this.epoch++;
    if (this.recorder) {
      this.recorder.onstop = this.recorder.ondataavailable = this.recorder.onerror = null;
      if (this.recorder.state !== 'inactive') this.recorder.stop();
    }
    this.reject?.(new Error('Recording canceled'));
    this.reject = null;
    this.recorder = null;
    this.pending = null;
    this.release();
  }
}
