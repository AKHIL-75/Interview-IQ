"""
Pydantic schemas for Phase 9: Adaptive Interview Logic & Dynamic Follow-ups.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator
from app.schemas.subjects import SubjectRequest
from app.schemas.request import RequestModel, Identifier, AnswerText, QuestionText

from app.schemas.interview import GeneratedQuestion, InterviewDifficulty, QuestionCategory


AdaptiveDecisionType = Literal[
    "TARGETED_FOLLOW_UP",
    "DEEPER_CHALLENGE",
    "NEXT_TOPIC",
    "ADVANCE_DIFFICULTY",
    "RECOVERY_QUESTION",
    "END_INTERVIEW",
]


class AdaptiveEvaluationInput(BaseModel):
    """
    Evaluation dimensions and feedback produced by Phase 10 Answer Evaluation Engine.
    """
    score: int = Field(default=0, ge=0, le=100)
    technicalAccuracy: int = Field(default=0, ge=0, le=100)
    relevance: int = Field(default=0, ge=0, le=100)
    depth: int = Field(default=0, ge=0, le=100)
    clarity: int = Field(default=0, ge=0, le=100)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    suggestedAnswer: str = Field(default="")
    answer_status: str | None = None

    @field_validator("technicalAccuracy", "relevance", "depth", "clarity", "score", mode="before")
    @classmethod
    def clamp_dimension(cls, v: Any) -> int:
        try:
            if isinstance(v, (int, float)):
                return max(0, min(100, int(round(v))))
            if isinstance(v, str):
                cleaned = v.strip().rstrip("%")
                return max(0, min(100, int(round(float(cleaned)))))
        except Exception:
            pass
        return 0


class AdaptiveNextQuestionRequest(RequestModel):
    """
    Request schema for POST /api/v1/interview/next-question.
    Consumes question context, candidate answer, Phase 10 evaluation, and session history.
    """
    session_id: Identifier | None = Field(
        default=None,
        description="Interview session ID for persistence",
    )
    previous_question: QuestionText = Field(
        ...,
        description="The interview question that was just evaluated",
        min_length=3,
    )
    candidate_answer: AnswerText = Field(
        default="",
        description="Candidate answer text evaluated by Phase 10",
    )
    evaluation: AdaptiveEvaluationInput | None = Field(
        default=None,
        description="Structured evaluation results from Phase 10",
    )
    category: Literal["Technical", "HR", "Behavioral", "Mixed"] = Field(
        default="Technical",
        description="Question category ('Technical', 'HR')",
    )
    difficulty: InterviewDifficulty = Field(
        default="Medium",
        description="Difficulty of the previous question ('Easy', 'Medium', 'Hard')",
    )
    relevant_skills: list[str] = Field(
        default_factory=list,
        description="Skills or technologies relevant to previous question",
    )
    current_topic: str = Field(
        default="General",
        description="Topic of the previous question",
    )
    consecutive_follow_ups: int = Field(
        default=0,
        ge=0,
        description="Current count of consecutive follow-ups asked on this topic",
    )
    question_history: list[str] = Field(
        default_factory=list,
        description="History of all questions asked in the session (for deduplication)",
    )
    answer_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="History of past answers with scores for difficulty stability",
    )
    role: str = Field(
        default="Software Engineer",
        description="Target job title",
    )
    interview_mode: Literal["STATIC", "DYNAMIC"] = Field(
        default="STATIC",
        description="Interview mode ('STATIC' or 'DYNAMIC')",
    )
    interview_plan: dict[str, Any] | None = Field(
        default=None,
        description="Structured interview plan tracking stages, topics, and question budgets",
    )
    interview_state: dict[str, Any] | None = Field(
        default=None,
        description="Dynamic state tracking covered topics, skills assessed, and signals",
    )
    candidate_profile: dict[str, Any] | None = Field(
        default=None,
        description="Candidate profile from resume (skills, projects, experience)",
    )
    job_profile: dict[str, Any] | None = Field(
        default=None,
        description="Job profile requirements and seniority",
    )
    analysis: dict[str, Any] | None = Field(
        default=None,
        description="Semantic match and gap analysis results",
    )

    @field_validator("previous_question", mode="before")
    @classmethod
    def clean_previous_question(cls, v: str) -> str:
        if isinstance(v, str):
            clean = v.strip()
            if not clean:
                raise ValueError("previous_question cannot be empty")
            return clean
        return v

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        if isinstance(v, str):
            val = v.strip().upper()
            if val == "HR":
                return "HR"
            if val == "INTRODUCTION":
                return "Technical"  # Existing Phase 9 request alias.
            return v.strip().capitalize()
        return v

    @field_validator("difficulty", mode="before")
    @classmethod
    def normalize_difficulty(cls, v: str) -> str:
        if isinstance(v, str):
            val = v.strip().capitalize()
            if val in ("Easy", "Medium", "Hard"):
                return val
        return v


class AdaptiveDecisionResult(BaseModel):
    """
    Deterministic output from the adaptive decision engine.
    """
    decision: AdaptiveDecisionType
    reason: str
    target_skill: str
    target_concept: str
    difficulty: InterviewDifficulty
    next_difficulty: InterviewDifficulty
    is_follow_up: bool
    conversational_lead_in: str = ""
    stage: str = "TECHNICAL_FUNDAMENTALS"
    end_interview: bool = False

    def __iter__(self):
        return iter((self.decision, self.reason, self.next_difficulty, self.is_follow_up))


class AdaptiveNextQuestionResponse(BaseModel):
    """
    Complete response returned by POST /api/v1/interview/next-question.
    """
    decision: AdaptiveDecisionType = Field(
        ...,
        description="Adaptive decision: 'TARGETED_FOLLOW_UP', 'DEEPER_CHALLENGE', 'NEXT_TOPIC', 'ADVANCE_DIFFICULTY', 'RECOVERY_QUESTION', or 'END_INTERVIEW'",
    )
    reason: str = Field(
        ...,
        description="Clear rationale explaining why this decision was made",
    )
    targetSkill: str = Field(
        default="General",
        description="Target skill for follow-up or challenge",
    )
    targetConcept: str = Field(
        default="core concepts",
        description="Specific concept or weakness targeted",
    )
    difficulty: InterviewDifficulty = Field(
        default="Medium",
        description="Difficulty level of the evaluated question",
    )
    nextDifficulty: InterviewDifficulty = Field(
        default="Medium",
        description="Difficulty level for subsequent questions",
    )
    isFollowUp: bool = Field(
        default=False,
        description="True if the question is a follow-up or deeper challenge",
    )
    question: GeneratedQuestion | None = Field(
        default=None,
        description="The dynamically generated follow-up/challenge question, or None if interview ended",
    )
    end_interview: bool = Field(
        default=False,
        description="True if the interview has reached completion or stopping criteria",
    )
    conversational_lead_in: str = Field(
        default="",
        description="Natural interviewer conversational remark acknowledging candidate response",
    )
    interview_plan: dict[str, Any] | None = Field(
        default=None,
        description="Updated interview plan",
    )
    interview_state: dict[str, Any] | None = Field(
        default=None,
        description="Updated interview state",
    )
    processing_time_ms: int | None = Field(
        default=None,
        description="Total processing latency in milliseconds",
    )


class InterviewStartRequest(SubjectRequest):
    """
    Request schema for POST /api/v1/interview/start.
    Initializes a realistic session and interview plan, returning ONLY Question 1.
    """
    candidate_profile: dict[str, Any] = Field(
        default_factory=dict,
        description="Candidate profile from resume",
    )
    job_profile: dict[str, Any] = Field(
        default_factory=dict,
        description="Target job requirements",
    )
    analysis: dict[str, Any] | None = Field(
        default=None,
        description="Optional semantic match analysis",
    )
    interview_type: Literal["Technical", "HR", "Mixed"] = Field(
        default="Technical",
        description="'Technical', 'HR', or 'Mixed'",
    )
    difficulty: InterviewDifficulty = Field(
        default="Medium",
        description="'Easy', 'Medium', or 'Hard'",
    )
    interview_mode: Literal["STATIC", "DYNAMIC"] = Field(
        default="STATIC",
        description="'STATIC' or 'DYNAMIC'",
    )
    question_count: int = Field(
        default=10,
        strict=True,
        ge=1,
        le=20,
        description="For STATIC mode: maximum questions (5, 10, 15, 20). Ignored for DYNAMIC.",
    )
    mode: Literal["Text", "Voice", "Camera"] = Field(
        default="Text",
        description="'Text' or 'Voice'",
    )
    role: str = Field(
        default="Software Engineer",
        min_length=1, max_length=200,
        description="Target role title",
    )
    resume_id: Identifier | None = Field(
        default=None,
        description="Persisted resume UUID in public.resumes",
    )
    job_description_id: Identifier | None = Field(
        default=None,
        description="Persisted job description UUID in public.job_descriptions",
    )


class InterviewStartResponse(BaseModel):
    """
    Response schema for POST /api/v1/interview/start.
    Returns session ID, interview plan, interview state, and ONLY the first question.
    """
    session_id: str
    interview_mode: str
    interview_plan: dict[str, Any]
    interview_state: dict[str, Any]
    first_question: GeneratedQuestion
    processing_time_ms: int | None = None


class AdaptiveLLMQuestionOutput(BaseModel):
    """
    Strict validation schema for single adaptive question generated by Qwen3.
    Matches required conceptual schema:
    {
      "question": "string",
      "category": "Technical",
      "topic": "string",
      "difficulty": "Easy|Medium|Hard",
      "targetSkill": "string",
      "targetConcept": "string",
      "reason": "string"
    }
    """
    question: str = Field(..., min_length=10, description="The interview question text")
    category: str = Field(default="Technical", description="'Technical' or 'HR'")
    topic: str = Field(default="General", description="Topic or technology being assessed")
    difficulty: InterviewDifficulty = Field(default="Medium", description="'Easy', 'Medium', or 'Hard'")
    targetSkill: str = Field(default="General", description="Specific skill targeted")
    targetConcept: str = Field(default="core mechanics", description="Specific concept or weakness targeted")
    reason: str = Field(default="", description="Rationale for why this question was chosen")

    @field_validator("difficulty", mode="before")
    @classmethod
    def normalize_difficulty(cls, v: Any) -> str:
        if isinstance(v, str):
            val = v.strip().capitalize()
            if val in ("Easy", "Medium", "Hard"):
                return val
        return "Medium"

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: Any) -> str:
        if isinstance(v, str) and v.strip().upper() == "HR":
            return "HR"
        return "Technical"
