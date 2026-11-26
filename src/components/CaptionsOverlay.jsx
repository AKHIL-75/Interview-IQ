import { memo, useEffect, useRef, useState, useSyncExternalStore } from 'react';

export const CaptionBoundary = memo(function CaptionBoundary({ store, questionId, enabled, ...props }) {
  const snapshot = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
  return <CaptionsOverlay {...props} isVisible={(enabled && props.isVisible) || snapshot.unavailable}
    text={snapshot.transcripts.get(questionId) || ''} interim={snapshot.interim.get(questionId) || ''}
    updatedAt={snapshot.updatedAt.get(questionId) || 0} unavailable={snapshot.unavailable}/>;
});
export default function CaptionsOverlay({ question = '', topic = '', difficulty = '', stage = '', isVisible = false,
  className = '', text = '', interim = '', updatedAt = 0, muted = false, unavailable = false, speaking = false, onRetry }) {
  const bottom = useRef(null);
  const [faded, setFaded] = useState(false);
  useEffect(() => {
    setFaded(false);
    if (!updatedAt) return;
    const timer = setTimeout(() => setFaded(true), Math.max(0, updatedAt + 8000 - Date.now()));
    return () => clearTimeout(timer);
  }, [updatedAt]);
  useEffect(() => { if (bottom.current) bottom.current.scrollTop = bottom.current.scrollHeight; }, [text, interim, isVisible]);
  if (!isVisible || speaking) return null;
  return <section aria-label="Your live captions" className={`iiq-caption-panel rounded-lg bg-surface border border-line px-4 py-3 ${className}`}>
    <span className="block mb-1 text-xs font-semibold text-secondary">You</span>
    <div ref={bottom} aria-live="polite" aria-relevant="text" className={`max-h-[4.5rem] overflow-y-auto text-base leading-6 text-heading transition-opacity duration-200 ${faded && !muted && !unavailable && (text || interim) ? 'opacity-0' : 'opacity-100'}`}>
      {unavailable ? <span className="text-secondary">Captions unavailable</span> : muted ? <span className="text-danger">Mic is muted</span> : text || interim
        ? <><span>{text}</span>{interim && <span className="text-secondary"> {interim}</span>}</>
        : <span><span className="inline-block w-1.5 h-1.5 mr-2 rounded-full bg-primary animate-pulse motion-reduce:animate-none"/>Listening... your answer will appear here</span>}
    </div>
    {unavailable && onRetry && <button type="button" onClick={onRetry} aria-label="Retry live captions"
      className="iiq-focus mt-2 min-h-11 px-3 rounded-lg border border-line text-sm text-primary">Retry captions</button>}
  </section>;
}
