/**
 * BrowserSpeechProvider — Phase 15.1
 *
 * Implements local-first text-to-speech using the browser's Web Speech API (window.speechSynthesis).
 * Strictly zero cloud / commercial API dependencies.
 *
 * Capabilities:
 * - Enumerates available browser voices across OS/platforms
 * - Handles asynchronous voiceschanged event
 * - Deterministic voice selection strategy (English, natural/clear masculine/professional voice preference)
 * - Safe utterance lifecycle (cancels stale queued utterances)
 * - Start / end / error callbacks
 * - Graceful fallback when SpeechSynthesis is unavailable
 */

import { timingSpan, timingEvent } from './performance.js';

class BrowserSpeechProvider {
  constructor() {
    this.voices = [];
    this.selectedVoice = null;
    this.isSupported = typeof window !== 'undefined' && 'speechSynthesis' in window;
    this.speaking = false;
    this.onSpeakingStateChange = null;
    this.initialized = false;
    this.initPromise = null;
  }

  /**
   * Initializes the speech provider, enumerating voices and setting up listeners.
   */
  async initialize() {
    if (!this.isSupported) {
      return false;
    }

    if (this.initialized && this.voices.length > 0) {
      return true;
    }

    if (this.initPromise) {
      return this.initPromise;
    }

    this.initPromise = new Promise((resolve) => {
      const loadVoices = () => {
        try {
          const rawVoices = window.speechSynthesis.getVoices() || [];
          if (rawVoices.length > 0) {
            this.voices = rawVoices;
            this.selectedVoice = this.pickBestVoice(rawVoices);
            this.initialized = true;
            resolve(true);
            return true;
          }
        } catch (err) {
          console.warn('[BrowserSpeechProvider] getVoices error:', err);
        }
        return false;
      };

      // Try immediate loading
      if (loadVoices()) return;

      // Handle async voiceschanged event
      const onVoicesChanged = () => {
        if (loadVoices()) {
          window.speechSynthesis.removeEventListener('voiceschanged', onVoicesChanged);
        }
      };

      window.speechSynthesis.addEventListener('voiceschanged', onVoicesChanged);

      // Timeout fallback (some browsers never fire voiceschanged)
      setTimeout(() => {
        if (!this.initialized) {
          loadVoices();
          this.initialized = true;
          resolve(this.voices.length > 0);
        }
      }, 1000);
    });

    return this.initPromise;
  }

  /**
   * Deterministic English voice selection strategy:
   * 1. English voices (lang starts with 'en')
   * 2. Prefer known suitable masculine/clear voices (e.g. David, Guy, George, Mark, Google US English, Natural)
   * 3. Prefer high-quality / local service English voice
   * 4. Best available English voice
   * 5. Browser default voice
   */
  pickBestVoice(voicesList) {
    if (!voicesList || voicesList.length === 0) return null;

    const englishVoices = voicesList.filter(v => v.lang && v.lang.toLowerCase().startsWith('en'));
    const candidateList = englishVoices.length > 0 ? englishVoices : voicesList;

    // Preferred keywords for clear/masculine/professional interviewer timbre
    const preferredNames = [
      'natural',
      'guy',
      'david',
      'george',
      'mark',
      'daniel',
      'ryan',
      'james',
      'andrew',
      'google us english',
      'english united states',
    ];

    // Priority 1: Preferred English voice name match
    for (const pref of preferredNames) {
      const match = candidateList.find(v => v.name && v.name.toLowerCase().includes(pref));
      if (match) return match;
    }

    // Priority 2: Local service English voice
    const localEnglish = candidateList.find(v => v.localService);
    if (localEnglish) return localEnglish;

    // Priority 3: Default English voice
    const defaultEnglish = candidateList.find(v => v.default);
    if (defaultEnglish) return defaultEnglish;

    // Priority 4: First available English voice
    if (candidateList.length > 0) return candidateList[0];

    // Fallback: Default system voice
    return voicesList.find(v => v.default) || voicesList[0];
  }

  getVoices() {
    return this.voices;
  }

  getCurrentVoice() {
    return this.selectedVoice;
  }

  setVoice(voiceOrName) {
    if (!voiceOrName) return;
    if (typeof voiceOrName === 'string') {
      const found = this.voices.find(v => v.name === voiceOrName || v.voiceURI === voiceOrName);
      if (found) this.selectedVoice = found;
    } else {
      this.selectedVoice = voiceOrName;
    }
  }

  isSpeaking() {
    if (!this.isSupported) return false;
    return window.speechSynthesis.speaking;
  }

  stop() {
    this._finishSpeechTiming?.();
    this._finishSpeechTiming = null;
    // Invalidate BEFORE cancel(): browsers can dispatch cancellation synchronously.
    this._request = null;
    this._activeUtterance = null;
    if (this.isSupported) window.speechSynthesis.cancel();
    this.speaking = false;
    this.onSpeakingStateChange?.(false);
  }

  speak(text, { onStart, onEnd, onError, rate = 0.95, pitch = 1 } = {}) {
    this.stop();
    if (!this.isSupported || !text?.trim()) {
      onError?.(new Error('Speech playback is unavailable or the question is empty.'));
      return;
    }
    const request = {};
    const finishSpeech = timingSpan('tts.request_to_terminal');
    this._finishSpeechTiming = () => { timingEvent('tts.cancel'); finishSpeech(); };
    this._request = request;
    const terminal = (error) => {
      if (this._request !== request) return;
      timingEvent(error ? 'tts.error' : 'tts.end');
      finishSpeech();
      this._finishSpeechTiming = null;
      this._request = null;
      this._activeUtterance = null;
      this.speaking = false;
      this.onSpeakingStateChange?.(false);
      if (error) onError?.(error); else onEnd?.();
    };
    try {
      const utterance = new SpeechSynthesisUtterance(text.trim());
      utterance.voice = this.selectedVoice;
      utterance.lang = this.selectedVoice?.lang || 'en-US';
      utterance.rate = rate;
      utterance.pitch = pitch;
      utterance.onstart = () => {
        if (this._request !== request) return;
        timingEvent('tts.start');
        this.speaking = true;
        this.onSpeakingStateChange?.(true);
        onStart?.();
      };
      utterance.onend = () => terminal();
      utterance.onerror = (event) => terminal(new Error(event.error || 'Speech playback failed'));
      this._activeUtterance = utterance;
      window.speechSynthesis.speak(utterance);
    } catch (error) { terminal(error); }
  }
}

export default BrowserSpeechProvider;
