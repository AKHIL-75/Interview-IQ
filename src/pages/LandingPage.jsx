import { Link } from 'react-router-dom';
import { ArrowDown, ArrowRight, ArrowUpRight, AudioLines, BarChart3, Brain, Check, Code2, FileText, GitBranch, MessageSquareText, Mic, Sparkles, Target } from 'lucide-react';
import Navbar from '../components/Navbar';
import './LandingPage.css';

function ProductPreview() {
  return (
    <figure className="lp-preview" aria-labelledby="preview-caption">
      <figcaption id="preview-caption" className="lp-preview-top">
        <span><span className="lp-status-dot" /> Interview workspace</span><span className="lp-preview-label">Product preview</span>
      </figcaption>
      <div className="lp-preview-context">
        <div className="lp-preview-file"><FileText size={19} aria-hidden="true" /><div><strong>Resume × target role</strong><span>Java Developer · Sample analysis</span></div></div>
        <div className="lp-match"><strong>82<span>%</span></strong><span>Resume match</span></div>
      </div>
      <div className="lp-preview-body">
        <div className="lp-question-meta"><span><Code2 size={15} aria-hidden="true" /> Java · Collections</span><span className="lp-tag">Medium</span></div>
        <p className="lp-overline lp-question-label">Technical question</p>
        <p className="lp-question">How does a HashMap differ from a ConcurrentHashMap?</p>
        <div className="lp-answer"><span className="lp-overline">Sample answer</span><p>“Both are thread-safe, so either can be used when multiple threads update the map.”</p></div>
        <div className="lp-evaluation"><Sparkles size={18} aria-hidden="true" /><div><strong>AI answer evaluation</strong><p>Revisit thread safety. HashMap is not thread-safe; ConcurrentHashMap supports concurrent access.</p></div></div>
        <div className="lp-next"><span><GitBranch size={16} aria-hidden="true" /> Next question adapts</span><span>Medium <ArrowRight size={14} aria-hidden="true" /><strong>Easy</strong></span></div>
      </div>
      <div className="lp-preview-bottom"><span className="lp-status-dot" /> Illustrative questions, feedback & scores</div>
    </figure>
  );
}

function FeatureTitle({ icon: Icon, label, title, children }) {
  return <><div className="lp-feature-label"><Icon size={17} aria-hidden="true" />{label}</div><h3>{title}</h3><p className="lp-feature-copy">{children}</p></>;
}

