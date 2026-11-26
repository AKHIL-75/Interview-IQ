import { useState, useRef, useEffect, useCallback } from 'react';
import { Camera, CameraOff, RefreshCw, FlipHorizontal2, AlertCircle } from 'lucide-react';

/**
 * CameraPreview — Phase 15.1
 *
 * Live webcam preview component for Camera interview mode.
 * - Uses getUserMedia for local video stream
 * - Strictly local-only preview (NO frame uploads, NO Supabase video storage)
 * - Deterministic stream lifecycle (attaches to video element safely even across state transitions)
 * - LIVE indicator verified against actual video track readiness and playing event
 * - Mirror toggle for natural candidate self-view
 * - Clean MediaStream track teardown on unmount / disable
 */
export default function CameraPreview({
  enabled = false,
  onPermissionChange,
  className = '',
  videoClassName = '',
}) {
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const bindVideo = useCallback((node) => {
    if (videoRef.current && videoRef.current !== node) videoRef.current.srcObject = null;
    videoRef.current = node;
  }, []);
  const onPermissionChangeRef = useRef(onPermissionChange);
  const isStartingRef = useRef(false);
  const generationRef = useRef(0);

  const [permissionState, setPermissionState] = useState('unknown'); // unknown | requesting | granted | denied | unavailable | playback_error
  const [isMirrored, setIsMirrored] = useState(true);
  const [isActive, setIsActive] = useState(false);
  const [streamVersion, setStreamVersion] = useState(0);

  // Keep callback ref updated without triggering effect re-runs
  useEffect(() => {
    onPermissionChangeRef.current = onPermissionChange;
  }, [onPermissionChange]);

  // Clean up camera stream
  const stopCamera = useCallback(() => {
    generationRef.current++;
    isStartingRef.current = false;
    setPermissionState('off');
    onPermissionChangeRef.current?.('off');
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => {
        try {
          track.stop();
        } catch {
          // ignore already stopped
        }
      });
      streamRef.current = null;
    }
    if (videoRef.current) {
      try {
        videoRef.current.srcObject = null;
      } catch {
        // ignore
      }
    }
    setIsActive(false);
  }, []);

  // Attach stream to video element safely and trigger playback
  const attachStreamToVideo = useCallback((stream) => {
    const video = videoRef.current;
    if (!video || !stream) return;

    if (video.srcObject !== stream) {
      video.srcObject = stream;
    }

    const checkTrackAndPlay = async () => {
      try {
        const videoTrack = stream.getVideoTracks()[0];
        if (!videoTrack || videoTrack.readyState !== 'live') {
          console.warn('[CameraPreview] Video track is not in live readyState');
          return;
        }

        // Listen for track ending (e.g. unplugged webcam)
        videoTrack.onended = () => {
          setIsActive(false);
          setPermissionState('unavailable');
          onPermissionChangeRef.current?.('unavailable');
        };

        await video.play();
        if (streamRef.current !== stream) return;
        const ready = videoTrack.readyState === 'live' && video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0;
        setIsActive(ready);
        if (ready) onPermissionChangeRef.current?.('granted');
      } catch (playErr) {
        // AbortError can occur if pause/stop was called right after play, harmless
        if (playErr.name !== 'AbortError') {
          console.warn('[CameraPreview] Video playback error:', playErr);
          setPermissionState('playback_error');
        }
      }
    };

    checkTrackAndPlay();
  }, []);

  // Start camera stream
  const startCamera = useCallback(async () => {
    if (isStartingRef.current) return;
    isStartingRef.current = true;
    const generation = generationRef.current;

    // Check browser support
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setPermissionState('unavailable');
      onPermissionChangeRef.current?.('unavailable');
      isStartingRef.current = false;
      return;
    }

    setPermissionState('requesting');

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: {
          width: { ideal: 640 },
          height: { ideal: 480 },
          facingMode: 'user',
        },
        audio: false, // Video only; microphone handled separately
      });

      if (generation !== generationRef.current) {
        stream.getTracks().forEach(track => track.stop());
        return;
      }
      streamRef.current = stream;
      const videoTracks = stream.getVideoTracks();
      if (!videoTracks || videoTracks.length === 0 || videoTracks[0].readyState !== 'live') {
        throw new Error('No active video track returned');
      }

      // Store stream reference
      streamRef.current = stream;
      setPermissionState('granted');
      setStreamVersion(v => v + 1);

      // Attempt immediate attachment
      attachStreamToVideo(stream);
    } catch (err) {
      if (generation !== generationRef.current) return;
      streamRef.current?.getTracks().forEach(track => track.stop());
      streamRef.current = null;
      console.warn('[CameraPreview] Camera access error:', err.name, err.message);

      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setPermissionState('denied');
        onPermissionChangeRef.current?.('denied');
      } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
        setPermissionState('unavailable');
        onPermissionChangeRef.current?.('unavailable');
      } else {
        setPermissionState('denied');
        onPermissionChangeRef.current?.('denied');
      }
    } finally {
      if (generation === generationRef.current) isStartingRef.current = false;
    }
  }, [attachStreamToVideo]);

  // Synchronize stream with video ref whenever DOM mounts or stream changes
  useEffect(() => {
    if (streamRef.current && videoRef.current) {
      attachStreamToVideo(streamRef.current);
    }
  }, [streamVersion, permissionState, attachStreamToVideo]);

  // Start/stop based on enabled prop
  useEffect(() => {
    if (enabled) {
      startCamera();
    } else {
      stopCamera();
    }

    return () => {
      stopCamera();
    };
  }, [enabled, startCamera, stopCamera]);

  const handleRetry = () => {
    stopCamera();
    startCamera();
  };

  if (!enabled) return null;

  return (
    <div className={`${className}`}>
      {/* Camera denied/unavailable/error state */}
      {(permissionState === 'off' || permissionState === 'denied' || permissionState === 'unavailable' || permissionState === 'playback_error') && (
        <div className="glass-card bg-surface p-6 text-center border border-amber-300">
          <CameraOff className="w-10 h-10 text-warning mx-auto mb-3" />
          <p className="text-sm text-warning font-medium mb-1">
            {permissionState === 'off' ? 'Camera is off' : permissionState === 'denied'
              ? 'Camera permission was denied'
              : permissionState === 'playback_error'
              ? 'Camera video stream playback failed'
              : 'No camera detected'}
          </p>
          <p className="text-xs text-secondary mb-4">
            {permissionState === 'denied'
              ? 'You can continue in Voice mode or grant permission in your browser.'
              : 'Please ensure your camera is connected and not in use by another application.'}
          </p>
          <button
            onClick={handleRetry}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-subtle border border-line text-secondary text-sm hover:bg-subtle transition-all"
          >
            <RefreshCw className="w-4 h-4" />
            Retry Camera
          </button>
        </div>
      )}

      {/* Requesting permission */}
      {permissionState === 'requesting' && (
        <div className="glass-card bg-surface p-6 text-center">
          <div className="w-10 h-10 rounded-full bg-selected border border-primary flex items-center justify-center mx-auto mb-3 animate-pulse">
            <Camera className="w-5 h-5 text-primary" />
          </div>
          <p className="text-sm text-secondary font-medium">Requesting camera access...</p>
          <p className="text-xs text-secondary mt-1">Please allow camera permissions in your browser prompt.</p>
        </div>
      )}

      {/* Video preview container — always present in DOM when granted/unknown/starting to guarantee videoRef is mounted */}
      <div
        className={`relative rounded-xl overflow-hidden border border-white/[0.08] bg-dark-900 transition-opacity ${
          permissionState === 'granted' ? 'block h-full' : 'hidden'
        }`}
      >
        <video
          ref={bindVideo}
          autoPlay
          playsInline
          muted
          onPlaying={() => { if (streamRef.current) attachStreamToVideo(streamRef.current); }}
          onLoadedMetadata={() => {
            if (streamRef.current) {
              attachStreamToVideo(streamRef.current);
            }
          }}
          className={`w-full ${videoClassName || 'h-auto max-h-[360px]'} object-cover bg-dark-950 ${
            isMirrored ? 'scale-x-[-1]' : ''
          }`}
        />

        {/* Camera controls overlay */}
        {isActive && (
          <div className="absolute bottom-2 right-2 flex items-center gap-2 z-10">
            {/* Mirror toggle */}
            <button
              onClick={() => setIsMirrored(!isMirrored)}
              className="min-h-11 min-w-11 grid place-items-center rounded-md bg-black/80 text-white hover:text-white hover:bg-black/80 transition-all shadow-sm"
              title={isMirrored ? 'Unmirror view' : 'Mirror view'}
            >
              <FlipHorizontal2 className="w-4 h-4" />
            </button>

            {/* Camera off button */}
            <button
              onClick={stopCamera}
              className="min-h-11 min-w-11 grid place-items-center rounded-md bg-red-800 text-white hover:bg-rose-600 transition-all shadow-sm"
              title="Turn off camera"
            >
              <CameraOff className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Live indicator — verified active only when stream is playing and tracks are live */}
        {isActive && (
          <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-black/80 border border-emerald-500/20 z-10">
            <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-xs text-white font-medium tracking-wider">LIVE</span>
          </div>
        )}
      </div>
    </div>
  );
}
