/**
 * Provider abstraction for interviewer questions. Azure credentials stay on the backend.
 */

import AzureSpeechProvider from './azureSpeechProvider';

class InterviewerVoiceService {
  constructor() {
    this.primaryProvider = new AzureSpeechProvider();
    this.activeProvider = this.primaryProvider;
    this.speakingListeners = new Set();

    this.activeProvider.onSpeakingStateChange = (isSpeaking) => {
      this.speakingListeners.forEach(listener => {
        try {
          listener(isSpeaking);
        } catch (err) {
          console.warn('[InterviewerVoiceService] Listener error:', err);
        }
      });
    };
  }

  /**
   * Initializes the active speech provider.
   */
  async initialize() {
    return this.activeProvider.initialize();
  }

  /**
   * Returns list of available voices.
   */
  getVoices() {
    return this.activeProvider.getVoices();
  }

  /**
   * Returns currently selected voice details.
   */
  getCurrentVoice() {
    return this.activeProvider.getCurrentVoice();
  }

  /**
   * Sets the active voice by object or name.
   */
  selectVoice(voiceOrName) {
    return this.activeProvider.setVoice(voiceOrName);
  }

  /**
   * Speaks given text via active provider.
   */
  speak(text, options = {}) {
    return this.activeProvider.speak(text, options);
  }

  /**
   * Stops/cancels current speech immediately.
   */
  stop() {
    this.activeProvider.stop();
  }

  clearCache() { this.activeProvider.clearCache(); }

  /**
   * Returns true if speech synthesis is currently active.
   */
  isSpeaking() {
    return this.activeProvider.isSpeaking();
  }

  /**
   * Subscribes to speaking state transitions (true = speaking, false = idle).
   */
  subscribeSpeakingState(listener) {
    this.speakingListeners.add(listener);
    return () => {
      this.speakingListeners.delete(listener);
    };
  }

  /**
   * Plays a quick test sample phrase to allow candidate to verify voice output in the lobby.
   */
  testVoice(customText = "Hello! I am your AI interviewer. I will be conducting your interview today.") {
    return new Promise((resolve, reject) => {
      this.speak(customText, {
        onEnd: () => resolve(true),
        onError: (err) => reject(err),
        onCancel: () => resolve(false),
      });
    });
  }
}

// Singleton instance
export const interviewerVoiceService = new InterviewerVoiceService();
export default interviewerVoiceService;
