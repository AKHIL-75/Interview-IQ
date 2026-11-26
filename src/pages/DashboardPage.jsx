import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  PlusCircle, ClipboardList, Target, TrendingUp, Brain,
  Code, Users, BookOpen, ChevronRight, Clock,
  Wifi, WifiOff, Loader2
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import StatCard from '../components/StatCard';
import ProgressBar from '../components/ProgressBar';
import Card from '../components/Card';
import Badge from '../components/Badge';
import Button from '../components/Button';
import { mockRecommendedPractice } from '../data/mockUser';
import { checkBackendHealth, fetchDashboardAnalytics } from '../services/api';

export default function DashboardPage() {
  const { user } = useAuth();
  const hour = new Date().getHours();
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening';

  const practiceIcons = { code: Code, brain: Brain, users: Users };

  // ─── Backend Connection Status ──────────────────────────────
  const [backendStatus, setBackendStatus] = useState('checking'); // 'checking' | 'connected' | 'offline'
  const [backendVersion, setBackendVersion] = useState(null);

  // ─── Real Dashboard Analytics State ─────────────────────────
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);
  const [analyticsError, setAnalyticsError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function checkConnection() {
      try {
        const data = await checkBackendHealth();
        if (!cancelled) {
          setBackendStatus(data.status === 'ok' ? 'connected' : 'offline');
          setBackendVersion(data.version || null);
        }
      } catch {
        if (!cancelled) {
          setBackendStatus('offline');
          setBackendVersion(null);
        }
      }
    }

    async function loadAnalytics() {
      try {
        setAnalyticsLoading(true);
        const data = await fetchDashboardAnalytics();
        if (!cancelled && data?.analytics) {
          setAnalytics(data.analytics);
          setAnalyticsError(null);
        }
      } catch (err) {
        if (!cancelled) {
          console.warn('[DashboardPage] Failed to fetch analytics:', err);
          setAnalyticsError('Could not load live analytics.');
        }
      } finally {
        if (!cancelled) {
          setAnalyticsLoading(false);
        }
      }
    }

    checkConnection();
    loadAnalytics();

    return () => {
      cancelled = true;
    };
  }, []);

  const recentInterviews = analytics?.recent_interviews || [];

  const skillDimensions = [
    { name: 'Technical Accuracy', score: analytics?.performance_dimensions?.technical_accuracy || 0, color: 'bg-primary' },
    { name: 'Clarity', score: analytics?.performance_dimensions?.clarity || 0, color: 'bg-emerald-600' },
    { name: 'Relevance', score: analytics?.performance_dimensions?.relevance || 0, color: 'bg-amber-600' },
  ];

  return (
    <div className="content-area animate-fade-in">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl sm:text-3xl font-semibold text-heading mb-1">
            {greeting}, {user?.name?.split(' ')[0] || 'User'} 👋
          </h1>
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-secondary">Ready for your next interview?</p>
            {/* Backend connection indicator */}
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium transition-colors ${
                backendStatus === 'connected'
                  ? 'bg-success-surface text-success'
                  : backendStatus === 'offline'
                  ? 'bg-danger-surface text-danger'
                  : 'bg-surface text-secondary'
              }`}
              title={
                backendStatus === 'connected'
                  ? `Backend v${backendVersion} is running`
                  : backendStatus === 'offline'
                  ? 'FastAPI backend is not reachable'
                  : 'Checking backend connection...'
              }
            >
              {backendStatus === 'connected' ? (
                <Wifi className="w-3 h-3" />
              ) : backendStatus === 'offline' ? (
                <WifiOff className="w-3 h-3" />
              ) : null}
              {backendStatus === 'checking'
                ? 'Checking...'
                : backendStatus === 'connected'
                ? 'Backend: Connected'
                : 'Backend: Offline'}
            </span>
          </div>
        </div>
        <Link to="/interview/setup">
          <Button icon={PlusCircle} className="whitespace-nowrap">
            New Interview
          </Button>
        </Link>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <StatCard
          title="Interviews Completed"
          value={analyticsLoading ? '...' : (analytics?.completed_interviews ?? 0)}
          icon={ClipboardList}
          trend={analytics?.total_interviews ? analytics.total_interviews : undefined}
          trendLabel={
            analytics?.total_interviews
              ? `${analytics.total_interviews} total attempted`
              : 'no interviews yet'
          }
        />
        <StatCard
          title="Average Score"
          value={analyticsLoading ? '...' : (analytics?.average_score ?? 0)}
          suffix="%"
          icon={Target}
          trend={analytics?.average_score ? analytics.average_score : undefined}
          trendLabel={
            analytics?.completed_interviews
              ? 'across completed rounds'
              : 'no completed rounds'
          }
        />
        <StatCard
          title="Skills Identified"
          value={
            analyticsLoading
              ? '...'
              : (analytics?.skills_identified ?? (user?.skills?.length || 0))
          }
          icon={Brain}
          trend={analytics?.skills_identified ? analytics.skills_identified : undefined}
          trendLabel="from profile & interviews"
        />
        <StatCard
          title="Technical Accuracy"
          value={
            analyticsLoading
              ? '...'
              : (analytics?.performance_dimensions?.technical_accuracy ?? 0)
          }
          suffix="%"
          icon={TrendingUp}
          trend={analytics?.performance_dimensions?.technical_accuracy ? analytics.performance_dimensions.technical_accuracy : undefined}
          trendLabel="average technical accuracy"
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Recent Interviews */}
        <div className="lg:col-span-2">
          <Card>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-heading">Recent Interviews</h2>
              <Link to="/history" className="text-sm text-primary hover:text-primary flex items-center gap-1 transition-colors">
                View all <ChevronRight className="w-4 h-4" />
              </Link>
            </div>

            {analyticsLoading && (
              <div className="py-12 flex flex-col items-center justify-center text-secondary">
                <Loader2 className="w-6 h-6 text-primary animate-spin mb-2" />
                <p className="text-sm">Loading recent sessions...</p>
              </div>
            )}

            {!analyticsLoading && recentInterviews.length > 0 && (
              <div className="divide-y divide-line">
                {recentInterviews.map((interview, i) => {
                  const targetLink = interview.has_report && interview.report_id
                    ? `/report?id=${encodeURIComponent(interview.report_id)}`
                    : interview.session_id
                    ? `/report?session_id=${encodeURIComponent(interview.session_id)}`
                    : '/history';

                  const dateFormatted = interview.date
                    ? new Date(interview.date).toLocaleDateString('en-US', {
                        month: 'short',
                        day: 'numeric',
                        year: 'numeric',
                      })
                    : 'Recent';

                  return (
                    <Link
                      key={interview.id || i}
                      to={targetLink}
                      className="flex items-center gap-4 p-4 rounded-lg hover:bg-subtle transition-colors group"
                    >
                      <div className="w-7 h-10 flex items-center justify-center flex-shrink-0">
                        <Code className="w-5 h-5 text-primary" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-heading group-hover:text-primary transition-colors truncate">
                          {interview.role}
                        </p>
                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1">
                          <span className="text-xs text-secondary">{dateFormatted}</span>
                          <Badge variant={interview.type === 'Technical' ? 'accent' : interview.type === 'HR' ? 'warning' : 'info'} size="sm">
                            {interview.type}
                          </Badge>
                          {interview.duration && (
                            <span className="text-xs text-secondary hidden sm:inline flex items-center gap-1">
                              <Clock className="w-3 h-3 inline" /> {interview.duration}
                            </span>
                          )}
                        </div>
                      </div>
                      <div className="text-right flex-shrink-0">
                        <p className={`text-lg font-semibold ${
                          interview.score >= 80 ? 'text-success' : interview.score >= 60 ? 'text-warning' : 'text-danger'
                        }`}>
                          {interview.score}%
                        </p>
                        <Badge
                          variant={interview.status === 'Completed' ? 'success' : interview.status === 'In Progress' ? 'warning' : 'default'}
                          size="sm"
                        >
                          {interview.status}
                        </Badge>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}

            {!analyticsLoading && recentInterviews.length === 0 && (
              <div className="text-center py-10 px-4">
                <ClipboardList className="w-10 h-10 text-secondary mx-auto mb-3 opacity-60" />
                <p className="text-heading font-medium mb-1">No interviews completed yet</p>
                <p className="text-sm text-secondary mb-4">
                  Start your first AI mock interview to track performance metrics and historical reports.
                </p>
                <Link to="/interview/setup">
                  <Button size="sm" icon={PlusCircle}>Start First Interview</Button>
                </Link>
              </div>
            )}
          </Card>
        </div>

        {/* Skill Analysis */}
        <div>
          <Card>
            <h2 className="text-lg font-semibold text-heading mb-6">Skill Dimension Analysis</h2>
            <div className="space-y-5">
              {skillDimensions.map((skill, i) => (
                <ProgressBar
                  key={i}
                  value={skill.score}
                  label={skill.name}
                  color={skill.color}
                />
              ))}
            </div>

            {analytics?.top_strengths && analytics.top_strengths.length > 0 && (
              <div className="mt-6 pt-5 border-t border-line">
                <h3 className="text-sm font-medium text-secondary mb-3">
                  Identified Strengths
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {analytics.top_strengths.slice(0, 4).map((str, idx) => (
                    <span
                      key={idx}
                      className="text-xs px-2.5 py-1 rounded-full bg-selected text-primary border border-primary"
                    >
                      {str}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </Card>
        </div>
      </div>

      {/* Recommended Practice */}
      <div className="mt-6">
        <h2 className="text-lg font-semibold text-heading mb-4">Recommended Practice</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {mockRecommendedPractice.map((practice) => {
            const PIcon = practiceIcons[practice.icon] || BookOpen;
            return (
              <Card key={practice.id} hover className="group">
                <div className="flex items-start gap-4">
                  <div className="w-7 h-11 flex items-center justify-center flex-shrink-0 group-hover:bg-selected transition-colors">
                    <PIcon className="w-5 h-5 text-primary" />
                  </div>
                  <div className="flex-1">
                    <h3 className="text-heading font-semibold mb-1">{practice.title}</h3>
                    <p className="text-sm text-secondary mb-3 line-clamp-2">{practice.description}</p>
                    <div className="flex items-center gap-3 mb-4">
                      <Badge variant={practice.difficulty === 'Easy' ? 'success' : practice.difficulty === 'Medium' ? 'warning' : 'danger'} size="sm">
                        {practice.difficulty}
                      </Badge>
                      <span className="text-xs text-secondary flex items-center gap-1">
                        <Clock className="w-3 h-3" /> {practice.duration}
                      </span>
                    </div>
                    <Link to="/interview/setup">
                      <Button variant="secondary" size="sm" className="w-full">
                        Start Practice
                      </Button>
                    </Link>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
