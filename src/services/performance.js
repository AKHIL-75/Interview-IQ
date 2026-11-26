/** Development-only numeric diagnostics: never accept answer text, audio or identities. */
const enabled = import.meta.env?.DEV === true;
const now = () => globalThis.performance?.now() ?? Date.now();
let sequence = 0;
export function timingEvent(stage, fields = {}) {
  if (!enabled) return;
  const safe = Object.fromEntries(Object.entries(fields).filter(([key, value]) =>
    ['duration_ms', 'status', 'bytes', 'processing_ms', 'total_ms', 'span', 'attempt'].includes(key) && Number.isFinite(value)));
  console.debug('[IIQ timing]', JSON.stringify({ stage, at_ms: Math.round(now() * 100) / 100, ...safe }));
}
export function timingSpan(stage) {
  if (!enabled) return () => {};
  const start = now(), span = ++sequence;
  let ended = false;
  timingEvent(`${stage}.start`, { span });
  return fields => {
    if (ended) return;
    ended = true;
    timingEvent(`${stage}.end`, { ...fields, span, duration_ms: Math.round((now() - start) * 100) / 100 });
  };
}