function Features() {
  return (
    <section id="features" className="lp-features lp-container" tabIndex={-1} aria-labelledby="features-title">
      <div className="lp-section-heading"><div><p className="lp-overline">Purposeful practice. Clearer progress.</p><h2 id="features-title">Powerful features.<br /><span>Built around you.</span></h2></div><p>From your first question to your next area of focus. Make every practice session count.</p></div>
      <div className="lp-bento">
        <article className="lp-feature lp-feature-adaptive">
          <FeatureTitle icon={GitBranch} label="Adaptive interviews" title="A better next question.">Difficulty responds to your answers. Revisit the fundamentals after a weak answer, and take on more as you demonstrate understanding.</FeatureTitle>
          <div className="lp-adaptive-demo" aria-label="Example difficulty adjustment from Medium to Easy after an incorrect answer">
            <div className="lp-path-row"><span className="lp-path-node">01</span><div><span className="lp-demo-label">Current question</span><strong>Java collections</strong></div><span className="lp-tag">Medium</span></div>
            <div className="lp-path-feedback"><ArrowDown size={14} aria-hidden="true" /><span>Incorrect answer · revisit the foundation</span></div>
            <div className="lp-path-row lp-path-active"><span className="lp-path-node">02</span><div><span className="lp-demo-label">Next question</span><strong>What is a Map in Java?</strong></div><span className="lp-tag">Easy</span></div>
          </div><span className="lp-demo-note">Illustrative question progression</span>
        </article>
        <article className="lp-feature lp-feature-subjects">
          <FeatureTitle icon={Code2} label="Core subjects" title="Choose your focus.">Go deep on a technical subject, or prepare for a general, HR, or mixed interview.</FeatureTitle>
          <div className="lp-subjects" aria-label="Example subject selection: Java"><span className="is-selected"><Check size={13} aria-hidden="true" /> Java</span>{['OOP', 'DSA', 'DBMS / SQL', 'Operating Systems', 'Computer Networks'].map(subject => <span key={subject}>{subject}</span>)}</div>
        </article>
        <article className="lp-feature lp-feature-match">
          <FeatureTitle icon={Target} label="Resume & role analysis" title="Your experience. Your next role.">Discover matching skills and gaps between your resume and the job description.</FeatureTitle>
          <div className="lp-match-demo"><div><FileText size={17} aria-hidden="true" /><span>Your resume</span></div><span className="lp-match-connector" aria-hidden="true" /><div><Target size={17} aria-hidden="true" /><span>Target role</span></div></div>
          <div className="lp-demo-footer"><Check size={14} aria-hidden="true" /> Example match: Java, SQL <span>Gap: Spring</span></div>
        </article>
        <article className="lp-feature lp-feature-feedback">
          <FeatureTitle icon={MessageSquareText} label="AI answer evaluation" title="Feedback you can act on.">Understand what worked, what was missing, and how to strengthen your next answer.</FeatureTitle>
          <div className="lp-feedback-demo"><span className="lp-demo-label">Example improvement</span><p><span aria-hidden="true">↳</span> Explain the trade-off, then support it with a concrete example.</p></div>
        </article>
        <article className="lp-feature lp-feature-voice">
          <FeatureTitle icon={Mic} label="Voice interviews" title="Say it out loud.">Practice explaining your thinking with voice input and speech recognition.</FeatureTitle>
          <div className="lp-wave" aria-hidden="true"><span className="lp-mic"><Mic size={19} /></span>{[10, 18, 12, 28, 38, 22, 32, 46, 28, 18, 34, 40, 24, 14, 26, 16, 10].map((height, index) => <i key={index} style={{ height }} />)}</div>
          <span className="lp-demo-note"><AudioLines size={13} aria-hidden="true" /> Your voice, transcribed into an answer</span>
        </article>
        <article className="lp-feature lp-feature-reports">
          <FeatureTitle icon={BarChart3} label="Reports & skill gaps" title="Know what to work on.">Review your performance, spot weaker areas, and give your next session a focus.</FeatureTitle>
          <div className="lp-report-demo" aria-label="Illustrative report: technical accuracy 72 percent, communication 86 percent">
            <div><span>Technical accuracy</span><strong>72%</strong></div><div className="lp-report-track"><i style={{ width: '72%' }} /></div>
            <div><span>Communication</span><strong>86%</strong></div><div className="lp-report-track"><i style={{ width: '86%' }} /></div>
          </div><span className="lp-demo-note">Illustrative report scores</span>
        </article>
      </div>
    </section>
  );
}

export default function LandingPage() {
  return (
    <div className="landing-page">
      <a className="lp-skip" href="#main-content">Skip to content</a>
      <Navbar />
      <main id="main-content" tabIndex={-1}>
        <section className="lp-hero lp-container" aria-labelledby="hero-title">
          <div className="lp-hero-copy">
            <p className="lp-eyebrow"><span className="lp-status-dot" /> AI-powered interview preparation</p>
            <h1 id="hero-title">Your next interview,<br /><span>practiced smarter.</span></h1>
            <p className="lp-hero-description">Turn your resume and target role into focused technical questions, adaptive practice, and actionable AI feedback.</p>
            <div className="lp-hero-actions"><Link to="/register" className="lp-button">Start Mock Interview <ArrowUpRight size={18} aria-hidden="true" /></Link><a href="#features" className="lp-text-link">Explore Features <ArrowRight size={16} aria-hidden="true" /></a></div>
            <p className="lp-signup-note">Create an account to start your practice.</p>
          </div>
          <div className="lp-hero-visual"><div className="lp-preview-ruler" aria-hidden="true"><span>PERSONALIZED PRACTICE</span><span>01 / INTERVIEW</span></div><ProductPreview /></div>
        </section>
        <Features />
        <section className="lp-closing lp-container" aria-labelledby="closing-title"><div><p className="lp-overline">Make room for your next opportunity</p><h2 id="closing-title">Walk in more prepared.</h2><p>Start with your experience. Build on every answer.</p></div><Link to="/register" className="lp-button">Start Practicing <ArrowUpRight size={18} aria-hidden="true" /></Link></section>
      </main>
      <footer className="lp-footer lp-container"><Link to="/" className="lp-brand"><span className="lp-logo"><Brain size={18} aria-hidden="true" /></span>Interview-IQ</Link><p>© 2026 Interview-IQ · Built for better preparation.</p><a href="#features">Features <ArrowUpRight size={14} aria-hidden="true" /></a></footer>
    </div>
  );
}
