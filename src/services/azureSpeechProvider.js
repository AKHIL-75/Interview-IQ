import { timingEvent, timingSpan } from './performance.js';
import apiClient from './client';
import { AZURE_VOICES, getAzureVoice, restoreAzureVoice, VOICE_STORAGE_KEY } from './azureVoices';

/** Audio through the authenticated backend. Bounded, voice-aware in-memory replay cache. */
export default class AzureSpeechProvider {
  constructor({ synthesize, createAudio, urls } = {}) {
    this.synthesize = synthesize || ((text, signal, voice) => apiClient.postBlob('/speech/synthesize', { text, voice }, { signal }));
    this.createAudio = createAudio || (url => new Audio(url));
    this.urls = urls || URL;
    this.active = null;
    this.cache = new Map();
    this.voice = restoreAzureVoice();
    this.onSpeakingStateChange = null;
  }

  async initialize() { return typeof Audio !== 'undefined'; }
  getVoices() { return AZURE_VOICES; }
  getCurrentVoice() { return this.voice; }
  setVoice(voiceOrName) {
    const voice = getAzureVoice(typeof voiceOrName === 'string' ? voiceOrName : voiceOrName?.name);
    if (!voice) return false;
    if (voice.name !== this.voice.name) {
      this.stop(); // Invalidate in-flight synthesis and release currently playing audio.
      this.voice = voice;
    }
    try { localStorage.setItem(VOICE_STORAGE_KEY, voice.name); } catch { /* Optional preference. */ }
    return true;
  }
  isSpeaking() { return Boolean(this.active); }

  release(request) {
    clearTimeout(request.timer);
    request.controller.abort();
    if (request.audio) {
      request.audio.onplaying = request.audio.onended = request.audio.onerror = null;
      request.audio.pause();
      request.audio.removeAttribute('src');
      request.audio.load();
    }
    if (request.url) this.urls.revokeObjectURL(request.url);
  }

  stop() {
    const previous = this.active;
    this.active = null; // Invalidate callbacks before abort/pause can fire events.
    if (previous) {
      this.release(previous);
      previous.options.onCancel?.();
    }
    this.onSpeakingStateChange?.(false);
  }

  clearCache() { this.cache.clear(); }

  async speak(text, options = {}) {
    text = text?.trim();
    const voice = this.voice.name;
    // Voice and text are the only variable synthesis parameters; format is fixed server-side.
    const key = JSON.stringify([voice, text]);
    if (this.active?.key === key) return; // Ignore duplicate requests during fetch/play.
    this.stop();
    if (!text) { options.onError?.(new Error('Question audio is unavailable.')); return; }
    const request = { key, text, voice, options, controller: new AbortController() };
    this.active = request;
    this.onSpeakingStateChange?.(true);
    const finish = error => {
      if (this.active !== request) return;
      this.active = null;
      this.release(request);
      this.onSpeakingStateChange?.(false);
      if (error) options.onError?.(new Error('Question audio is unavailable.'));
      else options.onEnd?.();
    };
    // Includes fetch, autoplay stalls, and missing terminal media events.
    request.timer = setTimeout(() => finish(true), 180000);
    try {
      let blob = this.cache.get(key);
      if (!blob) {
        const endFetch = timingSpan('tts.synthesis_request');
        try {
          blob = await this.synthesize(text, request.controller.signal, voice);
        } finally {
          endFetch();
        }
      }
      if (this.active !== request) return;
      if (!blob?.size) throw new Error('Empty audio');
      this.cache.delete(key);
      this.cache.set(key, blob);
      if (this.cache.size > 8) this.cache.delete(this.cache.keys().next().value);
      request.url = this.urls.createObjectURL(blob);
      request.audio = this.createAudio(request.url);
      request.audio.onplaying = () => {
        if (this.active === request && !request.started) {
          request.started = true;
          timingEvent('tts.playing');
          options.onStart?.();
        }
      };
      request.audio.onended = () => finish();
      request.audio.onerror = () => finish(true);
      await request.audio.play();
    } catch { finish(true); }
  }
}
