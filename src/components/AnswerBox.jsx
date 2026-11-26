import { useState, useEffect, useRef, useCallback } from 'react';
import { Send, SkipForward, Mic, MicOff, Square, RotateCcw, Loader2, AlertTriangle } from 'lucide-react';
import Button from './Button';
import { transcribeAudio } from '../services/api';

/**
 * Detect the best supported audio MIME type for MediaRecorder.
 * Tries multiple formats in priority order and returns the first supported one.
 */
function getSupportedMimeType() {
  const types = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/ogg',
    'audio/mp4',
  ];
  for (const type of types) {
    if (typeof MediaRecorder !== 'undefined' && MediaRecorder.isTypeSupported(type)) {
      return type;
    }
  }
  return ''; // Empty string = let browser decide
}

/**
 * AnswerBox — Phase 15 Updated
 *
 * Supports three modes:
 * - Text: Traditional textarea (unchanged from Phase 8+)
 * - Voice: Real MediaRecorder + Azure Speech transcription → editable textarea
 * - Camera: Same as Voice (mic recording handled here, camera preview is separate)
 *
 * Voice flow:
 * 1. User clicks Start Recording → getUserMedia(audio) → MediaRecorder starts
 * 2. User clicks Stop Recording → audio blob assembled
 * 3. Audio blob sent to POST /api/v1/audio/transcribe → Azure Speech
 * 4. Transcript populates editable textarea
 * 5. User can edit/correct transcript
 * 6. User clicks Submit Answer → existing submitAnswer() pipeline
 *
 * Critical lifecycle rules:
 * - Every mic stream is cleaned up on stop/cancel/unmount/navigation
 * - No duplicate MediaRecorder instances
 * - No stale chunks/listeners
 * - Audio blob is NOT persisted
 */
