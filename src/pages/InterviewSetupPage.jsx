import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  FileText, Briefcase, Settings, CheckCircle, AlertTriangle,
  ChevronRight, ChevronLeft,
  Zap, Target, ArrowRight, User, Award, Folder, Sparkles
} from 'lucide-react';
import { waitForSessionResolution } from '../lib/supabase';
import { useAuth } from '../context/AuthContext';
import { useInterview } from '../context/InterviewContext';
import { useToast } from '../context/ToastContext';
import Button from '../components/Button';
import Card from '../components/Card';
import FileUpload from '../components/FileUpload';
import Badge from '../components/Badge';
import SkillBadge from '../components/SkillBadge';
import ScoreCard from '../components/ScoreCard';
import { InlineLoader } from '../components/LoadingScreen';
import { mockJobDescription } from '../data/mockFeedback';
import InterviewSetupConfig from '../components/InterviewSetupConfig';
import InferenceEngineSelector from '../components/InferenceEngineSelector';
import { getInferenceEngines } from '../services/api';

const steps = [
  { num: '01', label: 'Resume', icon: FileText },
  { num: '02', label: 'Job Description', icon: Briefcase },
  { num: '03', label: 'Analysis', icon: Target },
  { num: '04', label: 'Interview Setup', icon: Settings },
];

