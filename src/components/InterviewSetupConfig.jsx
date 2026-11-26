import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { Briefcase, Camera, Check, CheckCircle2, ChevronDown, ChevronLeft, Clock3, Code, Info, Loader2, Mic, Play, Search, ShieldCheck, Shuffle, Sparkles, Type, Users, XCircle } from 'lucide-react';

const focusRing = 'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-surface';
const surface = 'rounded-lg border border-line bg-surface p-6';
const subjects = [
  { value: '', label: 'General interview - Resume and job description' },
  { value: 'Java', label: 'Java' },
  { value: 'OOP', label: 'Object-Oriented Programming (OOP)' },
  { value: 'DSA', label: 'Data Structures and Algorithms (DSA)' },
  { value: 'DBMS and SQL', label: 'Database Management Systems (DBMS) and SQL' },
  { value: 'Operating Systems', label: 'Operating Systems' },
  { value: 'Computer Networks', label: 'Computer Networks' },
];
const difficultyDescriptions = {
  Easy: 'Build confidence with foundational concepts and approachable questions.',
  Medium: 'Apply your knowledge to practical scenarios and deeper follow-ups.',
  Hard: 'Prepare for deeper reasoning and challenging technical discussions.',
};

function OptionGroup({ label, value, options, onChange, columns = 3, compact = false }) {
  const buttons = useRef([]);
  const selectedIndex = Math.max(0, options.findIndex((option) => option.value === value));
  function handleKey(event, index) {
    let next;
    if (['ArrowRight', 'ArrowDown'].includes(event.key)) next = (index + 1) % options.length;
    if (['ArrowLeft', 'ArrowUp'].includes(event.key)) next = (index - 1 + options.length) % options.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = options.length - 1;
    if (next === undefined) return;
    event.preventDefault();
    onChange(options[next].value);
    buttons.current[next]?.focus();
  }
  return (
    <div role="radiogroup" aria-label={label} className={`grid gap-3 ${columns === 4 ? 'grid-cols-4' : columns === 2 ? 'grid-cols-1 sm:grid-cols-2' : compact ? 'grid-cols-3' : 'grid-cols-1 sm:grid-cols-3'}`}>
      {options.map(({ value: optionValue, label: title, description, icon: Icon, badge, note }, index) => (
        <button key={optionValue} ref={(element) => { buttons.current[index] = element; }} type="button" role="radio"
          aria-checked={value === optionValue} tabIndex={index === selectedIndex ? 0 : -1}
          onKeyDown={(event) => handleKey(event, index)} onClick={() => onChange(optionValue)}
          className={`relative min-w-0 min-h-11 rounded-lg border text-left transition duration-200 motion-reduce:transition-none ${focusRing} ${compact ? 'px-2 py-3 text-center' : 'p-4 pt-5'} ${value === optionValue ? 'border-primary bg-selected ' : 'border-line bg-surface hover:border-primary'}`}>
          {value === optionValue && <Check aria-hidden="true" className={`absolute text-primary ${compact ? 'right-1 top-1 h-3 w-3' : 'right-3 top-3 h-4 w-4'}`} />}
          {Icon && <Icon aria-hidden="true" className="mb-4 h-5 w-5 text-primary" />}
          <span className="block text-sm font-semibold text-heading">{title}</span>
          {badge && <span className="mt-2 inline-block rounded-md bg-selected px-2 py-1 text-xs font-medium text-primary">{badge}</span>}
          {description && <span className="mt-2 block text-[13px] leading-relaxed text-secondary">{description}</span>}
          {note && <span className="mt-2 block text-[13px] leading-relaxed text-secondary">{note}</span>}
        </button>
      ))}
    </div>
  );
}

function Section({ number, title, helper, children }) {
  const id = useId();
  return <section aria-labelledby={id} className={surface}>
    <div className="mb-5 flex items-start gap-3">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-selected text-xs font-semibold text-primary">{number}</span>
      <div><h2 id={id} className="text-lg font-semibold text-heading">{title}</h2><p className="mt-1 text-[13px] leading-relaxed text-secondary">{helper}</p></div>
    </div>
    {children}
  </section>;
}

