import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { History, Code, Users, Shuffle, Clock, ChevronRight, PlusCircle, Loader2 } from 'lucide-react';
import Card from '../components/Card';
import Badge from '../components/Badge';
import Button from '../components/Button';
import { fetchInterviewHistory } from '../services/api';

const filters = ['All', 'Technical', 'HR', 'Mixed'];

export default function InterviewHistoryPage() {
  const [activeFilter, setActiveFilter] = useState('All');
  const [interviews, setInterviews] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    let mounted = true;
    async function loadHistory() {
      try {
        setLoading(true);
        setError(null);
        const res = await fetchInterviewHistory();
        if (!mounted) return;

        if (res?.history && Array.isArray(res.history) && res.history.length > 0) {
          const mapped = res.history.map((s) => ({
            id: s.report_id || s.id,
            reportId: s.report_id,
            sessionId: s.session_id,
            role: s.role || 'Software Engineer',
            date: s.created_at
              ? new Date(s.created_at).toLocaleDateString('en-US', {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })
              : 'Recent',
            score: s.overall_score !== null && s.overall_score !== undefined ? s.overall_score : null,
            status: s.status === 'completed' ? 'Completed' : s.status === 'active' ? 'In Progress' : 'Abandoned',
            type: s.interview_type || 'Technical',
            duration: `${Math.max(1, Math.round((s.duration_secs || 0) / 60))} min`,
            questions: s.question_count || 0,
            hasReport: Boolean(s.has_report),
          }));
          setInterviews(mapped);
        } else if (res?.reports && Array.isArray(res.reports) && res.reports.length > 0) {
          const mapped = res.reports.map((r) => ({
            id: r.id,
            reportId: r.id,
            sessionId: r.session_id,
            role: r.role || 'Software Engineer',
            date: new Date(r.created_at).toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
            }),
            score: r.overall_score || 0,
            status: 'Completed',
            type: r.interview_type || 'Technical',
            duration: `${Math.max(1, Math.round((r.duration_secs || 0) / 60))} min`,
            questions: r.total_questions || 0,
            hasReport: true,
          }));
          setInterviews(mapped);
        } else {
          setInterviews([]);
        }
      } catch (err) {
        if (mounted) {
          console.warn('[InterviewHistoryPage] Error fetching history:', err);
          setError('Could not load interview history. Please check your connection.');
          setInterviews([]);
        }
      } finally {
        if (mounted) setLoading(false);
      }
    }

    loadHistory();
    return () => {
      mounted = false;
    };
  }, []);

  const allInterviews = interviews;

  const filtered = activeFilter === 'All'
    ? allInterviews
    : allInterviews.filter(i => i.type === activeFilter);

  const typeIcons = { Technical: Code, HR: Users, Mixed: Shuffle };

  const handleOpenReport = (interview) => {
    if (interview.reportId) {
      navigate(`/report?id=${encodeURIComponent(interview.reportId)}`);
    } else if (interview.sessionId) {
      navigate(`/report?session_id=${encodeURIComponent(interview.sessionId)}`);
    } else {
      navigate('/report');
    }
  };

  return (
    <div className="content-area animate-fade-in">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-heading mb-1">Interview History</h1>
          <p className="text-secondary">
            {loading ? 'Loading interviews...' : `${allInterviews.length} interviews recorded`}
          </p>
        </div>
        <Link to="/interview/setup">
          <Button icon={PlusCircle} className="whitespace-nowrap">
            New Interview
          </Button>
        </Link>
      </div>

      {/* Filters */}
      <div className="flex gap-2 mb-6 overflow-x-auto pb-2">
        {filters.map((filter) => (
          <button
            key={filter}
            aria-pressed={activeFilter === filter}
            onClick={() => setActiveFilter(filter)}
            className={`min-h-11 px-4 py-2 rounded-md text-sm font-medium transition-all whitespace-nowrap ${
              activeFilter === filter
                ? 'bg-selected text-primary border border-primary'
                : 'text-secondary hover:text-heading hover:bg-subtle border border-transparent'
            }`}
          >
            {filter}
          </button>
        ))}
      </div>

      {/* Loading state */}
      {loading && (
        <div className="flex flex-col items-center justify-center py-16 text-secondary">
          <Loader2 className="w-8 h-8 text-primary animate-spin mb-3" />
          <p className="text-sm">Fetching your interview history...</p>
        </div>
      )}

      {/* Error state */}
      {!loading && error && (
        <div className="p-4 rounded-lg bg-danger-surface border border-red-300 text-danger text-sm mb-6 text-center">
          {error}
        </div>
      )}

      {/* Interview List */}
      {!loading && (
        <div className="space-y-3">
          {filtered.map((interview, i) => {
            const TypeIcon = typeIcons[interview.type] || Code;
            return (
              <Card
                key={interview.id || i}
                hover
                role="link" tabIndex={0} onKeyDown={event => { if (event.key === "Enter") handleOpenReport(interview); }}
                className="cursor-pointer group"
                onClick={() => handleOpenReport(interview)}
              >
                <div className="flex items-center gap-4">
                  <div className="w-7 h-11 flex items-center justify-center flex-shrink-0 group-hover:bg-selected transition-colors">
                    <TypeIcon className="w-5 h-5 text-primary" />
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="text-heading font-medium group-hover:text-primary transition-colors truncate">
                      {interview.role}
                    </p>
                    <div className="flex flex-wrap items-center gap-3 mt-1">
                      <span className="text-xs text-secondary">{interview.date}</span>
                      <Badge variant={interview.type === 'Technical' ? 'accent' : interview.type === 'HR' ? 'warning' : 'info'} size="sm">
                        {interview.type}
                      </Badge>
                      <span className="text-xs text-secondary flex items-center gap-1">
                        <Clock className="w-3 h-3" />{interview.duration}
                      </span>
                      <span className="text-xs text-secondary">{interview.questions} questions</span>
                    </div>
                  </div>

                  <div className="text-right flex-shrink-0 flex items-center gap-4">
                    <div>
                      {interview.score !== null ? (
                        <p className={`text-xl font-semibold ${
                          interview.score >= 80 ? 'text-success' : interview.score >= 60 ? 'text-warning' : 'text-danger'
                        }`}>
                          {interview.score}%
                        </p>
                      ) : (
                        <p className="text-sm font-medium text-secondary">--</p>
                      )}
                      <Badge
                        variant={interview.status === 'Completed' ? 'success' : interview.status === 'In Progress' ? 'warning' : 'default'}
                        size="sm"
                      >
                        {interview.status}
                      </Badge>
                    </div>
                    <ChevronRight className="w-5 h-5 text-secondary group-hover:text-primary transition-colors hidden sm:block" />
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* Empty states */}
      {!loading && !error && filtered.length === 0 && (
        <div className="text-center py-16">
          <History className="w-12 h-12 text-secondary mx-auto mb-4 opacity-50" />
          <p className="text-heading font-medium mb-1">
            {allInterviews.length === 0 ? 'No interviews yet' : 'No interviews match this filter'}
          </p>
          <p className="text-secondary text-sm mb-4">
            {allInterviews.length === 0
              ? 'Complete your first AI mock interview to track performance and review detailed reports.'
              : 'Try selecting a different filter above.'}
          </p>
          {allInterviews.length === 0 && (
            <Link to="/interview/setup">
              <Button icon={PlusCircle}>Start First Interview</Button>
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
