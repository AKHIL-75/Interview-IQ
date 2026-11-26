export const AZURE_VOICES = Object.freeze([
  { name: 'en-IN-NeerjaNeural', displayName: 'Neerja', lang: 'en-IN', language: 'English (India)', gender: 'Female' },
  { name: 'en-IN-PrabhatNeural', displayName: 'Prabhat', lang: 'en-IN', language: 'English (India)', gender: 'Male' },
  { name: 'en-IN-AaravNeural', displayName: 'Aarav', lang: 'en-IN', language: 'English (India)', gender: 'Male' },
  { name: 'en-US-JennyNeural', displayName: 'Jenny', lang: 'en-US', language: 'English (United States)', gender: 'Female' },
  { name: 'en-US-BrianNeural', displayName: 'Brian', lang: 'en-US', language: 'English (United States)', gender: 'Male' },
].map(voice => Object.freeze({ ...voice, localService: false })));

// Preserve the application's established default for existing users and requests.
export const DEFAULT_AZURE_VOICE = 'en-US-JennyNeural';
export const VOICE_STORAGE_KEY = 'iiq_interviewer_voice';
export const VOICE_PREVIEW_TEXT = 'Hello, welcome to your Interview-IQ mock interview.';

export function getAzureVoice(name) {
  return AZURE_VOICES.find(voice => voice.name === name);
}

export function restoreAzureVoice() {
  try {
    const stored = getAzureVoice(localStorage.getItem(VOICE_STORAGE_KEY));
    if (stored) return stored;
  } catch { /* Storage is optional; keep voice selection usable. */ }
  return getAzureVoice(DEFAULT_AZURE_VOICE);
}
