import { Sparkles, Mic, Loader2, Volume2, Bot } from 'lucide-react';

/**
 * InterviewerAvatar — Phase 15.1
 *
 * Clean, professional illustrated avatar for the AI Interviewer.
 * Deterministic CSS / SVG animation driven strictly by actual interview state:
 * - IDLE: Calm, ambient breathing orb
 * - SPEAKING: Dynamic audio waveform & pulse synced with TTS
 * - LISTENING: Focused listening wave indicator when candidate is speaking
 * - PROCESSING: Subtle glowing rotation during Azure Speech transcription / evaluation
 * - TRANSITIONING: Smooth conversational acknowledgement wave
 *
 * Privacy Guarantees:
 * - NO photorealistic face synthesis
 * - ZERO facial analysis, eye-tracking, or emotion inference
 */
export default function InterviewerAvatar({
  state = 'IDLE', // 'IDLE' | 'SPEAKING' | 'LISTENING' | 'PROCESSING' | 'TRANSITIONING'
  role = 'Interviewer',
  compact = false,
  className = '',
}) {
  const getStatusText = () => {
    switch (state) {
      case 'SPEAKING':
        return 'Speaking...';
      case 'LISTENING':
        return 'Listening to you...';
      case 'PROCESSING':
        return 'Analyzing response...';
      case 'TRANSITIONING':
        return 'Moving to next topic...';
      case 'ERROR':
        return 'Action needed';
      case 'IDLE':
      default:
        return 'Ready';
    }
  };

  const getStatusBadge = () => {
    switch (state) {
      case 'SPEAKING':
        return (
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-selected border border-primary text-primary text-xs font-medium animate-pulse">
            <Volume2 className="w-3.5 h-3.5" />
            <span>Speaking</span>
          </div>
        );
      case 'LISTENING':
        return (
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-success-surface border border-emerald-300 text-success text-xs font-medium animate-pulse">
            <Mic className="w-3.5 h-3.5" />
            <span>Listening</span>
          </div>
        );
      case 'PROCESSING':
        return (
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-purple-50 border border-purple-300 text-purple-800 text-xs font-medium">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            <span>Processing</span>
          </div>
        );
      case 'TRANSITIONING':
        return (
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-blue-50 border border-blue-300 text-blue-800 text-xs font-medium">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Transitioning</span>
          </div>
        );
      case 'IDLE':
      default:
        return (
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-subtle border border-line text-secondary text-xs font-medium">
            <div className="w-2 h-2 rounded-full bg-surface" />
            <span>Idle</span>
          </div>
        );
    }
  };

  return (
    <div className={`flex flex-col items-center justify-center select-none ${compact ? 'p-2' : 'p-8'} ${className}`}>
      {/* Outer ambient glow ring */}
      <div className="relative flex items-center justify-center">
        {/* Glow effect based on state */}
        <div aria-hidden="true" className="hidden" />

        {/* Dynamic Waveform Ring for SPEAKING */}
        {state === 'SPEAKING' && (
          <div className="absolute inset-0 -m-3 md:-m-6 rounded-full border-2 border-primary animate-ping opacity-30" />
        )}

        {/* Dynamic Waveform Ring for LISTENING */}
        {state === 'LISTENING' && (
          <div className="absolute inset-0 -m-2 md:-m-4 rounded-full border border-emerald-300 animate-pulse" />
        )}

        {/* Avatar Core Orb */}
        <div
          className={`relative rounded-full flex flex-col items-center justify-center  transition-all duration-500 border ${
            compact ? 'w-20 h-20 md:w-24 md:h-24' : 'w-40 h-40 md:w-48 md:h-48'
          } ${
            state === 'SPEAKING'
              ? '    border-primary '
              : state === 'LISTENING'
              ? '    border-emerald-300 '
              : state === 'PROCESSING'
              ? '    border-purple-300 '
              : '    border-line '
          }`}
        >
          {/* Illustrated AI Core Icon */}
          <div
            className={`rounded-lg bg-subtle border border-line flex items-center justify-center  ${
              compact ? 'w-10 h-10 mb-1 rounded-lg' : 'w-16 h-16 md:w-20 md:h-20 mb-2'
            }`}
          >
            <Bot
              className={`transition-all duration-300 ${
                compact ? 'w-5 h-5' : 'w-9 h-9 md:w-11 md:h-11'
              } ${
                state === 'SPEAKING'
                  ? 'text-primary scale-110'
                  : state === 'LISTENING'
                  ? 'text-success scale-105'
                  : state === 'PROCESSING'
                  ? 'text-purple-800 rotate-12'
                  : 'text-secondary'
              }`}
            />
          </div>

          {/* Sound wave bars inside avatar when speaking */}
          {state === 'SPEAKING' && (
            <div className="flex items-center gap-0.5 md:gap-1 mt-0.5">
              <div className="w-0.5 md:w-1 h-2 md:h-3 bg-primary rounded-full animate-bounce [animation-delay:0ms]" />
              <div className="w-0.5 md:w-1 h-3 md:h-5 bg-primary rounded-full animate-bounce [animation-delay:150ms]" />
              <div className="w-0.5 md:w-1 h-2.5 md:h-4 bg-primary rounded-full animate-bounce [animation-delay:75ms]" />
              <div className="w-0.5 md:w-1 h-3.5 md:h-6 bg-primary rounded-full animate-bounce [animation-delay:225ms]" />
              <div className="w-0.5 md:w-1 h-2 md:h-3 bg-primary rounded-full animate-bounce [animation-delay:300ms]" />
            </div>
          )}

          {/* Listening pulse line when candidate is answering */}
          {state === 'LISTENING' && (
            <div className="flex items-center gap-1 mt-0.5">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-600 animate-ping" />
              <span className="text-xs md:text-xs text-success tabular-nums  uppercase">
                {compact ? 'MIC' : 'RECEIVING'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Name and State Status */}
      <div className={`${compact ? 'mt-2' : 'mt-6'} text-center`}>
        <h3 className={`${compact ? 'text-xs' : 'text-base'} font-semibold text-heading tracking-wide`}>
          {role}
        </h3>
        <div className={`${compact ? 'mt-1 scale-90' : 'mt-2'} flex justify-center`}>
          {getStatusBadge()}
        </div>
      </div>
    </div>
  );
}
