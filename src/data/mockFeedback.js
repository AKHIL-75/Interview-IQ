export const generateMockFeedback = (questionId) => {
  const feedbacks = {
    default: {
      overallScore: 82,
      scores: {
        technicalAccuracy: 85,
        communication: 78,
        depth: 82,
        relevance: 88,
      },
      strengths: [
        'Correctly explained core concepts',
        'Provided a practical real-world example',
        'Good understanding of fundamentals',
        'Clear and structured response',
      ],
      improvements: [
        'Explain thread safety implications more clearly',
        'Discuss performance trade-offs in more detail',
        'Include edge cases in your explanation',
        'Mention alternative approaches',
      ],
      suggestedAnswer:
        'A strong answer would cover the core concept, provide a comparison with alternatives, discuss time and space complexity, mention real-world use cases, and address edge cases. Structure your response with a clear introduction, detailed explanation, and a practical example.',
    },
  };

  return feedbacks[questionId] || feedbacks.default;
};

export const generateMockEvaluation = () => {
  const base = 75;
  const variance = 15;
  const rand = () => Math.floor(base + Math.random() * variance);

  return {
    score: rand(),
    technicalAccuracy: rand(),
    clarity: rand(),
    depth: rand(),
  };
};

export const mockReportData = {
  id: 'report-1',
  role: 'Software Engineer',
  date: 'September 17, 2026',
  overallScore: 82,
  scores: {
    technicalKnowledge: 85,
    problemSolving: 79,
    communication: 78,
    confidence: 81,
    jobRelevance: 88,
  },
  strengths: ['Java', 'Data Structures', 'Problem Solving'],
  skillGaps: ['System Design', 'AWS', 'Docker'],
  questionAnalysis: [
    { question: 'HashMap vs ConcurrentHashMap', score: 88 },
    { question: 'Cycle detection in linked list', score: 76 },
    { question: 'Abstract class vs Interface', score: 82 },
    { question: 'Longest substring problem', score: 79 },
    { question: 'INNER JOIN vs LEFT JOIN', score: 85 },
  ],
  recommendations: [
    'Practice system design fundamentals — focus on scalability and trade-offs.',
    'Review Java concurrency concepts — understand thread pools and executors.',
    'Practice explaining solutions aloud — clarity matters in interviews.',
    'Solve more medium-level DSA problems — especially trees and graphs.',
  ],
  interviewType: 'Technical',
  difficulty: 'Medium',
  duration: '32 min',
  questionsAnswered: 5,
  totalQuestions: 5,
};

export const mockAnalysisResult = {
  matchScore: 82,
  matchLabel: 'Strong match',
  skillsFound: [
    'Java', 'C++', 'Data Structures', 'Algorithms',
    'SQL', 'React', 'Node.js', 'Git', 'REST APIs',
  ],
  skillGaps: ['System Design', 'Docker', 'AWS', 'Testing'],
  requirements: [
    { text: 'Proficiency in Java or similar OOP language', matched: true },
    { text: 'Strong data structures and algorithms', matched: true },
    { text: 'Experience with relational databases (SQL)', matched: true },
    { text: 'Knowledge of web frameworks (React/Angular)', matched: true },
    { text: 'Understanding of RESTful API design', matched: true },
    { text: 'Experience with system design', matched: false },
    { text: 'Familiarity with cloud services (AWS/GCP)', matched: false },
    { text: 'Experience with containerization (Docker)', matched: false },
    { text: 'Knowledge of CI/CD pipelines', matched: false },
    { text: 'Unit testing and test-driven development', matched: false },
  ],
};

export const mockJobDescription = `Software Engineer - Full Stack

Company: TechCorp Solutions
Location: Bangalore, India (Hybrid)
Experience: 0-2 years

About the Role:
We are looking for a passionate Software Engineer to join our growing engineering team. You will work on building scalable web applications and contribute to our core platform.

Requirements:
• Proficiency in Java or similar OOP language
• Strong understanding of data structures and algorithms
• Experience with relational databases (SQL)
• Knowledge of web frameworks (React/Angular)
• Understanding of RESTful API design
• Familiarity with version control (Git)

Nice to Have:
• Experience with system design concepts
• Familiarity with cloud services (AWS/GCP)
• Experience with containerization (Docker/Kubernetes)
• Knowledge of CI/CD pipelines
• Unit testing and test-driven development

What We Offer:
• Competitive salary and equity
• Flexible working hours
• Learning and development budget
• Health insurance
• Modern tech stack`;
