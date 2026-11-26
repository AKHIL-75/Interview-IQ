export const mockUser = {
  id: '1',
  name: 'Alex Kumar',
  email: 'alex@example.com',
  avatar: null,
  targetRole: 'Software Engineer',
  experience: 'Fresher',
  skills: ['Java', 'C++', 'React', 'SQL', 'DSA'],
  joinedDate: '2026-08-01',
};

export const mockStats = {
  interviewsCompleted: 12,
  averageScore: 78,
  skillsIdentified: 24,
  improvement: 12,
};

export const mockRecentInterviews = [
  {
    id: '1',
    role: 'Software Engineer',
    date: 'Sep 15, 2026',
    score: 82,
    status: 'Completed',
    type: 'Technical',
    duration: '32 min',
    questions: 10,
  },
  {
    id: '2',
    role: 'Java Developer',
    date: 'Sep 12, 2026',
    score: 76,
    status: 'Completed',
    type: 'Mixed',
    duration: '28 min',
    questions: 10,
  },
  {
    id: '3',
    role: 'Frontend Developer',
    date: 'Sep 8, 2026',
    score: 71,
    status: 'Completed',
    type: 'Technical',
    duration: '25 min',
    questions: 8,
  },
  {
    id: '4',
    role: 'Full Stack Developer',
    date: 'Sep 3, 2026',
    score: 68,
    status: 'Completed',
    type: 'HR',
    duration: '20 min',
    questions: 5,
  },
  {
    id: '5',
    role: 'Backend Engineer',
    date: 'Aug 29, 2026',
    score: 74,
    status: 'Completed',
    type: 'Technical',
    duration: '30 min',
    questions: 10,
  },
];

export const mockSkillAnalysis = [
  { name: 'Java', score: 88, color: 'from-accent-500 to-accent-400' },
  { name: 'Communication', score: 82, color: 'from-emerald-500 to-emerald-400' },
  { name: 'DSA', score: 76, color: 'from-amber-500 to-amber-400' },
  { name: 'SQL', score: 64, color: 'from-cyan-500 to-cyan-400' },
  { name: 'System Design', score: 58, color: 'from-rose-500 to-rose-400' },
];

export const mockRecommendedPractice = [
  {
    id: '1',
    title: 'Java Technical Round',
    description: 'Practice core Java concepts, OOP, and collections framework',
    difficulty: 'Medium',
    duration: '30 min',
    questions: 10,
    icon: 'code',
  },
  {
    id: '2',
    title: 'DSA Problem Solving',
    description: 'Arrays, linked lists, trees, and dynamic programming',
    difficulty: 'Hard',
    duration: '45 min',
    questions: 8,
    icon: 'brain',
  },
  {
    id: '3',
    title: 'HR Behavioral Round',
    description: 'Situational questions, teamwork, and leadership scenarios',
    difficulty: 'Easy',
    duration: '20 min',
    questions: 6,
    icon: 'users',
  },
];