export default function AnswerBox({
  onSubmit,
  onDraftChange,
  readOnly = false,
  onSkip,
  mode = 'Text',
  loading = false,
  submissionStage,
  initialAnswer = '',
  className = '',
}) {
  const [answer, setAnswer] = useState(initialAnswer || '');

  // Voice recording state
  const [recState, setRecState] = useState('idle');
  // idle | recording | stopping | transcribing | ready | error | unsupported
  const [recordingTime, setRecordingTime] = useState(0);
  const [transcriptionError, setTranscriptionError] = useState('');
  const [micPermission, setMicPermission] = useState('unknown');
  // unknown | requesting | granted | denied | unavailable

  // Refs for cleanup
  const mediaRecorderRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const audioChunksRef = useRef([]);
  const timerIntervalRef = useRef(null);
  const mimeTypeRef = useRef('');
  const mountedRef = useRef(true);

  // Track mount status for async safety
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Sync initialAnswer
  useEffect(() => {
    setAnswer(initialAnswer || '');
  }, [initialAnswer]);

  // Check browser support on mount
  useEffect(() => {
    if (mode === 'Voice' || mode === 'Camera') {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setRecState('unsupported');
        setMicPermission('unavailable');
      } else if (typeof MediaRecorder === 'undefined') {
        setRecState('unsupported');
        setMicPermission('unavailable');
      }
    }
  }, [mode]);

  // Reset recording state when question changes (detected via initialAnswer change)
  useEffect(() => {
    cleanupRecording();
    setRecState('idle');
    setRecordingTime(0);
    setTranscriptionError('');
    // Don't reset micPermission — keep it across questions
  }, [initialAnswer]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanupRecording();
    };
  }, []);

  /** Stop all tracks and clean up MediaRecorder resources */
  const cleanupRecording = useCallback(() => {
    // Stop timer
    if (timerIntervalRef.current) {
      clearInterval(timerIntervalRef.current);
      timerIntervalRef.current = null;
    }

    // Stop MediaRecorder
    if (mediaRecorderRef.current) {
      try {
        if (mediaRecorderRef.current.state !== 'inactive') {
          mediaRecorderRef.current.stop();
        }
      } catch {
        // Already stopped
      }
      mediaRecorderRef.current = null;
    }

    // Stop all tracks on the stream
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => {
        track.stop();
      });
      mediaStreamRef.current = null;
    }

    // Clear audio chunks
    audioChunksRef.current = [];
  }, []);

  /** Start recording */
  const startRecording = async () => {
    if (recState === 'recording' || recState === 'transcribing') return;

    // Clean up any previous recording
    cleanupRecording();
    setTranscriptionError('');
    setRecordingTime(0);

    // Check browser support
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setRecState('unsupported');
      setMicPermission('unavailable');
      return;
    }

    setMicPermission('requesting');

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          sampleRate: 16000,
        },
      });

      if (!mountedRef.current) {
        stream.getTracks().forEach(t => t.stop());
        return;
      }

      mediaStreamRef.current = stream;
      setMicPermission('granted');

      // Determine MIME type
      const mimeType = getSupportedMimeType();
      mimeTypeRef.current = mimeType;

      // Create MediaRecorder
      const options = mimeType ? { mimeType } : {};
      const recorder = new MediaRecorder(stream, options);
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      recorder.onstop = async () => {
        if (!mountedRef.current) return;

        // Stop mic tracks immediately when recording stops
        if (mediaStreamRef.current) {
          mediaStreamRef.current.getTracks().forEach(t => t.stop());
          mediaStreamRef.current = null;
        }

        // Stop timer
        if (timerIntervalRef.current) {
          clearInterval(timerIntervalRef.current);
          timerIntervalRef.current = null;
        }

        const chunks = audioChunksRef.current;
        if (chunks.length === 0) {
          setRecState('error');
          setTranscriptionError('No audio was captured. Please try again.');
          return;
        }

        const audioBlob = new Blob(chunks, {
          type: mimeTypeRef.current || 'audio/webm',
        });

        if (audioBlob.size === 0) {
          setRecState('error');
          setTranscriptionError('Recording produced empty audio. Please try again.');
          return;
        }

        // Send to backend for transcription
        setRecState('transcribing');

        try {
          const result = await transcribeAudio(audioBlob, mimeTypeRef.current || 'audio/webm');

          if (!mountedRef.current) return;

          if (result && result.success) {
            const transcript = result.text || '';
            if (transcript.trim()) {
              setAnswer(transcript);
              setRecState('ready');
              setTranscriptionError((result.warnings || []).join(' '));
            } else {
              setRecState('ready');
              setTranscriptionError('No speech detected. You can type your answer or try recording again.');
            }
          } else {
            setRecState('error');
            setTranscriptionError('Transcription returned no result. Please try again.');
          }
        } catch (err) {
          if (!mountedRef.current) return;
          console.error('[AnswerBox] Transcription failed:', err);
          setRecState('error');
          setTranscriptionError(
            err.message || 'Failed to transcribe audio. You can type your answer instead.'
          );
        }
      };

      recorder.onerror = (e) => {
        console.error('[AnswerBox] MediaRecorder error:', e);
        cleanupRecording();
        if (mountedRef.current) {
          setRecState('error');
          setTranscriptionError('Recording failed. Please try again.');
        }
      };

      // Start recording with 250ms timeslice for regular data chunks
      recorder.start(250);
      setRecState('recording');

      // Start timer
      let seconds = 0;
      timerIntervalRef.current = setInterval(() => {
        seconds += 1;
        if (mountedRef.current) {
          setRecordingTime(seconds);
        }
      }, 1000);

    } catch (err) {
      console.warn('[AnswerBox] Microphone access error:', err.name, err.message);

      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setMicPermission('denied');
        setRecState('idle');
        setTranscriptionError('Microphone permission denied. You can type your answer instead.');
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        setMicPermission('unavailable');
        setRecState('unsupported');
        setTranscriptionError('No microphone found. Please connect a microphone or use Text mode.');
      } else {
        setMicPermission('denied');
        setRecState('error');
        setTranscriptionError(`Microphone error: ${err.message}`);
      }
    }
  };

  /** Stop recording */
  const stopRecording = () => {
    if (recState !== 'recording') return;
    setRecState('stopping');

    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      mediaRecorderRef.current.stop(); // triggers onstop handler
    }
  };

  /** Cancel recording */
  const cancelRecording = () => {
    cleanupRecording();
    setRecState('idle');
    setRecordingTime(0);
    setTranscriptionError('');
  };

  /** Re-record (discard previous and start fresh) */
  const reRecord = () => {
    cleanupRecording();
    setRecState('idle');
    setRecordingTime(0);
    setAnswer('');
    setTranscriptionError('');
    // Immediately start new recording
    setTimeout(() => startRecording(), 100);
  };

  const handleSubmit = () => {
    const trimmed = answer.trim();
    if (!trimmed || loading) return;
    onSubmit?.(trimmed, recState === 'ready' ? 'speech' : 'text');
  };

  const formatTime = (seconds) => {
    const m = Math.floor(seconds / 60).toString().padStart(2, '0');
    const s = (seconds % 60).toString().padStart(2, '0');
    return `${m}:${s}`;
  };

  const isVoiceMode = mode === 'Voice' || mode === 'Camera';

  return (
    <div className={`${className}`}>
      {isVoiceMode ? (
        <div className="space-y-4">
          {/* Microphone unsupported / denied banner */}
          {(recState === 'unsupported' || micPermission === 'denied') && (
            <div className="glass-card p-4 border border-amber-300">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4 text-warning flex-shrink-0" />
                <span className="text-sm text-warning font-medium">
                  {recState === 'unsupported' ? 'Voice recording not available' : 'Microphone permission denied'}
                </span>
              </div>
              <p className="text-xs text-secondary">
                {recState === 'unsupported'
                  ? 'Your browser does not support audio recording. Please use Text mode.'
                  : 'Grant microphone permission in your browser settings, or type your answer below.'}
              </p>
            </div>
          )}

          {/* Recording controls */}
          {recState !== 'unsupported' && micPermission !== 'denied' && (
            <div className="glass-card p-6 text-center">
              {/* Idle / Ready to record */}
              {(recState === 'idle' || recState === 'error') && (
                <>
                  <button
                    onClick={startRecording}
                    disabled={loading}
                    className="w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-4 transition-all duration-300 bg-primary hover:bg-pressed   disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <Mic className="w-8 h-8 text-white" />
                  </button>
                  <p className="text-heading font-medium">
                    {micPermission === 'requesting' ? 'Requesting microphone...' : 'Click to start recording'}
                  </p>
                  {recState === 'error' && transcriptionError && (
                    <p className="text-xs text-warning mt-2">{transcriptionError}</p>
                  )}
                </>
              )}

              {/* Recording in progress */}
              {recState === 'recording' && (
                <>
                  <button
                    onClick={stopRecording}
                    className="w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-4 transition-all duration-300 bg-red-600   animate-pulse"
                  >
                    <Square className="w-6 h-6 text-white" />
                  </button>
                  <p className="text-heading font-medium">Recording...</p>
                  <p className="text-2xl tabular-nums text-primary mt-2">{formatTime(recordingTime)}</p>
                  <div className="flex justify-center gap-3 mt-4">
                    <button
                      onClick={stopRecording}
                      className="px-4 py-2 rounded-lg bg-subtle border border-line text-secondary text-sm hover:bg-subtle transition-all"
                    >
                      Stop & Transcribe
                    </button>
                    <button
                      onClick={cancelRecording}
                      className="px-4 py-2 rounded-lg text-secondary text-sm hover:text-secondary transition-all"
                    >
                      Cancel
                    </button>
                  </div>
                </>
              )}

              {/* Stopping / Transcribing */}
              {(recState === 'stopping' || recState === 'transcribing') && (
                <>
                  <div className="w-20 h-20 rounded-full flex items-center justify-center mx-auto mb-4 bg-selected border-2 border-primary">
                    <Loader2 className="w-8 h-8 text-primary animate-spin" />
                  </div>
                  <p className="text-heading font-medium">
                    {recState === 'stopping' ? 'Processing audio...' : 'Transcribing with Azure Speech...'}
                  </p>
                  <p className="text-xs text-secondary mt-1">This may take a few seconds</p>
                </>
              )}

              {/* Ready — Transcript available */}
              {recState === 'ready' && (
                <div className="text-left">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-success font-medium flex items-center gap-1">
                      <Mic className="w-3 h-3" />
                      Transcription complete
                    </span>
                    <button
                      onClick={reRecord}
                      disabled={loading}
                      className="inline-flex items-center gap-1.5 text-xs text-secondary hover:text-primary transition-colors disabled:opacity-50"
                    >
                      <RotateCcw className="w-3 h-3" />
                      Re-record
                    </button>
                  </div>
                  {transcriptionError && (
                    <p className="text-xs text-warning mb-2">{transcriptionError}</p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Editable transcript / text fallback */}
          {(recState === 'ready' || recState === 'unsupported' || micPermission === 'denied' || recState === 'error') && (
            <div>
              <textarea aria-label="Your answer"
                value={answer}
                onChange={(e) => { setAnswer(e.target.value); onDraftChange?.(e.target.value); }}
        readOnly={readOnly}
                placeholder={
                  recState === 'ready'
                    ? 'Edit your transcribed answer here...'
                    : 'Type your answer here...'
                }
                className="input-field min-h-[200px] resize-y font-normal leading-relaxed"
                disabled={loading}
              />
              <div className="flex items-center justify-between mt-1">
                <span className="text-xs text-secondary">{answer.length} characters</span>
                {recState === 'ready' && (
                  <span className="text-xs text-secondary">You can edit the transcript before submitting</span>
                )}
              </div>
            </div>
          )}
        </div>
      ) : (
        /* Text Mode — unchanged */
        <div>
          <textarea aria-label="Your answer"
            value={answer}
            onChange={(e) => { setAnswer(e.target.value); onDraftChange?.(e.target.value); }}
        readOnly={readOnly}
            placeholder="Type your answer here..."
            className="input-field min-h-[200px] resize-y font-normal leading-relaxed"
            disabled={loading}
          />
          <div className="flex items-center justify-between mt-1">
            <span className="text-xs text-secondary">{answer.length} characters</span>
          </div>
        </div>
      )}

      <div className="flex gap-3 mt-4">
        <Button
          variant="primary"
          icon={Send}
          onClick={handleSubmit}
          loading={loading}
          disabled={!answer.trim() || loading}
          className="flex-1"
        >
          {submissionStage || 'Submit Answer'}
        </Button>
        <Button variant="secondary" icon={SkipForward} onClick={onSkip} disabled={loading}>
          Skip
        </Button>
      </div>
    </div>
  );
}
