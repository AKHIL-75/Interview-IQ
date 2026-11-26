import { useState } from 'react';
import { Mic, MicOff, Camera, CameraOff, Subtitles, RotateCcw, Check, Loader2, Volume2, VolumeX, X } from 'lucide-react';

export default function InterviewControlBar({
  mode = 'Voice', isRecording = false, isSpeaking = false, isProcessing = false,
  isCameraActive = true, isMicMuted = false, captionsEnabled = false, voiceEnabled = true,
  canDoneAnswer = false, canRecord = true, onToggleMic, onToggleCamera, onToggleCaptions,
  onToggleVoice, onRepeatQuestion, onDoneAnswering, onEndInterview, className = '',
  captionsAvailable = false, voiceSelector, disabled = false,
}) {
  const [voiceOpen, setVoiceOpen] = useState(false);
  const locked = disabled || isProcessing;
  const button = 'iiq-control w-12 h-12 shrink-0 rounded-md border flex items-center justify-center transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface ';
  const normal = ' border-line bg-surface text-heading hover:bg-subtle';
  const off = ' border-red-300 bg-danger-surface text-danger hover:bg-red-100';
  return (
    <div className={`iiq-controls fixed bottom-4 left-1/2 -translate-x-1/2 z-40 flex flex-wrap justify-center items-center gap-3 p-4 rounded-md bg-surface  border border-line  ${className}`}>
      <button aria-label={isMicMuted ? 'Unmute microphone' : 'Mute microphone'} aria-pressed={!isMicMuted}
        onClick={onToggleMic} disabled={locked || isSpeaking || !canRecord}
        title={isSpeaking ? 'Wait for the question to finish' : `${isMicMuted ? 'Unmute' : 'Mute'} microphone (M)`}
        className={button + (isMicMuted ? off : normal) + (isRecording ? ' ring-2 ring-primary' : '')}>
        {isMicMuted ? <MicOff size={20} /> : <Mic size={20} />}
      </button>
      <button aria-label={isCameraActive ? 'Turn camera off' : 'Turn camera on'} aria-pressed={isCameraActive}
        title={`Camera (V)`} onClick={onToggleCamera} disabled={disabled} className={button + (isCameraActive ? normal : off)}>
        {isCameraActive ? <Camera size={20} /> : <CameraOff size={20} />}
      </button>
      {captionsAvailable && <button aria-label="Captions" aria-pressed={captionsEnabled} title="Captions (C)" onClick={onToggleCaptions} disabled={disabled}
        className={button + (captionsEnabled ? ' border-primary bg-selected text-primary' : normal)}><Subtitles size={20} /></button>}
      <div className="h-7 w-px bg-subtle" aria-hidden="true" />
      <div className="relative">
        <button aria-label="Interviewer voice" aria-expanded={voiceOpen} aria-haspopup="dialog" title="Choose interviewer voice"
          onClick={() => setVoiceOpen(open => !open)} disabled={locked} className={button + normal}>
          {voiceEnabled ? <Volume2 size={20} /> : <VolumeX size={20} />}
        </button>
        {voiceOpen && <div role="dialog" aria-label="Interviewer voice options" className="iiq-voice-popover absolute bottom-16 w-72 rounded-lg border border-line bg-surface p-4 "
          onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); setVoiceOpen(false); event.currentTarget.parentElement?.querySelector('button')?.focus(); } }}>
          <div className="flex items-center justify-between text-sm text-heading"><span>Interviewer voice</span><button aria-label="Close voice options" className="iiq-focus min-h-11 min-w-11 flex items-center justify-center" onClick={() => setVoiceOpen(false)}><X size={18}/></button></div>
          {voiceSelector}
          <button className="iiq-focus mt-3 min-h-11 w-full rounded-lg border border-line text-sm text-heading" onClick={onToggleVoice}>{voiceEnabled ? 'Turn interviewer voice off' : 'Turn interviewer voice on'}</button>
        </div>}
      </div>
      <button aria-label="Repeat question" title="Repeat question (R)" onClick={onRepeatQuestion} disabled={locked || isSpeaking || !voiceEnabled} className={button + normal}><RotateCcw size={20} /></button>
      <button aria-label={isProcessing ? 'Processing answer' : 'Done Answering'} title={isSpeaking ? 'Wait for the question to finish' : 'Done Answering'}
        onClick={onDoneAnswering} disabled={locked || isSpeaking || !canDoneAnswer}
        className="iiq-done iiq-focus h-12 rounded-md px-5 flex items-center justify-center gap-2 bg-primary hover:bg-pressed text-white text-sm font-semibold transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed">
        <span className="hidden md:inline">{isProcessing ? 'Processing...' : 'Done Answering'}</span>
        {isProcessing ? <Loader2 size={20} className="animate-spin motion-reduce:animate-none"/> : <Check size={20}/>}
      </button>
    </div>
  );
}
