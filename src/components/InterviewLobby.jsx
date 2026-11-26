import { useState, useEffect } from 'react';
import {
  Mic,
  Camera,
  Volume2,
  CheckCircle,
  AlertCircle,
  Sparkles,
  ShieldCheck,
  ArrowRight,
} from 'lucide-react';
import CameraPreview from './CameraPreview';
import MicLevelMeter from './MicLevelMeter';
import InterviewerVoiceSelector from './InterviewerVoiceSelector';
import interviewerVoiceService from '../services/interviewerVoiceService';

/**
 * InterviewLobby — Phase 15.1
 *
 * Preflight readiness lobby for Voice and Camera interview modes.
 * - Displays interview title and target role
 * - Camera preview verification (Camera mode)
 * - Microphone test and real-time activity meter
 * - Interviewer voice selection info and test voice button
 * - "Join Interview" button providing the required explicit user interaction
 *   to unlock audio playback and initialize stage media safely.
 */
export default function InterviewLobby({
  role = 'Software Engineer',
  interviewType = 'Technical',
  difficulty = 'Medium',
  mode = 'Voice', // 'Voice' | 'Camera'
  onJoinInterview,
}) {
  const [micStream, setMicStream] = useState(null);
  const [micStatus, setMicStatus] = useState('requesting'); // requesting | granted | denied | unavailable
  const [cameraPermission, setCameraPermission] = useState('unknown');
  const [joining, setJoining] = useState(false);

  // Test microphone on lobby mount; voice previews are requested only on click.
  useEffect(() => {
    let active = true;
    let previewStream = null;

    // Request transient microphone access to verify levels
    if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
      navigator.mediaDevices
        .getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        })
        .then((stream) => {
          if (!active) {
            stream.getTracks().forEach((t) => t.stop());
            return;
          }
          previewStream = stream;
          setMicStream(stream);
          setMicStatus('granted');
        })
        .catch((err) => {
          if (!active) return;
          console.warn('[InterviewLobby] Mic access error:', err);
          if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
            setMicStatus('denied');
          } else {
            setMicStatus('unavailable');
          }
        });
    } else {
      setMicStatus('unavailable');
    }

    return () => {
      active = false;
      // Stop lobby preview mic stream so it doesn't conflict with interview stage
      interviewerVoiceService.stop();
      if (previewStream) {
        previewStream.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  // Stop micStream before proceeding into stage
  const handleJoin = async () => {
    if (joining) return;
    setJoining(true);
    interviewerVoiceService.stop();

    if (micStream) {
      micStream.getTracks().forEach((t) => t.stop());
      setMicStream(null);
    }

    // Call parent to enter interview stage
    onJoinInterview();
  };

  return (
    <div className="min-h-screen bg-surface flex flex-col justify-center items-center p-4 md:p-8 animate-fade-in">
      <div className="w-full max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div className="text-center space-y-2">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-selected border border-primary text-primary text-xs font-medium">
            <Sparkles className="w-3.5 h-3.5" />
            <span>Preflight Readiness Lobby</span>
          </div>
          <h1 className="text-2xl md:text-3xl font-semibold text-heading tracking-tight">
            {role} Mock Interview
          </h1>
          <p className="text-sm text-secondary">
            {interviewType} • {difficulty} Difficulty • {mode === 'Camera' ? 'Video & Audio Mode' : 'Voice Mode'}
          </p>
        </div>

        {/* Preflight Grid */}
        <div className="grid md:grid-cols-2 gap-6 items-stretch">
          {/* Left Column: Media Preview */}
          <div className="glass-card p-6 flex flex-col justify-between border border-line">
            <div>
              <h2 className="text-sm font-semibold text-heading mb-4 flex items-center gap-2">
                {mode === 'Camera' ? (
                  <>
                    <Camera className="w-4 h-4 text-primary" />
                    <span>Camera & Video Feed</span>
                  </>
                ) : (
                  <>
                    <Mic className="w-4 h-4 text-primary" />
                    <span>Audio & Speech Setup</span>
                  </>
                )}
              </h2>

              {mode === 'Camera' ? (
                <div className="space-y-4">
                  <CameraPreview
                    enabled={true}
                    onPermissionChange={setCameraPermission}
                    className="w-full"
                  />
                  <div className="flex items-center justify-between text-xs text-secondary px-1">
                    <span>Privacy: Video is processed locally only.</span>
                    <span className="flex items-center gap-1 text-success">
                      <ShieldCheck className="w-3.5 h-3.5" /> No Storage
                    </span>
                  </div>
                </div>
              ) : (
                <div className="p-8 text-center rounded-lg bg-subtle border border-line space-y-3">
                  <div className="w-16 h-16 rounded-lg bg-selected border border-primary flex items-center justify-center mx-auto text-primary">
                    <Mic className="w-8 h-8" />
                  </div>
                  <h3 className="text-sm font-medium text-heading">Voice Mode Selected</h3>
                  <p className="text-xs text-secondary max-w-xs mx-auto">
                    Camera is disabled for this session. Your spoken responses will be transcribed using Azure Speech.
                  </p>
                </div>
              )}
            </div>

            {/* Mic Live Level Meter */}
            <div className="mt-6 pt-4 border-t border-line space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-secondary font-medium">Microphone Input</span>
                <span className="text-xs tabular-nums">
                  {micStatus === 'granted' ? (
                    <span className="text-success flex items-center gap-1">
                      <CheckCircle className="w-3 h-3" /> Connected
                    </span>
                  ) : micStatus === 'denied' ? (
                    <span className="text-danger flex items-center gap-1">
                      <AlertCircle className="w-3 h-3" /> Denied
                    </span>
                  ) : (
                    <span className="text-warning">Checking...</span>
                  )}
                </span>
              </div>
              <MicLevelMeter stream={micStream} isActive={micStatus === 'granted'} barCount={16} />
            </div>
          </div>

          {/* Right Column: AI Interviewer Voice & Readiness */}
          <div className="glass-card p-6 flex flex-col justify-between border border-line">
            <div className="space-y-5">
              <h2 className="text-sm font-semibold text-heading flex items-center gap-2">
                <Volume2 className="w-4 h-4 text-primary" />
                <span>Interviewer Voice Configuration</span>
              </h2>

              <InterviewerVoiceSelector />

              {/* Session Guidelines */}
              <div className="space-y-2 text-xs text-secondary">
                <p className="font-medium text-secondary">How your interview works:</p>
                <ul className="list-disc list-inside space-y-1 pl-1">
                  <li>The AI interviewer speaks each question aloud.</li>
                  <li>Question text is hidden by default; enable captions anytime.</li>
                  <li>Click <strong className="text-heading">Done Answering</strong> when finished.</li>
                  <li>You can review and edit your transcript before submitting.</li>
                </ul>
              </div>
            </div>

            {/* Join Interview CTA */}
            <div className="mt-6 pt-4 border-t border-line">
              <button
                onClick={handleJoin}
                disabled={joining}
                className="w-full py-3.5 rounded-lg bg-primary hover:bg-pressed text-white font-semibold text-sm   flex items-center justify-center gap-2 transition-all disabled:opacity-50"
              >
                <span>Join Interview</span>
                <ArrowRight className="w-4 h-4" />
              </button>
              <p className="text-center text-xs text-secondary mt-2">
                Clicking Join unlocks browser audio and initializes your interview stage.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
