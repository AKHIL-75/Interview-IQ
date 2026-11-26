import { memo } from 'react';
import InterviewerAvatar from './InterviewerAvatar';
export default memo(function InterviewerStatus({ state, voice }) {
  return <section className="iiq-interviewer rounded-lg bg-surface border border-line p-4 text-center" aria-label="AI Interviewer">
    <span className="text-xs text-primary font-semibold">AI Interviewer</span>
    <InterviewerAvatar state={state} role={voice.displayName} compact className="iiq-avatar"/>
    <p className="text-xs text-secondary">{voice.lang} · {voice.gender}</p>
  </section>;
});
