import { useEffect, useId, useRef, useState } from 'react';
import { CheckCircle, Loader2, Volume2 } from 'lucide-react';
import interviewerVoiceService from '../services/interviewerVoiceService';
import { AZURE_VOICES, DEFAULT_AZURE_VOICE, VOICE_PREVIEW_TEXT } from '../services/azureVoices';

export default function InterviewerVoiceSelector({ compact = false, disabled = false, onVoiceChange }) {
  const id = useId();
  const [selected, setSelected] = useState(() => interviewerVoiceService.getCurrentVoice()?.name || DEFAULT_AZURE_VOICE);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState('');
  const previewRef = useRef(null);

  useEffect(() => () => {
    const hadPreview = previewRef.current;
    previewRef.current = null;
    if (hadPreview) interviewerVoiceService.stop();
  }, []);

  const select = name => {
    interviewerVoiceService.selectVoice(name);
    setSelected(name);
    setError('');
    onVoiceChange?.(AZURE_VOICES.find(voice => voice.name === name));
  };

  const playPreview = name => {
    if (previewRef.current?.name === name) return;
    select(name);
    const request = { name, state: 'loading' };
    previewRef.current = request;
    setPreview(request);
    const finish = failed => {
      if (previewRef.current !== request) return;
      previewRef.current = null;
      setPreview(null);
      if (failed) setError('Voice preview is unavailable. Please try again. You can still join and read the questions.');
    };
    interviewerVoiceService.speak(VOICE_PREVIEW_TEXT, {
      onStart: () => {
        if (previewRef.current === request) setPreview({ name, state: 'playing' });
      },
      onEnd: () => finish(false),
      onCancel: () => finish(false),
      onError: () => finish(true),
    });
  };

  if (compact) return (
    <div className="w-full mt-2 text-left">
      <label htmlFor={id} className="block text-xs text-secondary mb-1">Interviewer voice</label>
      <select id={id} value={selected} disabled={disabled} onChange={event => select(event.target.value)}
        className="w-full min-w-0 rounded-lg bg-surface border border-line min-h-11 px-3 text-sm text-heading focus:border-primary disabled:opacity-50">
        {AZURE_VOICES.map(voice => <option key={voice.name} value={voice.name}>
          {voice.displayName} · {voice.lang} · {voice.gender}
        </option>)}
      </select>
    </div>
  );

  return (
    <fieldset className="space-y-2" disabled={disabled}>
      <legend className="text-xs text-secondary mb-2">Choose your interviewer voice · Azure Neural</legend>
      {AZURE_VOICES.map(voice => {
        const active = selected === voice.name;
        const busy = preview?.name === voice.name;
        return (
          <div key={voice.name} className={`flex items-center gap-2 p-3 rounded-lg border transition-colors ${active ? 'bg-selected border-primary' : 'bg-subtle border-line'}`}>
            <label className="flex flex-1 min-w-0 items-center gap-2 cursor-pointer">
              <input type="radio" name={id} value={voice.name} checked={active} onChange={() => select(voice.name)}
                className="accent-primary shrink-0" />
              <span className="min-w-0">
                <span className="text-sm font-semibold text-heading flex items-center gap-2">
                  {voice.displayName}{active && <CheckCircle className="w-3.5 h-3.5 text-primary" aria-label="Selected" />}
                </span>
                <span className="block text-xs text-secondary">{voice.language} · {voice.lang} · {voice.gender}</span>
              </span>
            </label>
            <button type="button" onClick={() => playPreview(voice.name)} disabled={busy}
              aria-label={`Preview ${voice.displayName}`} aria-busy={busy}
              className="shrink-0 flex items-center gap-1 rounded-lg p-2 text-xs text-primary bg-selected hover:bg-subtle min-h-11 focus-visible:outline focus-visible:outline-primary disabled:opacity-60">
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Volume2 className="w-3.5 h-3.5" />}
              <span>{busy ? (preview.state === 'loading' ? 'Loading…' : 'Playing…') : 'Preview'}</span>
            </button>
          </div>
        );
      })}
      <p role="status" aria-live="polite" className={`text-xs ${error ? 'text-warning' : 'text-secondary'}`}>
        {error || (preview ? (preview.state === 'loading' ? 'Generating voice preview…' : 'Playing voice preview…') : 'Your choice is saved in this browser. Preview also selects the voice.')}
      </p>
    </fieldset>
  );
}