export default function InterviewSetupPage() {
  const { user, session, loading: authLoading } = useAuth();

  const { setup, updateSetup, setInferenceEngine, isInterviewActive, parseResume, parseJobDescription, analyzeMatch, startInterview } = useInterview();
  const [currentStep, setCurrentStep] = useState(0);
  const [jobDesc, setJobDesc] = useState(setup.jobDescription || '');
  const [analyzing, setAnalyzing] = useState(false);
  const [matching, setMatching] = useState(false);
  const [generatingQuestions, setGeneratingQuestions] = useState(false);
  const { success, error, info } = useToast();
  const navigate = useNavigate();
  const [parsingResume, setParsingResume] = useState(false);
  const [engines, setEngines] = useState(null);
  const [check, setCheck] = useState(0);
  useEffect(() => {
    if (authLoading) return;
    const controller = new AbortController();
    setEngines(null);
    async function checkAvailability() {
      let result;
      try { result = await getInferenceEngines(controller.signal); } catch { /* Retry is manual. */ }
      if (!controller.signal.aborted) {
        const valid = typeof result?.local === 'boolean' && typeof result?.aws === 'boolean';
        setEngines(valid ? result : { checkFailed: true });
      }
    }
    checkAvailability();
    return () => controller.abort();
  }, [check, authLoading]);
  const selectedAvailable = engines?.[setup.inferenceEngine] === true;
  const unavailableMessage = 'Check the selected AI engine or choose an available engine before continuing.';
  function inferenceError(err, fallback) {
    if ([503, 504].includes(err.status)) {
      setCheck(n => n + 1);
      return `${err.message} Check the selected AI engine and retry.`;
    }
    return err.message || fallback;
  }

  if (authLoading) {
    return (
      <div className="content-area flex items-center justify-center min-h-[50vh]">
        <InlineLoader text="Resolving authenticated session..." />
      </div>
    );
  }

  const handleFileSelect = async (file) => {
    if (!file) {
      updateSetup({ resume: null, candidateProfile: null });
      return;
    }
    if (!selectedAvailable) throw new Error(unavailableMessage);
    setParsingResume(true);
    try {
      if (!user) {
        navigate('/login');
        throw new Error('Please sign in before uploading your resume.');
      }
      const token = session?.access_token || await waitForSessionResolution(2000);
      if (!token) throw new Error('Authentication session not ready. Please refresh or sign in again.');
      const profile = await parseResume(file);
      if (profile) {
        success(`Resume parsed: ${profile.candidate_name}`);
      }
    } catch (err) {
      error(inferenceError(err, 'Failed to parse resume'));
      throw err;
    } finally {
      setParsingResume(false);
    }
  };

  const handleAnalyze = async () => {
    if (!selectedAvailable) return error(unavailableMessage);
    if (!jobDesc.trim()) {
      info('Please paste a job description first');
      return;
    }
    if (!user) {
      error('Please sign in before parsing the job description.');
      navigate('/login');
      return;
    }
    const token = (session && session.access_token) || (await waitForSessionResolution(2000));
    if (!token) {
      error('Authentication session not ready. Please refresh or sign in again.');
      return;
    }
    setAnalyzing(true);
    try {
      const profile = await parseJobDescription(jobDesc);
      if (profile) {
        success(`Job parsed: ${profile.role_title !== 'Not specified' ? profile.role_title : 'Role requirements extracted'}`);
      }
    } catch (err) {
      error(inferenceError(err, 'Failed to parse job description'));
    } finally {
      setAnalyzing(false);
    }
  };




  const handleProceedToAnalysis = async () => {
    if (!setup.candidateProfile) {
      info('Please upload your resume in Step 1 first.');
      setCurrentStep(0);
      return;
    }
    if (!setup.jobProfile) {
      info('Please analyze the job description first.');
      return;
    }
    setMatching(true);
    try {
      await analyzeMatch();
      success('Semantic matching complete!');
      setCurrentStep(2);
    } catch (err) {
      error(err.message || 'Failed to analyze semantic match');
      setCurrentStep(2);
    } finally {
      setMatching(false);
    }
  };

  const handleStartInterview = async () => {
    if (!selectedAvailable) return error(unavailableMessage);
    if (!setup.candidateProfile) {
      info('Please upload your resume in Step 1 first.');
      setCurrentStep(0);
      return;
    }
    if (!setup.jobProfile) {
      info('Please analyze your job description in Step 2 first.');
      setCurrentStep(1);
      return;
    }

    setGeneratingQuestions(true);
    try {
      await startInterview();
      success('Personalized questions generated successfully!');
      navigate('/interview');
    } catch (err) {
      error(inferenceError(err, 'Failed to generate personalized interview questions'));
    } finally {
      setGeneratingQuestions(false);
    }
  };

  return (
    <div className={currentStep === 3 ? "content-area min-h-screen bg-page" : "content-area animate-fade-in"}>
      {/* Step indicator */}
      <div className="flex items-center justify-center gap-2 mb-10 overflow-x-auto pb-2">
        {steps.map((step, i) => (
          <div key={i} className="flex items-center">
            <button
              aria-label={step.label}
              aria-current={i === currentStep ? "step" : undefined}
              onClick={() => i <= currentStep && setCurrentStep(i)}
              className={`min-h-11 flex items-center gap-2 px-3 py-2 rounded-md transition-all whitespace-nowrap ${
                i === currentStep
                  ? 'bg-selected text-primary border border-primary'
                  : i < currentStep
                    ? 'text-success hover:bg-subtle'
                    : 'text-secondary'
              }`}
            >
              {i < currentStep ? (
                <CheckCircle className="w-4 h-4" />
              ) : (
                <span className="text-xs tabular-nums">{step.num}</span>
              )}
              <span className="text-sm font-medium hidden sm:inline">{step.label}</span>
            </button>
            {i < steps.length - 1 && <ChevronRight className="w-4 h-4 text-secondary mx-1" />}
          </div>
        ))}
      </div>

      <InferenceEngineSelector value={setup.inferenceEngine} status={engines} active={isInterviewActive}
        locked={isInterviewActive || parsingResume || analyzing || matching || generatingQuestions}
        hasProfile={Boolean(setup.candidateProfile || setup.jobProfile)}
        onChange={engine => { setInferenceEngine(engine); setCurrentStep(0); }}
        onRetry={() => setCheck(n => n + 1)} />

      {/* Step 1: Resume */}
      {currentStep === 0 && (
        <div className="max-w-2xl mx-auto animate-fade-in-up">
          <div className="text-center mb-8">
            <h2 className="text-2xl font-semibold text-heading mb-2">Upload Your Resume</h2>
            <p className="text-secondary">We'll extract your skills and experience to personalize your interview</p>
          </div>

          <FileUpload key={setup.inferenceEngine} onFileSelect={handleFileSelect} />

          {/* Extracted Candidate Profile Display */}
          {setup.candidateProfile && (
            <div className="mt-6 glass-card p-6 border border-line animate-fade-in">
              <div className="flex items-center justify-between border-b border-line pb-4 mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-selected border border-primary flex items-center justify-center">
                    <User className="w-5 h-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-heading">
                      {setup.candidateProfile.candidate_name || 'Candidate'}
                    </h3>
                    <p className="text-xs text-secondary">
                      Experience: {setup.candidateProfile.experience_years > 0 ? `${setup.candidateProfile.experience_years} years` : 'Fresher / Entry level'}
                    </p>
                  </div>
                </div>
                <Badge variant="success" size="sm">
                  Parsed by Qwen3
                </Badge>
              </div>

              {/* Extracted Skills */}
              <div className="mb-4">
                <h4 className="text-xs font-semibold uppercase  text-secondary mb-2 flex items-center gap-1.5">
                  <Award className="w-3.5 h-3.5 text-primary" />
                  Extracted Skills ({setup.candidateProfile.extracted_skills?.length || 0})
                </h4>
                {setup.candidateProfile.extracted_skills?.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto pr-1">
                    {setup.candidateProfile.extracted_skills.map((skill) => (
                      <Badge key={skill} variant="accent" size="sm">
                        {skill}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-secondary italic">No specific skills extracted</p>
                )}
              </div>

              {/* Key Projects */}
              {setup.candidateProfile.key_projects?.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold uppercase  text-secondary mb-2 flex items-center gap-1.5">
                    <Folder className="w-3.5 h-3.5 text-primary" />
                    Key Projects ({setup.candidateProfile.key_projects.length})
                  </h4>
                  <div className="space-y-2.5 max-h-48 overflow-y-auto pr-1">
                    {setup.candidateProfile.key_projects.map((project, idx) => (
                      <div key={idx} className="bg-subtle border border-line rounded-lg p-3">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-sm font-medium text-heading">{project.name}</span>
                        </div>
                        {project.description && (
                          <p className="text-xs text-secondary mb-2 leading-relaxed">{project.description}</p>
                        )}
                        {project.technologies?.length > 0 && (
                          <div className="flex flex-wrap gap-1">
                            {project.technologies.map((tech) => (
                              <span key={tech} className="text-xs px-1.5 py-0.5 rounded bg-subtle text-secondary">
                                {tech}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end mt-8">
            <Button
              onClick={() => {
                if (!setup.resume) {
                  info('Please upload a resume first');
                  return;
                }
                setCurrentStep(1);
              }}
              icon={ChevronRight}
            >
              Continue
            </Button>
          </div>
        </div>
      )}

      {/* Step 2: Job Description */}
      {currentStep === 1 && (
        <div className="max-w-2xl mx-auto animate-fade-in-up">
          <div className="text-center mb-8">
            <h2 className="text-2xl font-semibold text-heading mb-2">Add Job Description</h2>
            <p className="text-secondary">Paste the job posting to get role-specific interview questions</p>
          </div>

          <textarea aria-label="Job description"
            value={jobDesc}
            onChange={(e) => setJobDesc(e.target.value)}
            placeholder="Paste the job description here..."
            className="input-field min-h-[280px] resize-y leading-relaxed"
          />

          <button
            onClick={() => setJobDesc(mockJobDescription)}
            className="mt-2 text-sm text-primary hover:text-primary transition-colors"
          >
            Load sample job description
          </button>

          {analyzing && (
            <div className="mt-6">
              <InlineLoader message="Extracting job requirements with Qwen3..." />
            </div>
          )}

          {/* Extracted Job Profile Display */}
          {setup.jobProfile && (
            <div className="mt-6 glass-card p-6 border border-line animate-fade-in">
              <div className="flex items-center justify-between border-b border-line pb-4 mb-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-selected border border-primary flex items-center justify-center">
                    <Briefcase className="w-5 h-5 text-primary" />
                  </div>
                  <div>
                    <h3 className="text-lg font-semibold text-heading">
                      {setup.jobProfile.role_title || 'Target Role'}
                    </h3>
                    <p className="text-xs text-secondary">
                      Experience: {setup.jobProfile.experience_level || 'Not specified'}
                    </p>
                  </div>
                </div>
                <Badge variant="success" size="sm">
                  Parsed by Qwen3
                </Badge>
              </div>

              {/* Required Skills */}
              <div className="mb-4">
                <h4 className="text-xs font-semibold uppercase  text-secondary mb-2 flex items-center gap-1.5">
                  <Award className="w-3.5 h-3.5 text-primary" />
                  Required Skills ({setup.jobProfile.required_skills?.length || 0})
                </h4>
                {setup.jobProfile.required_skills?.length > 0 ? (
                  <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto pr-1">
                    {setup.jobProfile.required_skills.map((skill) => (
                      <Badge key={skill} variant="accent" size="sm">
                        {skill}
                      </Badge>
                    ))}
                  </div>
                ) : (
                  <p className="text-xs text-secondary italic">No mandatory skills extracted</p>
                )}
              </div>

              {/* Good to Have Skills */}
              {setup.jobProfile.good_to_have_skills?.length > 0 && (
                <div>
                  <h4 className="text-xs font-semibold uppercase  text-secondary mb-2 flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5 text-warning" />
                    Good- Skills ({setup.jobProfile.good_to_have_skills.length})
                  </h4>
                  <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto pr-1">
                    {setup.jobProfile.good_to_have_skills.map((skill) => (
                      <Badge key={skill} variant="neutral" size="sm">
                        {skill}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="flex justify-between mt-8">
            <Button variant="secondary" icon={ChevronLeft} onClick={() => setCurrentStep(0)}>
              Back
            </Button>
            <div className="flex items-center gap-3">
              {setup.jobProfile ? (
                <>
                  <Button variant="secondary" onClick={handleAnalyze} loading={analyzing} icon={Zap}>
                    Re-analyze Job
                  </Button>
                  <Button onClick={handleProceedToAnalysis} loading={matching} icon={ChevronRight}>
                    Continue to Analysis
                  </Button>
                </>
              ) : (
                <Button onClick={handleAnalyze} loading={analyzing} icon={Zap}>
                  Analyze Job Description
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Step 3: Analysis Results */}
      {currentStep === 2 && (
        <div className="max-w-3xl mx-auto animate-fade-in-up">
          {matching ? (
            <div className="py-16 text-center">
              <InlineLoader message="Computing semantic skill match with Sentence Transformers (all-MiniLM-L6-v2)..." />
            </div>
          ) : setup.analysis ? (
            <>
              <div className="text-center mb-8">
                <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-success-surface border border-emerald-300 text-success text-sm font-medium mb-4">
                  <CheckCircle className="w-4 h-4" />
                  Semantic Match Analysis Complete
                </div>
                <h2 className="text-2xl font-semibold text-heading">Resume & Job Analysis</h2>
                <p className="text-xs text-secondary mt-1">Computed via Sentence Transformers embeddings and cosine similarity</p>
              </div>

              <div className="grid md:grid-cols-2 gap-6 mb-6">
                {/* Match Score */}
                <Card className="flex flex-col items-center justify-center py-8">
                  <h3 className="text-sm text-secondary mb-4 font-medium">Match Score</h3>
                  <ScoreCard score={setup.analysis.match_score ?? setup.analysis.matchScore ?? 0} size="lg" />
                  <span className="text-secondary text-xs tabular-nums mt-3">
                    Similarity Threshold: {setup.analysis.summary?.threshold_used ?? 0.60}
                  </span>
                </Card>

                {/* Skills Breakdown by Evidence Tier */}
                <Card>
                  {/* Category 1: Skills Found */}
                  <div className="mb-6">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm text-secondary font-medium flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-emerald-600"></span>
                        Skills Found ({setup.analysis.skills_found?.length || setup.analysis.skillsFound?.length || 0})
                      </h3>
                      <span className="text-xs text-secondary">Explicitly listed or satisfied</span>
                    </div>
                    {(setup.analysis.skills_found || setup.analysis.skillsFound || []).length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {(setup.analysis.skills_found || setup.analysis.skillsFound).map((skill) => (
                          <SkillBadge key={skill} skill={skill} variant="found" />
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-secondary italic">No matching skills found</p>
                    )}
                  </div>

                  {/* Category 2: Covered Through Related Skills */}
                  {(setup.analysis.covered_through_parent || setup.analysis.coveredThroughParent || []).length > 0 && (
                    <div className="mb-6">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm text-secondary font-medium flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-sky-600"></span>
                          Covered Through Related Skills ({(setup.analysis.covered_through_parent || setup.analysis.coveredThroughParent || []).length})
                        </h3>
                        <span className="text-xs text-sky-800">Covered through parent core concepts</span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {(setup.analysis.covered_through_parent || setup.analysis.coveredThroughParent).map((skill) => (
                          <SkillBadge key={skill} skill={skill} variant="related" />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Category 3: Not Explicitly Evidenced */}
                  {(setup.analysis.not_explicitly_evidenced || setup.analysis.notExplicitlyEvidenced || []).length > 0 && (
                    <div className="mb-6">
                      <div className="flex items-center justify-between mb-3">
                        <h3 className="text-sm text-secondary font-medium flex items-center gap-2">
                          <span className="w-2 h-2 rounded-full bg-amber-600"></span>
                          Not Explicitly Evidenced ({(setup.analysis.not_explicitly_evidenced || setup.analysis.notExplicitlyEvidenced || []).length})
                        </h3>
                        <span className="text-xs text-warning">Sub-concept in covered domain</span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {(setup.analysis.not_explicitly_evidenced || setup.analysis.notExplicitlyEvidenced).map((skill) => (
                          <SkillBadge key={skill} skill={skill} variant="not_evidenced" />
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Category 4: Skill Gaps (True Gaps Only) */}
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm text-secondary font-medium flex items-center gap-2">
                        <span className="w-2 h-2 rounded-full bg-red-600"></span>
                        Skill Gaps ({setup.analysis.gap_skills?.length || setup.analysis.skillGaps?.length || 0})
                      </h3>
                      <span className="text-xs text-danger">True gaps missing from profile</span>
                    </div>
                    {(setup.analysis.gap_skills || setup.analysis.skillGaps || []).length > 0 ? (
                      <div className="flex flex-wrap gap-2">
                        {(setup.analysis.gap_skills || setup.analysis.skillGaps).map((skill) => (
                          <SkillBadge key={skill} skill={skill} variant="gap" />
                        ))}
                      </div>
                    ) : (
                      <p className="text-xs text-success italic">No skill gaps detected!</p>
                    )}
                  </div>
                </Card>
              </div>

              {/* Job Requirements Checklist */}
              {setup.analysis.requirements && setup.analysis.requirements.length > 0 && (
                <Card className="mb-6">
                  <h3 className="text-sm text-secondary mb-4 font-medium">Job Requirements Breakdown</h3>
                  <div className="space-y-3">
                    {setup.analysis.requirements.map((req, i) => (
                      <div key={i} className="flex items-start gap-3">
                        {req.matched && req.status !== 'parent_covered' && req.status !== 'not_explicitly_evidenced' ? (
                          <CheckCircle className="w-5 h-5 text-success flex-shrink-0 mt-0.5" />
                        ) : req.status === 'parent_covered' ? (
                          <CheckCircle className="w-5 h-5 text-sky-800 flex-shrink-0 mt-0.5" />
                        ) : req.status === 'not_explicitly_evidenced' ? (
                          <AlertTriangle className="w-5 h-5 text-warning flex-shrink-0 mt-0.5" />
                        ) : (
                          <AlertTriangle className="w-5 h-5 text-danger flex-shrink-0 mt-0.5" />
                        )}
                        <div className="flex flex-col">
                          <span className={`text-sm ${
                            req.matched && req.status !== 'parent_covered' && req.status !== 'not_explicitly_evidenced'
                              ? 'text-heading'
                              : req.status === 'parent_covered'
                              ? 'text-sky-800'
                              : req.status === 'not_explicitly_evidenced'
                              ? 'text-warning'
                              : 'text-danger'
                          }`}>
                            {req.text}
                            {req.status === 'parent_covered' && (
                              <span className="text-xs text-sky-800 ml-2">— Covered through core concept</span>
                            )}
                            {req.status === 'not_explicitly_evidenced' && (
                              <span className="text-xs text-warning ml-2">— Concept covered under domain</span>
                            )}
                            {!req.matched && (
                              <span className="text-xs text-danger ml-2">— True skill gap</span>
                            )}
                          </span>
                          {req.matched && req.matched_with && req.matched_with.toLowerCase() !== req.text.toLowerCase() && (
                            <span className="text-xs text-secondary">
                              Matched via: <span className="text-primary">{req.matched_with}</span>
                              {req.similarity ? ` (${Math.round(req.similarity * 100)}% match)` : ''}
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              <div className="flex justify-between">
                <Button variant="secondary" icon={ChevronLeft} onClick={() => setCurrentStep(1)}>
                  Back
                </Button>
                <Button onClick={() => setCurrentStep(3)} icon={ArrowRight}>
                  Continue to Interview Setup
                </Button>
              </div>
            </>
          ) : (
            <div className="text-center py-12 glass-card p-8 border border-line">
              <Target className="w-12 h-12 text-primary mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-heading mb-2">No Match Analysis Available</h3>
              <p className="text-sm text-secondary mb-6">
                Please ensure you have completed your resume and job description to compute semantic matching.
              </p>
              <Button onClick={handleProceedToAnalysis} loading={matching} icon={Zap}>
                Compute Semantic Match
              </Button>
            </div>
          )}
        </div>
      )}

      {currentStep === 3 && (
        <InterviewSetupConfig
          setup={setup}
          updateSetup={updateSetup}
          generatingQuestions={generatingQuestions}
          engineUnavailable={!selectedAvailable}
          onStart={handleStartInterview}
          onBack={() => setCurrentStep(2)}
        />
      )}
    </div>
  );
}
