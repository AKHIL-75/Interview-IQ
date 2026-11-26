import { useState, useEffect, useRef } from 'react';
import {
  Brain,
  Clock,
  Sparkles,
  ArrowRight,
  Play,
  Mic,
  CameraOff,
  User,
} from 'lucide-react';
import InterviewerStatus from './InterviewerStatus';
import CameraPreview from './CameraPreview';
import { CaptionBoundary } from './CaptionsOverlay';
import InterviewControlBar from './InterviewControlBar';
import InterviewerVoiceSelector from './InterviewerVoiceSelector';
import MicLevelMeter from './MicLevelMeter';
import interviewerVoiceService from '../services/interviewerVoiceService';
import { AudioCapture } from '../services/audioCapture';
import { transcribeAudio } from '../services/api';
import { timingEvent } from '../services/performance.js';
import useLiveCaptions from '../hooks/useLiveCaptions';
import { useOptionalToast } from '../context/ToastContext';
import { getAzureVoice, DEFAULT_AZURE_VOICE } from '../services/azureVoices';

/**
 * Authoritative Interview Stage States (Phase 15.1 State Machine)
 */
export const INTERVIEW_STAGE_STATES = {
  QUESTION_LOADING: 'QUESTION_LOADING',
  QUESTION_READY: 'QUESTION_READY',
  INTERVIEWER_SPEAKING: 'INTERVIEWER_SPEAKING',
  WAITING_FOR_ANSWER: 'WAITING_FOR_ANSWER',
  RECORDING: 'RECORDING',
  TRANSCRIBING: 'TRANSCRIBING',
  ANSWER_READY: 'ANSWER_READY',
  SUBMITTING: 'SUBMITTING',
  EVALUATING: 'EVALUATING',
  TRANSITIONING: 'TRANSITIONING',
  QUESTION_COMPLETE: 'QUESTION_COMPLETE',
  INTERVIEW_COMPLETE: 'INTERVIEW_COMPLETE',
  ERROR: 'ERROR',
};

/**
 * ImmersiveInterviewStage — Phase 15.1
 *
 * Full-screen dark interview stage for Voice and Camera modes.
 *
 * Layout Hierarchy (Section 6 Invariant):
 * - Top Bar: Role title, question counter, elapsed timer, minimal actions.
 * - PRIMARY LARGE SCREEN: The Candidate Camera (or Voice audio stage in Voice mode).
 * - SECONDARY SIDEBAR: Interviewer status and microphone meter.
 * - Control Bar: Mic, Camera, Captions (CC), Voice, Repeat, Done Answering.
 * - Candidate captions below the video, hidden by default.
 * - Au State Machine:
 *   QUESTION_READY -> INTERVIEWER_SPEAKING -> RECORDING -> TRANSCRIBING -> EVALUATING -> TRANSITIONING -> NEXT_QUESTION
 */
