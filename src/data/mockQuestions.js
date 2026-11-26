export const technicalQuestions = [
  {
    id: 'q1',
    topic: 'Java Basics',
    question: 'Explain the difference between HashMap and ConcurrentHashMap in Java. When would you use each?',
    difficulty: 'Medium',
    category: 'Technical',
    expectedKeywords: ['thread-safe', 'synchronization', 'concurrent', 'locking', 'performance'],
  },
  {
    id: 'q2',
    topic: 'Data Structures',
    question: 'How would you detect a cycle in a linked list? Explain your approach with time and space complexity.',
    difficulty: 'Medium',
    category: 'Technical',
    expectedKeywords: ['Floyd', 'two pointers', 'slow', 'fast', 'O(n)', 'O(1)'],
  },
  {
    id: 'q3',
    topic: 'Java Basics',
    question: 'What is the difference between an abstract class and an interface in Java? When would you choose one over the other?',
    difficulty: 'Easy',
    category: 'Technical',
    expectedKeywords: ['abstract', 'interface', 'multiple inheritance', 'default methods', 'contract'],
  },
  {
    id: 'q4',
    topic: 'Algorithms',
    question: 'Find the longest substring without repeating characters. Walk me through your solution.',
    difficulty: 'Medium',
    category: 'Technical',
    expectedKeywords: ['sliding window', 'hash set', 'two pointers', 'O(n)'],
  },
  {
    id: 'q5',
    topic: 'SQL',
    question: 'Explain the difference between INNER JOIN and LEFT JOIN with a practical example.',
    difficulty: 'Easy',
    category: 'Technical',
    expectedKeywords: ['inner', 'left', 'matching rows', 'null', 'all rows'],
  },
  {
    id: 'q6',
    topic: 'System Design',
    question: 'How would you design a URL shortening service like bit.ly? Discuss the key components.',
    difficulty: 'Hard',
    category: 'Technical',
    expectedKeywords: ['hashing', 'base62', 'database', 'redirect', 'scalability', 'cache'],
  },
  {
    id: 'q7',
    topic: 'Data Structures',
    question: 'Explain how a balanced binary search tree (like AVL or Red-Black tree) maintains balance. Why is this important?',
    difficulty: 'Hard',
    category: 'Technical',
    expectedKeywords: ['rotation', 'height', 'O(log n)', 'balance factor', 'rebalancing'],
  },
  {
    id: 'q8',
    topic: 'Java Basics',
    question: 'What is the Java Memory Model? Explain the difference between stack and heap memory.',
    difficulty: 'Medium',
    category: 'Technical',
    expectedKeywords: ['stack', 'heap', 'garbage collection', 'local variables', 'objects', 'threads'],
  },
  {
    id: 'q9',
    topic: 'SQL',
    question: 'What are database indexes? How do they improve query performance, and what are their trade-offs?',
    difficulty: 'Medium',
    category: 'Technical',
    expectedKeywords: ['B-tree', 'lookup', 'write overhead', 'clustered', 'non-clustered'],
  },
  {
    id: 'q10',
    topic: 'Algorithms',
    question: 'Explain dynamic programming with an example. How does it differ from a greedy approach?',
    difficulty: 'Medium',
    category: 'Technical',
    expectedKeywords: ['overlapping subproblems', 'memoization', 'tabulation', 'optimal substructure'],
  },
  {
    id: 'q11',
    topic: 'System Design',
    question: 'How would you design a real-time chat application? Discuss the architecture and key decisions.',
    difficulty: 'Hard',
    category: 'Technical',
    expectedKeywords: ['WebSocket', 'message queue', 'database', 'scaling', 'presence'],
  },
  {
    id: 'q12',
    topic: 'Java Basics',
    question: 'Explain the concept of multithreading in Java. How do you handle thread synchronization?',
    difficulty: 'Medium',
    category: 'Technical',
    expectedKeywords: ['Thread', 'Runnable', 'synchronized', 'lock', 'deadlock', 'executor'],
  },
];

export const hrQuestions = [
  {
    id: 'hr1',
    topic: 'Introduction',
    question: 'Tell me about yourself and why you are interested in this role.',
    difficulty: 'Easy',
    category: 'HR',
    expectedKeywords: ['experience', 'passion', 'skills', 'goals'],
  },
  {
    id: 'hr2',
    topic: 'HR',
    question: 'Tell me about a challenging project you worked on. How did you overcome the difficulties?',
    difficulty: 'Medium',
    category: 'HR',
    expectedKeywords: ['challenge', 'solution', 'teamwork', 'learning', 'outcome'],
  },
  {
    id: 'hr3',
    topic: 'HR',
    question: 'Describe a situation where you had a conflict with a team member. How did you resolve it?',
    difficulty: 'Medium',
    category: 'HR',
    expectedKeywords: ['communication', 'compromise', 'understanding', 'resolution'],
  },
  {
    id: 'hr4',
    topic: 'HR',
    question: 'Where do you see yourself in 5 years? How does this role fit into your career plan?',
    difficulty: 'Easy',
    category: 'HR',
    expectedKeywords: ['growth', 'learning', 'leadership', 'contribution'],
  },
  {
    id: 'hr5',
    topic: 'HR',
    question: 'Why should we hire you? What unique value do you bring to the team?',
    difficulty: 'Medium',
    category: 'HR',
    expectedKeywords: ['skills', 'experience', 'passion', 'value', 'contribution'],
  },
  {
    id: 'hr6',
    topic: 'HR',
    question: 'How do you handle pressure and tight deadlines? Give an example from your experience.',
    difficulty: 'Medium',
    category: 'HR',
    expectedKeywords: ['prioritize', 'time management', 'calm', 'focus', 'deliver'],
  },
];

export const getQuestionsForInterview = (type = 'Mixed', count = 10) => {
  let pool = [];
  if (type === 'Technical') {
    pool = [...technicalQuestions];
  } else if (type === 'HR') {
    pool = [...hrQuestions];
  } else {
    pool = [...technicalQuestions.slice(0, 7), ...hrQuestions.slice(0, 3)];
  }

  const shuffled = pool.sort(() => 0.5 - Math.random());
  return shuffled.slice(0, Math.min(count, shuffled.length));
};

export const interviewTopics = [
  { name: 'Introduction', status: 'completed' },
  { name: 'Java Basics', status: 'completed' },
  { name: 'Data Structures', status: 'current' },
  { name: 'Algorithms', status: 'pending' },
  { name: 'HR', status: 'pending' },
];
