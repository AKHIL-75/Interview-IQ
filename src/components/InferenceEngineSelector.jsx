const engines = [
  { id: 'local', label: 'Local GPU', description: 'Ollama • Qwen3:4B' },
  { id: 'aws', label: 'AWS CPU', description: 'Cloud-hosted Ollama • Qwen3:4B' },
];

export default function InferenceEngineSelector({ value, status, locked, active, hasProfile, onChange, onRetry }) {
  return <fieldset className="mx-auto mb-6 max-w-2xl rounded-lg border border-line bg-surface p-4">
    <legend className="px-1 text-base font-semibold text-heading">AI Inference Engine</legend>
    <div className="grid gap-3 sm:grid-cols-2">
      {engines.map(({ id, label, description }) => {
        const selected = value === id;
        const available = status?.[id] === true;
        return <label key={id} className={`flex items-start gap-3 rounded-lg border p-3 focus-within:ring-2 focus-within:ring-primary ${selected ? 'border-primary bg-selected' : 'border-line'}`}>
          <input type="radio" name="inference-engine" value={id} checked={selected}
            disabled={locked || !available} onChange={() => onChange(id)} className="mt-1 accent-primary" />
          <span>
            <span className="block text-sm font-semibold text-heading">{label}</span>
            <span className="block text-xs text-secondary">{description}</span>
            <span className="block text-xs text-secondary">{status === null ? 'Checking…' : status?.checkFailed ? 'Status unknown' : available ? 'Available' : 'Unavailable'}{selected && ' · Selected'}</span>
          </span>
        </label>;
      })}
    </div>
    {hasProfile && !locked && <p className="mt-2 text-xs text-secondary">Changing engines restarts résumé and job analysis.</p>}
    {active && <p className="mt-2 text-xs text-secondary">Your current interview uses the engine selected at start.</p>}
    <div aria-live="polite" className="mt-2 flex flex-wrap items-center justify-between gap-2 text-sm">
      {status?.checkFailed && <span className="text-warning">Could not read engine status from the backend. Check the connection and retry.</span>}
      {status && !status.checkFailed && !status[value] && <span className="text-warning">Selected engine unavailable. {active ? 'Check again to retry your interview.' : 'Retry or choose an available engine before starting.'}</span>}
      <button type="button" disabled={status === null} onClick={onRetry}
        className="min-h-11 px-2 text-primary disabled:text-secondary">Check availability</button>
    </div>
  </fieldset>;
}