export default function ImmersiveInterviewStage({
  session,
  saveDraft,
  submissionStage,
  questions,
  currentQuestionIndex,
  currentQuestion,
  answers,
  currentQuestionStartedAt,
  isInterviewEnded,
  setup,
  submitAnswer,
  skipQuestion,
  nextQuestion,
  handleFinish,
  isResumed = false,
}) {
  const [stageState, setStageState] = useState(INTERVIEW_STAGE_STATES.QUESTION_READY);
  const [avatarState, setAvatarState] = useState('IDLE');
  const [captionsVisible, setCaptionsVisible] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(() => {
    try { return localStorage.getItem('iiq_voice_enabled') !== 'false'; } catch { return true; }
  });
  const [cameraActive, setCameraActive] = useState(setup.mode === 'Camera');
  const [cameraPermission, setCameraPermission] = useState('unknown');
  const [isMicMuted, setIsMicMuted] = useState(true);
  const [needsResumeActivation, setNeedsResumeActivation] = useState(isResumed);
  const [isAiSpeaking, setIsAiSpeaking] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [transcriptionError, setTranscriptionError] = useState('');
  const [transitionText, setTransitionText] = useState('');
  const [timer, setTimer] = useState(0);
  const [endDialogOpen, setEndDialogOpen] = useState(false);
  const [voiceFailure, setVoiceFailure] = useState(false);
  const [echoGuardActive, setEchoGuardActive] = useState(false);
  const [selectedVoice, setSelectedVoice] = useState(() => getAzureVoice(interviewerVoiceService.getCurrentVoice?.()?.name) || getAzureVoice(DEFAULT_AZURE_VOICE));
  const toast = useOptionalToast();
  const endDialogRef = useRef(null);
  const endButtonRef = useRef(null);
  const echoReadyAtRef = useRef(0);
  const isSubmittingRef = useRef(false);
  const busyRef = useRef(false);
  const mountedRef = useRef(true);
  const generationRef = useRef(0);
  const speechTimerRef = useRef(null);
  const captureRef = useRef(new AudioCapture());
  const mediaStreamRef = useRef(null);
  const recordingAttemptRef = useRef(null);
  const captions = useLiveCaptions({ sessionId: session?.sessionId, questionId: currentQuestion?.id,
    stream: mediaStreamRef.current, active: isRecording && !isAiSpeaking && !echoGuardActive && !needsResumeActivation,
    onError: retry => toast?.error('Captions unavailable. Your recording continues.', { duration: 6000, action: { label: 'Retry', onClick: retry } }),
  });
  useEffect(() => {
    toast?.setPlacement('immersive');
    return () => toast?.setPlacement('default');
  }, [toast?.setPlacement]);
  useEffect(() => {
    if (endDialogOpen) endDialogRef.current?.querySelector('button')?.focus();
  }, [endDialogOpen]);
  const currentAnswerRecord = answers.find(a => a.questionId === currentQuestion?.id);
  const cleanupRecording = () => {
    captions.stop();
    clearTimeout(speechTimerRef.current);
    echoReadyAtRef.current = 0;
    setEchoGuardActive(false);
    captureRef.current.cancel();
    mediaStreamRef.current = null;
    setIsRecording(false);
    setIsMicMuted(true);
  };
  const cleanup = () => {
    generationRef.current++;
    interviewerVoiceService.stop();
    cleanupRecording();
    setIsAiSpeaking(false);
  };
  useEffect(() => {
    mountedRef.current = true;
    const interval = setInterval(() => setTimer(Math.max(0, Math.floor((Date.now() - (session?.startedAt || Date.now())) / 1000))), 1000);
    return () => { mountedRef.current = false; clearInterval(interval); cleanup(); };
  }, []);
  useEffect(() => {
    interviewerVoiceService.clearCache?.();
    return () => { interviewerVoiceService.stop(); interviewerVoiceService.clearCache?.(); };
  }, [session?.sessionId]);
  const formatTimer = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  const showError = error => {
    setTranscriptionError(error.message || String(error));
    setStageState(INTERVIEW_STAGE_STATES.ERROR);
    setAvatarState('ERROR');
    toast?.error('Your answer could not be completed. Please retry.', { duration: 6000,
      action: { label: 'Retry', onClick: () => transcript.trim() ? handleDoneAnswering() : startCandidateRecording() } });
  };
  const stopCandidateRecording = async () => {
    if (busyRef.current || isSubmittingRef.current) return;
    captions.stop();
    timingEvent('answer.done_recording');
    busyRef.current = true;
    const generation = generationRef.current;
    const questionId = currentQuestion.id;
    const attempt = recordingAttemptRef.current;
    setIsRecording(false);
    setStageState(INTERVIEW_STAGE_STATES.TRANSCRIBING);
    setAvatarState('PROCESSING');
    try {
      const blob = await captureRef.current.finish();
      if (!mountedRef.current || generation !== generationRef.current) return;

      const finalTranscript = await captions.finish(questionId, attempt);
      if (!mountedRef.current || generation !== generationRef.current) return;
      // Final live Azure text is authoritative. Upload to Azure only when no
      // final result exists (for example captions could not initialize).
      const result = finalTranscript ? { success: true, text: finalTranscript, warnings: [] }
        : await transcribeAudio(blob, blob.type);
      if (!mountedRef.current || generation !== generationRef.current) return;
      if (!result?.success || !result.text?.trim()) throw new Error('No clear speech detected. Please record your answer again.');
      const text = result.text.trim();
      setTranscript(text);
      timingEvent('transcript.associated', { attempt });
      saveDraft(questionId, text);
      setTranscriptionError((result.warnings || []).join(' '));
      setStageState(INTERVIEW_STAGE_STATES.ANSWER_READY);
      setAvatarState('IDLE');
      return text;
    } catch (error) {
      if (mountedRef.current && generation === generationRef.current) showError(error);
    } finally {
      if (mountedRef.current && generation === generationRef.current) {
        busyRef.current = false;
        mediaStreamRef.current = null;
        setIsMicMuted(true);
      }
    }
  };
  const startCandidateRecording = async () => {
    if (busyRef.current || isSubmittingRef.current || currentAnswerRecord?.evaluation || interviewerVoiceService.isSpeaking() || Date.now() < echoReadyAtRef.current) return;
    busyRef.current = true;
    const generation = generationRef.current;
    try {

      // Natural thinking pauses must not terminate a candidate answer.
      const stream = await captureRef.current.start();
      if (!stream || !mountedRef.current || generation !== generationRef.current) return;
      mediaStreamRef.current = stream;
      recordingAttemptRef.current = captions.start(stream, currentQuestion.id);
      setIsRecording(true);
      setIsMicMuted(false);
      setTranscriptionError('');
      setStageState(INTERVIEW_STAGE_STATES.RECORDING);
      setAvatarState('LISTENING');
    } catch (error) { if (mountedRef.current && generation === generationRef.current) showError(error); }
    finally { if (generation === generationRef.current) busyRef.current = false; }
  };
  const speakCurrentQuestion = () => {
    if (!voiceEnabled || !currentQuestion?.question || busyRef.current || isSubmittingRef.current || interviewerVoiceService.isSpeaking()) return;
    cleanup();
    setVoiceFailure(false);
    const generation = generationRef.current;
    setIsAiSpeaking(true);
    setStageState(INTERVIEW_STAGE_STATES.INTERVIEWER_SPEAKING);
    setAvatarState('SPEAKING');
    interviewerVoiceService.speak(currentQuestion.question, {
      onCancel: () => {
        if (!mountedRef.current || generation !== generationRef.current) return;
        setIsAiSpeaking(false);
        setAvatarState('IDLE');
        setStageState(INTERVIEW_STAGE_STATES.WAITING_FOR_ANSWER);
      },
      onEnd: () => {
        if (!mountedRef.current || generation !== generationRef.current) return;
        setIsAiSpeaking(false);
        setAvatarState('IDLE');
        setStageState(INTERVIEW_STAGE_STATES.WAITING_FOR_ANSWER);
        echoReadyAtRef.current = Date.now() + 400;
        setEchoGuardActive(true);
        speechTimerRef.current = setTimeout(() => {
          timingEvent('interviewer.echo_guard_complete');
          setEchoGuardActive(false);
          if (mountedRef.current && generation === generationRef.current && !currentAnswerRecord && !transcript.trim()) startCandidateRecording();
        }, 400);
      },
      onError: () => {
        if (!mountedRef.current || generation !== generationRef.current) return;
        setIsAiSpeaking(false);
        setVoiceFailure(true);
        setAvatarState('IDLE');
        setStageState(INTERVIEW_STAGE_STATES.WAITING_FOR_ANSWER);
        toast?.error('Interviewer voice unavailable.', { duration: 6000, action: { label: 'Retry', onClick: () => speakCurrentQuestion() } });
      },
    });
  };
  useEffect(() => {
    cleanup();
    busyRef.current = false;
    timingEvent('question.rendered');

    const record = session?.answers.find(a => a.questionId === currentQuestion?.id);
    const draft = session?.draft?.questionId === currentQuestion?.id ? session.draft.text : '';
    setTranscript(record?.answer || draft || '');
    setTranscriptionError('');
    setVoiceFailure(false);
    isSubmittingRef.current = false;
    if (record?.adaptiveComplete) {
      setTransitionText('Your answer is saved. Continue your interview.');
      setStageState(INTERVIEW_STAGE_STATES.TRANSITIONING);
    } else if (record || draft) {
      setStageState(INTERVIEW_STAGE_STATES.ANSWER_READY);
    } else if (!needsResumeActivation) {
      setStageState(INTERVIEW_STAGE_STATES.WAITING_FOR_ANSWER);
      // Defer one microtask so StrictMode's discarded effect never requests audio.
      let canceled = false;
      queueMicrotask(() => {
        if (canceled || !mountedRef.current) return;
        const key = `iiq_spoken_question:${session?.sessionId || 'current'}`;
        let alreadyPlayed = false;
        try { alreadyPlayed = sessionStorage.getItem(key) === currentQuestion?.id; } catch { /* Storage may be disabled. */ }
        if (voiceEnabled && !alreadyPlayed) {
          try { sessionStorage.setItem(key, currentQuestion.id); } catch { /* Optional refresh guard. */ }
          speakCurrentQuestion();
        }
      });
      return () => { canceled = true; cleanup(); };
    }
    return cleanup;
  }, [session?.sessionId, currentQuestion?.id, needsResumeActivation]);
  const finishInterview = async () => {
    if (isSubmittingRef.current || busyRef.current) return;
    isSubmittingRef.current = true;
    setEndDialogOpen(false);
    cleanup();
    captions.dispose();
    setCameraActive(false);

    setStageState(INTERVIEW_STAGE_STATES.SUBMITTING);
    try { await handleFinish(); }
    catch (error) { showError(error); }
    finally { isSubmittingRef.current = false; }
  };
  const autoAdvanceToNext = async ended => {
    if (ended || isInterviewEnded) { await finishInterview(); return; }
    if (!nextQuestion()) showError(new Error('No committed next question is available. Retry your saved answer.'));
  };
  const handleAnswerSubmission = async answerText => {
    if (isSubmittingRef.current || busyRef.current) return;
    timingEvent('answer.submit_clicked');
    const answer = String(isRecording ? await stopCandidateRecording() || '' : answerText || '').trim();
    if (!answer || !mountedRef.current) return;
    isSubmittingRef.current = true;
    cleanup();
    const generation = generationRef.current;
    setTranscript(answer);
    saveDraft(currentQuestion.id, answer);
    setTranscriptionError('');
    setStageState(INTERVIEW_STAGE_STATES.EVALUATING);
    setAvatarState('PROCESSING');
    try {
      const result = await submitAnswer(answer, 'speech');
      if (!mountedRef.current || generation !== generationRef.current) return;
      setStageState(INTERVIEW_STAGE_STATES.TRANSITIONING);
      setAvatarState('IDLE');
      isSubmittingRef.current = false;
      // Progress is driven by committed evaluation/adaptive result, never by TTS.
      await autoAdvanceToNext(result.end_interview);
    } catch (error) { if (mountedRef.current && generation === generationRef.current) showError(error); }
    finally { if (generation === generationRef.current) isSubmittingRef.current = false; }
  };
  const handleResumeActivation = () => setNeedsResumeActivation(false);
  const handleRepeatQuestion = () => {
    if (!voiceEnabled || busyRef.current || isSubmittingRef.current || interviewerVoiceService.isSpeaking() || isAiSpeaking) return;
    captions.resetAttempt(currentQuestion.id);
    speakCurrentQuestion();
  };
  const handleToggleVoice = () => {
    const enabled = !voiceEnabled;
    setVoiceEnabled(enabled);
    try { localStorage.setItem('iiq_voice_enabled', String(enabled)); } catch { /* Optional preference. */ }
    if (!enabled) {
      clearTimeout(speechTimerRef.current);
      if (isAiSpeaking) {
        generationRef.current++;
        interviewerVoiceService.stop();
        setIsAiSpeaking(false);
        setAvatarState('IDLE');
        setStageState(INTERVIEW_STAGE_STATES.WAITING_FOR_ANSWER);
      }
    }
  };
  const handleDoneAnswering = () => { captions.stop(); return handleAnswerSubmission(transcript); };
  const handleToggleMic = () => isRecording ? stopCandidateRecording() : startCandidateRecording();
  const handleManualNext = () => autoAdvanceToNext(isInterviewEnded);
  const isProcessing = ['TRANSCRIBING', 'SUBMITTING', 'EVALUATING'].includes(stageState);
  const isTransitionActive = stageState === INTERVIEW_STAGE_STATES.TRANSITIONING;
  const isLastQuestion = isInterviewEnded;
  const handleToggleCamera = () => setCameraActive(active => !active);
  const dismissEndDialog = () => { setEndDialogOpen(false); endButtonRef.current?.focus(); };
  const shortcutRef = useRef(null);
  shortcutRef.current = event => {
      if (event.repeat || event.altKey || event.ctrlKey || event.metaKey || endDialogOpen || needsResumeActivation || event.target?.closest?.('input, textarea, select, [contenteditable="true"], [role="dialog"]') || document.querySelector('[role="dialog"]')) return;
      const key = event.key.toLowerCase();
      if (!['m', 'v', 'c', 'r'].includes(key)) return;
      event.preventDefault();
      if (key === 'v') handleToggleCamera();
      if (key === 'c' && captions.enabled) setCaptionsVisible(value => !value);
      if (key === 'm' && !isAiSpeaking && !echoGuardActive && !isProcessing && !isTransitionActive && !currentAnswerRecord?.evaluation) handleToggleMic();
      if (key === 'r' && voiceEnabled && !isAiSpeaking && !isProcessing && !isTransitionActive) handleRepeatQuestion();
  };
  useEffect(() => {
    const onKey = event => shortcutRef.current(event);
    window.addEventListener?.('keydown', onKey);
    return () => window.removeEventListener?.('keydown', onKey);
  }, []);

  const totalQuestions = setup.questionCount || Math.max(questions?.length || 0, currentQuestionIndex + 1);
  return (
    <div data-interview-stage="true" className="iiq-immersive fixed inset-0 z-30 flex flex-col overflow-hidden bg-page text-heading">
      <header className="iiq-header h-16 shrink-0 flex items-center gap-3 px-4 md:px-6 border-b border-line bg-surface">
        <div className="iiq-brand flex flex-1 items-center gap-3 min-w-0">
          <div className="w-9 h-9 shrink-0 rounded-lg bg-primary text-white flex items-center justify-center" aria-label="Interview-IQ"><Brain size={20}/></div>
          <span className="truncate text-sm font-semibold">{setup.role || 'Mock Interview'} - {setup.interviewType || 'Technical'}</span>
        </div>
        <div className="iiq-progress min-w-0 text-center text-xs md:text-sm">
          <span>Question {currentQuestionIndex + 1} of {totalQuestions}</span>
          <div role="progressbar" aria-label="Interview progress" aria-valuenow={currentQuestionIndex + 1} aria-valuemin={0} aria-valuemax={totalQuestions} className="h-1 bg-subtle rounded-full mt-2 overflow-hidden">
            <div className="h-full bg-primary transition-all duration-200" style={{ width: ((currentQuestionIndex + 1) / totalQuestions * 100) + '%' }}/>
          </div>
        </div>
        <div className="iiq-header-actions flex shrink-0 items-center justify-end gap-2">
          <div className="iiq-timer flex items-center gap-2 rounded-md border border-line px-3 py-2 text-xs tabular-nums"><Clock size={14}/>{formatTimer(timer)}</div>
          <button ref={endButtonRef} className="iiq-focus shrink-0 whitespace-nowrap min-h-11 px-3 rounded-lg border border-red-300 text-danger hover:bg-danger-surface text-xs md:text-sm disabled:opacity-40" disabled={isProcessing} onClick={() => setEndDialogOpen(true)}>End Interview</button>
        </div>
      </header>
      <main className="iiq-main flex-1 min-h-0 px-3 md:px-6 py-3">
        <div className="iiq-stage-grid">
        <div className="iiq-video-column">
        <div className="iiq-candidate relative aspect-video rounded-lg overflow-hidden border border-line bg-surface ">
          {cameraActive ? <CameraPreview enabled={cameraActive} onPermissionChange={setCameraPermission} className="w-full h-full" videoClassName="w-full h-full min-h-0 object-cover"/>
            : <div className="iiq-camera-off absolute inset-0 flex flex-col items-center justify-center gap-3 text-center p-4">
                <CameraOff size={30} className="text-slate-200"/>
                <p className="text-sm font-medium">Camera is off</p>
                <button onClick={() => setCameraActive(true)} className="iiq-focus min-h-11 px-4 rounded-lg bg-subtle hover:bg-subtle border border-line text-sm">Turn Camera On</button>
              </div>}
        </div>
          {(!transcript.trim() || isRecording) && <CaptionBoundary store={captions.store} questionId={currentQuestion?.id} enabled={captions.enabled}
            isVisible={captionsVisible} muted={isMicMuted} speaking={isAiSpeaking} onRetry={captions.retry}/>}
        </div>
        <aside className="iiq-sidebar">
          <InterviewerStatus state={avatarState} voice={selectedVoice}/>
          <section aria-label="Current question" className="min-w-0 max-h-[40vh] max-lg:max-h-24 max-lg:flex-1 overflow-y-auto rounded-lg border border-line bg-surface p-4">
            <h2 className="mb-2 text-xs font-semibold text-secondary">Current question</h2>
            <p className="text-sm leading-relaxed text-heading">{currentQuestion?.question}</p>
          </section>
          <div className="iiq-meter rounded-lg border border-line bg-surface p-4">
            <MicLevelMeter stream={mediaStreamRef.current} isActive={isRecording}/>
          </div>
          {transcript.trim() && !isRecording && <section aria-label="Recorded answer transcript" className="min-w-0 max-h-36 max-lg:max-h-24 max-lg:flex-1 overflow-y-auto rounded-lg border border-line bg-surface p-4">
            <h2 className="mb-2 text-xs font-semibold text-secondary">Recorded answer transcript</h2>
            <p className="text-sm leading-relaxed text-heading">{transcript}</p>
          </section>}
        </aside>
        </div>
        {voiceFailure && <div role="status" className="iiq-recovery w-full max-w-3xl rounded-lg bg-warning-surface border border-amber-300 p-3 text-sm">
          <p className="text-warning text-xs">Interviewer voice unavailable. Read the current question or use Repeat to try again.</p>
        </div>}
        {isTransitionActive ? <div className="text-center text-sm"><p>{transitionText}</p><button onClick={handleManualNext} className="iiq-focus min-h-11 mt-2 px-4 rounded-lg bg-primary text-white">{isLastQuestion ? 'Complete Interview & View Report' : 'Next Question'}</button></div>
          : !isRecording && !isProcessing && (transcriptionError || transcript) && <p role={transcriptionError ? 'alert' : 'status'} className="iiq-recovery text-center text-sm text-secondary max-w-2xl">
            {transcriptionError ? transcriptionError + (transcript ? ' Your answer is preserved. Use Done Answering to retry.' : ' Use the microphone to record again.') : 'Answer ready. Use Done Answering to submit, or the microphone to record again.'}
          </p>}
      </main>
      <footer className="iiq-footer shrink-0">
        {submissionStage && <p role="status" className="text-center text-sm text-secondary">{submissionStage}…</p>}
        <InterviewControlBar mode={setup.mode} isRecording={isRecording} isSpeaking={isAiSpeaking || echoGuardActive}
          isProcessing={isProcessing || isTransitionActive} isCameraActive={cameraActive && cameraPermission === 'granted'} isMicMuted={isMicMuted}
          captionsEnabled={captionsVisible} captionsAvailable={captions.enabled} voiceEnabled={voiceEnabled} disabled={needsResumeActivation || endDialogOpen}
          canDoneAnswer={!isAiSpeaking && !echoGuardActive && !isTransitionActive && (isRecording || Boolean(transcript.trim()))} canRecord={!currentAnswerRecord?.evaluation}
          onToggleMic={handleToggleMic} onToggleCamera={handleToggleCamera} onToggleCaptions={() => setCaptionsVisible(value => !value)}
          onToggleVoice={handleToggleVoice} onRepeatQuestion={handleRepeatQuestion} onDoneAnswering={handleDoneAnswering} onEndInterview={() => setEndDialogOpen(true)}
          voiceSelector={<InterviewerVoiceSelector compact disabled={isProcessing || isTransitionActive || needsResumeActivation} onVoiceChange={setSelectedVoice}/>}/>
      </footer>
      {needsResumeActivation && <div role="dialog" aria-modal="true" aria-label="Resume Interview" className="absolute inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/45">
        <div className="w-full max-w-md rounded-lg bg-surface border border-line p-8 text-center space-y-4">
          <Play size={32} className="mx-auto text-primary"/><h2 className="text-xl font-semibold">Resume Interview</h2>
          <p className="text-sm text-secondary">Your session state has been restored. Resume to continue your answer. Use Repeat if you want to hear the question again.</p>
          <button className="iiq-focus min-h-11 w-full rounded-lg bg-primary text-white" onClick={handleResumeActivation}>Resume Interview</button>
        </div>
      </div>}
      {endDialogOpen && <div ref={endDialogRef} role="dialog" aria-modal="true" aria-labelledby="iiq-end-title" className="absolute inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/45" onKeyDown={event => {
        if (event.key === 'Escape') { event.stopPropagation(); dismissEndDialog(); }
        if (event.key === 'Tab') { const buttons = Array.from(event.currentTarget.querySelectorAll('button')); const index = buttons.indexOf(document.activeElement); event.preventDefault(); buttons[(index + (event.shiftKey ? buttons.length - 1 : 1)) % buttons.length]?.focus(); }
      }}>
        <div className="w-full max-w-md rounded-lg border border-line bg-surface p-6">
          <h2 id="iiq-end-title" className="text-lg font-semibold">Finish this interview?</h2><p className="text-sm text-secondary mt-2">Your completed answers will be saved. An unfinished recording will be discarded.</p>
          <div className="flex justify-end gap-3 mt-6"><button className="iiq-focus min-h-11 px-4 rounded-lg border border-line" onClick={dismissEndDialog}>Keep interviewing</button><button className="iiq-focus min-h-11 px-4 rounded-lg bg-red-600 hover:bg-red-700 text-white" onClick={finishInterview}>Confirm end</button></div>
        </div>
      </div>}
    </div>
  );
}