function FocusCombobox({ value, onChange, disabled }) {
  const id = useId();
  const root = useRef(null);
  const input = useRef(null);
  const trigger = useRef(null);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const selected = subjects.find((subject) => subject.value === value) || subjects[0];
  const filtered = subjects.filter((subject) => subject.label.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => {
    if (!open) return;
    input.current?.focus();
    const close = (event) => { if (!root.current?.contains(event.target)) setOpen(false); };
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  function select(option) {
    onChange(option.value || null);
    setOpen(false);
    trigger.current?.focus();
  }
  return <div ref={root} className="relative" onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <button ref={trigger} type="button" disabled={disabled} aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-list`} aria-label={`Focus area: ${selected.label}`}
      onClick={() => { setQuery(''); setActive(0); setOpen(!open); }}
      onKeyDown={(event) => { if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); setQuery(''); setActive(0); setOpen(true); } }}
      className={`flex min-h-12 w-full items-center justify-between gap-3 rounded-lg border border-line bg-subtle px-4 py-3 text-left text-sm text-heading disabled:cursor-not-allowed disabled:opacity-60 ${focusRing}`}>
      <span>{selected.label}</span><ChevronDown aria-hidden="true" className="h-4 w-4 shrink-0 text-secondary" />
    </button>
    {open && <div className="absolute left-0 right-0 top-full z-30 mt-2 rounded-lg border border-line bg-surface p-2 shadow-lg">
      <div className="relative mb-2"><Search aria-hidden="true" className="pointer-events-none absolute left-3 top-3.5 h-4 w-4 text-secondary" />
        <input ref={input} role="combobox" aria-label="Search focus areas" aria-autocomplete="list" aria-expanded="true" aria-controls={`${id}-list`} aria-activedescendant={filtered[active] ? `${id}-option-${active}` : undefined}
          value={query} onChange={(event) => { setQuery(event.target.value); setActive(0); }} placeholder="Search subjects…"
          onKeyDown={(event) => {
            if (event.key === 'Escape') { event.preventDefault(); setOpen(false); trigger.current?.focus(); }
            if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); setActive((index) => filtered.length ? (index + (event.key === 'ArrowDown' ? 1 : -1) + filtered.length) % filtered.length : 0); }
            if (event.key === 'Enter') { event.preventDefault(); if (filtered[active]) select(filtered[active]); }
          }} className={`min-h-11 w-full rounded-lg bg-page py-3 pl-9 pr-3 text-sm text-heading placeholder:text-secondary ${focusRing}`} />
      </div>
      <ul id={`${id}-list`} role="listbox" aria-label="Focus areas" className="max-h-72 overflow-y-auto">
        {filtered.map((option, index) => <li key={option.value} id={`${id}-option-${index}`} role="option" aria-selected={value === option.value}
          ref={(element) => { if (index === active) element?.scrollIntoView({ block: 'nearest' }); }}
          onMouseDown={(event) => event.preventDefault()} onClick={() => select(option)}
          className={`flex min-h-11 cursor-pointer items-center justify-between gap-3 rounded-lg px-3 py-3 text-sm text-heading hover:bg-selected ${index === active ? 'bg-selected' : ''}`}>
          {option.label}{value === option.value && <Check aria-hidden="true" className="h-4 w-4 shrink-0 text-primary" />}
        </li>)}
      </ul>
      {!filtered.length && <p role="status" className="p-3 text-sm text-secondary">No subjects found. Try another search.</p>}
    </div>}
  </div>;
}

const deviceFailures = {
  denied: ['Permission denied', 'Access denied. Allow device access in your browser or system settings, then test again.'],
  unavailable: ['Unavailable', 'Check that the device is connected and selected as the default, then test again.'],
  hardware: ['Device error', 'The device could not be opened. Close other apps using it or reconnect it, then test again.'],
  initialization: ['Initialization failed', 'The device did not start. Retry the test or reload this page.'],
  unsupported: ['Unsupported', 'Device testing requires a supported browser on HTTPS or localhost.'],
};
const deviceLabels = { unchecked: 'Not tested', checking: 'Checking', ready: 'Ready', 'not required': 'Not required' };

function captureFailure(name) {
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError': return 'denied';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
    case 'ConstraintNotSatisfiedError': return 'unavailable';
    case 'NotReadableError':
    case 'TrackStartError': return 'hardware';
    case 'SecurityError': return 'unsupported';
    default: return 'initialization';
  }
}

const initialReadiness = { microphone: 'unchecked', camera: 'unchecked' };
const stopTracks = (stream) => stream?.getTracks().forEach((track) => track.stop());
const hasLiveTrack = (tracks) => tracks.some((track) => track.readyState === 'live');

function useDeviceReadiness(mode) {
  const [statuses, setStatuses] = useState(initialReadiness);
  const [preview, setPreview] = useState(null);
  const pendingPreview = useRef(null);
  const request = useRef(0);
  const cancel = useCallback(() => {
    request.current += 1;
    stopTracks(pendingPreview.current);
    pendingPreview.current = null;
  }, []);

  useLayoutEffect(() => {
    setPreview(null);
    setStatuses(initialReadiness);
    return cancel;
  }, [mode, cancel]);

  const finishPreview = useCallback((stream) => {
    if (pendingPreview.current !== stream) return;
    const status = hasLiveTrack(stream.getVideoTracks()) ? 'ready' : 'unavailable';
    pendingPreview.current = null;
    stopTracks(stream);
    setStatuses((current) => ({ ...current, camera: status }));
  }, []);

  async function testDevices() {
    cancel();
    const attempt = request.current;
    setPreview(null);
    const cameraRequired = mode === 'Camera';
    const media = navigator.mediaDevices;
    if (!media?.getUserMedia) {
      setStatuses({ microphone: 'unsupported', camera: cameraRequired ? 'unsupported' : 'unchecked' });
      return;
    }
    setStatuses({ microphone: 'checking', camera: cameraRequired ? 'checking' : 'unchecked' });

    for (const device of cameraRequired ? ['microphone', 'camera'] : ['microphone']) {
      if (attempt !== request.current) return;
      const camera = device === 'camera';
      let stream;
      try {
        stream = await media.getUserMedia(camera ? { video: true } : { audio: true });
        if (attempt !== request.current) return;
        const tracks = camera ? stream.getVideoTracks() : stream.getAudioTracks();
        // A live track can be temporarily muted while the browser starts the source.
        if (!hasLiveTrack(tracks)) {
          setStatuses((current) => ({ ...current, [device]: 'initialization' }));
        } else if (camera) {
          pendingPreview.current = stream;
          setPreview(stream);
          stream = null;
        } else {
          setStatuses((current) => ({ ...current, microphone: 'ready' }));
        }
      } catch (error) {
        if (attempt === request.current) {
          setStatuses((current) => ({ ...current, [device]: captureFailure(error?.name) }));
        }
      } finally {
        stopTracks(stream);
      }
    }
  }
  const ready = mode === 'Text' || (statuses.microphone === 'ready' && (mode !== 'Camera' || statuses.camera === 'ready'));
  return { statuses, preview, testDevices, ready, cancel, finishPreview };
}

function CameraThumbnail({ stream, onComplete }) {
  const video = useRef(null);
  const canvas = useRef(null);
  const [hasFrame, setHasFrame] = useState(false);

  useEffect(() => {
    const source = video.current;
    let finished = false;
    function finish() {
      if (finished) return;
      finished = true;
      clearTimeout(timeout);
      source.srcObject = null;
      onComplete(stream);
    }
    function captureFrame() {
      if (finished || !source.videoWidth || !source.videoHeight) return;
      try {
        const frame = canvas.current;
        frame.width = Math.min(source.videoWidth, 640);
        frame.height = Math.round(frame.width * source.videoHeight / source.videoWidth);
        const context = frame.getContext('2d');
        if (context) {
          context.drawImage(source, 0, 0, frame.width, frame.height);
          setHasFrame(true);
        }
      } catch {
        // A thumbnail failure does not invalidate a live camera track.
      } finally {
        finish();
      }
    }
    const timeout = setTimeout(finish, 2000);
    source.addEventListener('loadeddata', captureFrame);
    source.addEventListener('error', finish);
    source.srcObject = stream;
    return () => {
      finished = true;
      clearTimeout(timeout);
      source.removeEventListener('loadeddata', captureFrame);
      source.removeEventListener('error', finish);
      source.srcObject = null;
    };
  }, [stream, onComplete]);

  return <>
    <video ref={video} autoPlay muted playsInline aria-hidden="true" className="sr-only" />
    <canvas ref={canvas} role="img" aria-label="Camera readiness preview" hidden={!hasFrame} className="mt-3 w-full rounded-lg border border-line bg-black" />
  </>;
}

export default function InterviewSetupConfig({ setup, updateSetup, generatingQuestions, engineUnavailable, onStart, onBack }) {
  const [showAllSkills, setShowAllSkills] = useState(false);
  const tooltipId = useId();
  const mode = setup.mode || 'Text';
  const dynamic = setup.interviewMode === 'DYNAMIC';
  const count = setup.questionCount || 10;
  const skills = [...new Set(setup.candidateProfile?.extracted_skills || [])];
  const focus = subjects.find((subject) => subject.value === (setup.subject || ''))?.label || setup.subject;
  const devices = useDeviceReadiness(mode);
  const checking = Object.values(devices.statuses).includes('checking');
  const disabledReason = generatingQuestions ? 'Generating your personalized interview questions…' : engineUnavailable ? 'Check availability or select an available AI engine.' : !devices.ready ? 'Test your devices below. Required devices must be ready to start.' : '';
  const summary = [
    ['Role', setup.role], ['Type', setup.interviewType], ['Focus', focus], ['Difficulty', setup.difficulty],
    ['Style', dynamic ? 'Dynamic · 5–20 questions' : `Static · ${count} questions`], ['Mode', mode],
  ];
  function start() {
    if (disabledReason) return;
    devices.cancel();
    onStart();
  }
  return <div className="mx-auto max-w-[1200px] pb-40 text-heading lg:pb-0">
    <header className="mb-8">
      <h1 className="text-3xl font-semibold tracking-tight">Interview Setup</h1>
      <p className="mt-2 text-sm text-secondary">Tailor your mock session</p>
      <div className="mt-6 flex items-center gap-4 rounded-lg border border-line bg-surface p-5">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-selected"><Briefcase aria-hidden="true" className="h-5 w-5 text-primary" /></div>
        <div className="min-w-0"><p className="font-medium text-heading">{setup.role}</p><p className="mt-1 text-[13px] text-secondary">{skills.length} skills detected</p></div>
        <Sparkles aria-hidden="true" className="ml-auto hidden h-5 w-5 shrink-0 text-primary sm:block" />
      </div>
    </header>
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(300px,1fr)]">
      <div className="min-w-0 space-y-8">
        <Section number="01" title="Interview Type" helper="Choose the conversation you want to practice.">
          <OptionGroup label="Interview type" value={setup.interviewType} onChange={(value) => updateSetup({ interviewType: value, subject: value === 'Technical' ? setup.subject : null })}
            options={[
              { value: 'Technical', label: 'Technical', icon: Code, description: 'Coding, concepts, system design' },
              { value: 'HR', label: 'HR', icon: Users, description: 'Experience, communication, culture' },
              { value: 'Mixed', label: 'Mixed', icon: Shuffle, description: 'Technical and behavioral questions' },
            ]} />
        </Section>
        <Section number="02" title="Focus Area" helper="Keep it broad or concentrate on a core subject.">
          <FocusCombobox value={setup.subject || ''} onChange={(subject) => updateSetup({ subject })} disabled={setup.interviewType !== 'Technical'} />
          <p className="mt-3 text-[13px] leading-relaxed text-secondary">{setup.interviewType === 'Technical' ? 'General interviews use your resume and job description. Subject interviews start with a technical question and stay on your selected subject.' : 'HR and Mixed interviews use your resume and job description. Select Technical to focus on a core subject.'}</p>
        </Section>
        <Section number="03" title="Difficulty" helper="Set the starting point for your session.">
          <OptionGroup label="Difficulty" value={setup.difficulty} compact options={['Easy', 'Medium', 'Hard'].map((value) => ({ value, label: value }))} onChange={(difficulty) => updateSetup({ difficulty })} />
          <p aria-live="polite" className="mt-4 text-[13px] leading-relaxed text-secondary">{difficultyDescriptions[setup.difficulty]}</p>
          <p className="mt-3 flex items-start gap-2 text-[13px] leading-relaxed text-secondary"><Sparkles aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-primary" />Difficulty adapts to your answers. Hard begins at Medium and adjusts as you progress.</p>
        </Section>
        <Section number="04" title="Interview Style" helper="Choose a question cap or let the AI guide the length.">
          <OptionGroup label="Interview style" columns={2} value={dynamic ? 'DYNAMIC' : 'STATIC'} onChange={(interviewMode) => updateSetup({ interviewMode })}
            options={[{ value: 'STATIC', label: 'Static', description: 'Fixed question cap' }, { value: 'DYNAMIC', label: 'Dynamic', description: 'AI decides when to conclude (5 to 20 questions)' }]} />
          <div className={`grid transition-[grid-template-rows,opacity] duration-200 motion-reduce:transition-none ${dynamic ? 'grid-rows-[0fr] opacity-0' : 'grid-rows-[1fr] opacity-100'}`} inert={dynamic ? '' : undefined} aria-hidden={dynamic}>
            <div className="min-h-0 overflow-hidden"><div className="pt-5"><p className="mb-3 text-[13px] text-secondary">Maximum questions</p>
              <OptionGroup label="Maximum questions" columns={4} compact value={count} options={[5, 10, 15, 20].map((value) => ({ value, label: String(value) }))} onChange={(questionCount) => updateSetup({ questionCount })} />
            </div></div>
          </div>
            {dynamic && <p className="mt-4 flex items-start gap-2 rounded-lg border border-primary bg-selected p-3 text-[13px] leading-relaxed text-secondary"><Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-primary" />The AI considers conceptual understanding and topic coverage to conclude naturally after 5-20 questions.</p>}
        </Section>
        <Section number="05" title="Answer Mode" helper="Pick how you feel most comfortable answering.">
          <OptionGroup label="Answer mode" value={mode} onChange={(value) => updateSetup({ mode: value })} options={[
            { value: 'Text', label: 'Text', icon: Type, description: 'Type your answers' },
            { value: 'Voice', label: 'Voice', icon: Mic, description: 'Speak, live transcript', badge: 'Recommended' },
            { value: 'Camera', label: 'Camera', icon: Camera, description: 'Video + voice', note: 'Requires camera and mic access' },
          ]} />
          {mode !== 'Text' && <p className="mt-4 text-[13px] leading-relaxed text-secondary">Voice answers are transcribed with Azure Speech. Final recognized words are preserved when submitting. Test your devices in the session summary.</p>}
        </Section>
      </div>
      <aside aria-labelledby="session-summary" className={`${surface} min-w-0 self-start lg:sticky lg:top-6`}>
        <div className="mb-6 flex items-center gap-2"><Sparkles aria-hidden="true" className="h-5 w-5 text-primary" /><h2 id="session-summary" className="text-lg font-semibold">Session Summary</h2></div>
        <dl className="space-y-4">{summary.map(([label, value]) => <div key={label} className="grid grid-cols-[70px_minmax(0,1fr)] gap-4 text-[13px]"><dt className="text-secondary">{label}</dt><dd className="break-words text-right font-medium leading-relaxed text-heading">{value}</dd></div>)}</dl>
        <div className="mt-5 flex items-center justify-between gap-3 rounded-lg bg-selected p-3 text-[13px]"><span className="flex items-center gap-2 text-secondary"><Clock3 aria-hidden="true" className="h-4 w-4 text-primary" />Est. duration</span><span className="font-medium text-primary">~{dynamic ? '10–40' : count * 2} min</span></div>
        <section className="mt-6 border-t border-line pt-5" aria-label="Detected skills">
          <h3 className="mb-3 text-[13px] font-medium text-secondary">Detected skills <span className="text-secondary">· {skills.length}</span></h3>
          <div className="flex flex-wrap items-center gap-2">{(showAllSkills ? skills : skills.slice(0, 6)).map((skill) => <span key={skill} className="rounded-md border border-line bg-subtle px-2.5 py-1.5 text-xs text-secondary">{skill}</span>)}
            {skills.length > 6 && <button type="button" aria-expanded={showAllSkills} onClick={() => setShowAllSkills(!showAllSkills)} className={`min-h-11 rounded-lg px-2.5 text-xs font-medium text-primary hover:bg-selected ${focusRing}`}>{showAllSkills ? 'Show less' : `+${skills.length - 6} more`}</button>}
            {!skills.length && <p className="text-[13px] text-secondary">No skills detected yet.</p>}
          </div>
        </section>
        {mode !== 'Text' && <section aria-label="Device readiness" className="mt-5 border-t border-line pt-5">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium"><ShieldCheck aria-hidden="true" className="h-4 w-4 text-primary" />Device readiness</h3>
          <div aria-live="polite" className="space-y-3">{['microphone', 'camera'].map((device) => {
            const required = device === 'microphone' || mode === 'Camera';
            const status = required ? devices.statuses[device] : 'not required';
            const failure = deviceFailures[status];
            const StatusIcon = status === 'ready' ? CheckCircle2 : failure ? XCircle : status === 'checking' ? Loader2 : Info;
            return <div key={device}>
              <div className="flex items-center justify-between gap-3 text-[13px]"><span className="capitalize text-secondary">{device}</span><span className={`flex items-center gap-1.5 ${status === 'ready' ? 'text-success' : failure ? 'text-danger' : 'text-secondary'}`}><StatusIcon aria-hidden="true" className={`h-4 w-4 ${status === 'checking' ? 'motion-safe:animate-spin' : ''}`} />{failure?.[0] || deviceLabels[status]}</span></div>
              {failure && <p className="mt-1 text-[13px] leading-relaxed text-secondary">{failure[1]}</p>}
            </div>;
          })}</div>
          {mode === 'Camera' && devices.preview && <CameraThumbnail stream={devices.preview} onComplete={devices.finishPreview} />}
          <button type="button" onClick={devices.testDevices} disabled={checking || generatingQuestions} className={`mt-4 min-h-11 w-full rounded-lg border border-line px-3 py-2 text-sm font-medium transition duration-150 hover:border-line hover:bg-subtle disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none ${focusRing}`}>{checking ? 'Checking devices…' : 'Test devices'}</button>
          <p className="mt-2 text-[13px] leading-relaxed text-secondary">This local check releases your devices when it finishes.</p>
        </section>}
        <div className="mt-6 hidden lg:block"><StartAction onStart={start} disabledReason={disabledReason} loading={generatingQuestions} tooltipId={`${tooltipId}-desktop`} /></div>
        <button type="button" onClick={() => { devices.cancel(); onBack(); }} disabled={generatingQuestions} className={`mt-3 flex min-h-11 w-full items-center justify-center gap-2 rounded-lg border border-line text-sm text-secondary hover:border-line hover:bg-subtle disabled:opacity-50 ${focusRing}`}><ChevronLeft aria-hidden="true" className="h-4 w-4" />Back</button>
      </aside>
    </div>
    <div className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface p-4 pb-[max(1rem,env(safe-area-inset-bottom))]  lg:hidden"><StartAction onStart={start} disabledReason={disabledReason} loading={generatingQuestions} tooltipId={`${tooltipId}-mobile`} /></div>
  </div>;
}

function StartAction({ onStart, disabledReason, loading, tooltipId }) {
  return <div className={`group relative rounded-lg ${focusRing}`} tabIndex={disabledReason ? 0 : undefined} aria-label={disabledReason ? 'Start Interview unavailable' : undefined} aria-describedby={disabledReason ? tooltipId : undefined}>
    <button type="button" onClick={onStart} disabled={Boolean(disabledReason)} aria-describedby={disabledReason ? tooltipId : undefined}
      className={`flex min-h-12 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-3 text-sm font-semibold text-white   transition duration-200 hover:bg-pressed disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none ${focusRing}`}>
      {loading ? <Loader2 aria-hidden="true" className="h-4 w-4 motion-safe:animate-spin" /> : <Play aria-hidden="true" className="h-4 w-4" />}{loading ? 'Preparing interview…' : 'Start Interview'}
    </button>
    {disabledReason && <><span id={tooltipId} role="tooltip" className="pointer-events-none absolute bottom-full left-0 mb-2 hidden w-full rounded-lg border border-line bg-surface p-3 text-[13px] text-secondary group-hover:block group-focus:block group-focus-within:block">{disabledReason}</span><p role="status" className="mt-2 text-center text-[13px] text-secondary">{disabledReason}</p></>}
  </div>;
}
