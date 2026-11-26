import { useCallback, useEffect, useRef, useState } from 'react';
import { LiveCaptionSession } from '../services/liveCaptions';

export function createCaptionStore() {
  let snapshot = { transcripts: new Map(), interim: new Map(), updatedAt: new Map(), unavailable: false };
  const listeners = new Set(), attempts = new Map(), sealed = new Set();
  let sequence = 0;
  const update = patch => { snapshot = { ...snapshot, ...patch }; listeners.forEach(listener => listener()); };
  const accepts = (id, attempt) => attempts.get(id) === attempt && !sealed.has(attempt);
  return {
    getSnapshot: () => snapshot,
    subscribe: listener => { listeners.add(listener); return () => listeners.delete(listener); },
    error: unavailable => update({ unavailable }),
    attempt: id => attempts.get(id),
    beginAttempt: id => {
      const attempt = ++sequence;
      attempts.set(id, attempt);
      update({ transcripts: new Map(snapshot.transcripts).set(id, ''), interim: new Map(snapshot.interim).set(id, ''), updatedAt: new Map(snapshot.updatedAt).set(id, 0) });
      return attempt;
    },
    interim: (id, text, attempt) => { if (accepts(id, attempt)) update({ interim: new Map(snapshot.interim).set(id, text),
      ...(text ? { updatedAt: new Map(snapshot.updatedAt).set(id, Date.now()) } : {}) }); },
    final: (id, text, attempt) => { if (accepts(id, attempt)) update({ transcripts: new Map(snapshot.transcripts).set(id, [snapshot.transcripts.get(id), text].filter(Boolean).join(' ')),
      interim: new Map(snapshot.interim).set(id, ''), updatedAt: new Map(snapshot.updatedAt).set(id, Date.now()) }); },
    seal: (id, attempt) => {
      if (attempts.get(id) !== attempt) throw new Error('The answer attempt changed. Please record again.');
      sealed.add(attempt);
      return snapshot.transcripts.get(id) || '';
    },
    reset: () => { attempts.clear(); sealed.clear(); update({ transcripts: new Map(), interim: new Map(), updatedAt: new Map(), unavailable: false }); },
  };
}
export default function useLiveCaptions({ sessionId, questionId, stream, active, onError }) {
  const [config, setConfig] = useState(null);
  const [store] = useState(createCaptionStore);
  const recognizerRef = useRef(null);
  const sessionRef = useRef(null);
  const errorRef = useRef(onError); errorRef.current = onError;
  const turnRef = useRef(); turnRef.current = { questionId, stream, active };
  const stop = useCallback(() => sessionRef.current?.stop(), []);
  const start = useCallback((stream, questionId) => {
    const attempt = store.beginAttempt(questionId);
    void sessionRef.current?.start(stream, questionId, attempt);
    return attempt;
  }, [store]);
  const resetAttempt = useCallback(questionId => { stop(); store.beginAttempt(questionId); }, [stop, store]);
  const finish = useCallback(async (questionId, attempt) => {
    await sessionRef.current?.finish();
    return store.seal(questionId, attempt);
  }, [store]);
  const dispose = useCallback(() => sessionRef.current?.dispose(), []);
  const retry = useCallback(async () => {
    const session = sessionRef.current;
    store.error(false);
    await session?.retry();
    if (session !== sessionRef.current || session?.closed || session?.failed) return;
    const turn = turnRef.current;
    if (turn.active && turn.stream) void session.start(turn.stream, turn.questionId, store.attempt(turn.questionId));
  }, [store]);
  useEffect(() => {
    setConfig(null); store.reset();
    const session = new LiveCaptionSession({ recognizerRef, onConfig: setConfig,
      onInterim: store.interim, onFinal: store.final,
      onError: () => { store.error(true); errorRef.current?.(retry); },
    });
    sessionRef.current = session;
    void session.prepare();
    return () => { session.dispose(); if (sessionRef.current === session) sessionRef.current = null; };
  }, [sessionId, store, retry]);
  useEffect(() => () => stop(), [questionId, sessionId, stop]);
  return { enabled: Boolean(config?.enabled), store, start, stop, finish, resetAttempt, dispose, retry, recognizerRef };
}
