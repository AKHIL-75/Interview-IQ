"""
Pydantic schemas for Phase 10: Answer Evaluation Engine.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator
from app.schemas.request import RequestModel, Identifier, AnswerText, QuestionText


EvaluationCategory = Literal["Technical", "HR", "Behavioral", "Mixed"]
EvaluationDifficulty = Literal["Easy", "Medium", "Hard"]
AnswerStatus = Literal["CORRECT", "PARTIAL", "INCORRECT", "IRRELEVANT", "NON_ANSWER"]
CONCEPTUAL_RUBRIC = "conceptual-v2"
MIXED_RUBRICS = "mixed"


def saved_answer_rubric(config: dict | None, question_id: str) -> str | None:
    """Read the rubric of an owned answer using existing session metadata."""
    config = config or {}
    if config.get("rubric_version") == CONCEPTUAL_RUBRIC or question_id in (
        config.get("conceptual_question_ids") or []
    ):
        return CONCEPTUAL_RUBRIC
    return None


class AnswerEvaluationRequest(RequestModel):
    """
    Request schema for POST /api/v1/evaluation/evaluate.
    Accepts candidate's answer alongside question context.
    """
    session_id: Identifier | None = None
    question_id: Identifier | None = None
    question: QuestionText = Field(
        ...,
        description="The interview question that was asked",
        min_length=3,
    )
    candidate_answer: AnswerText = Field(
        ...,
        description="The candidate's submitted answer text",
    )
    answer_source: Literal["text", "speech"] | None = Field(
        default=None, description="Optional transcription context. The submitted text is preserved.",
    )
    expected_answer: str | None = Field(
        default=None,
        max_length=20000,
        description="Optional reference or expected answer if available (never fabricated)",
    )
    job_title: str | None = Field(
        default="Software Engineer",
        description="Target job title / role context",
    )
    category: EvaluationCategory = Field(
        default="Technical",
        description="Question category: 'Technical', 'HR', 'Behavioral', or 'Mixed'",
    )
    difficulty: EvaluationDifficulty = Field(
        default="Medium",
        description="Difficulty level: 'Easy', 'Medium', or 'Hard'",
    )
    relevant_skills: list[str] = Field(
        default_factory=list,
        description="List of relevant skills or technologies for this question",
    )
    stage: str | None = Field(
        default=None,
        description="Optional interview stage (e.g. 'INTRO', 'RESUME_JD', 'PROJECT', etc.)",
    )
    topic: str | None = Field(
        default=None,
        description="Optional target skill or topic",
    )

    @field_validator("question", mode="before")
    @classmethod
    def clean_question(cls, v: str) -> str:
        if isinstance(v, str):
            cleaned = v.strip()
            if not cleaned:
                raise ValueError("Question cannot be empty or whitespace only")
            return cleaned
        return v

    @field_validator("candidate_answer", mode="before")
    @classmethod
    def clean_candidate_answer(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, v: str) -> str:
        if isinstance(v, str):
            normalized = v.strip().capitalize()
            if normalized == "Introduction":
                return "Technical"  # Existing Phase 9 alias; stage still identifies INTRO.
            if normalized in ("Technical", "Hr", "HR", "Behavioral", "Mixed"):
                return "HR" if normalized.upper() == "HR" else normalized
        return v

    @field_validator("difficulty", mode="before")
    @classmethod
    def normalize_difficulty(cls, v: str) -> str:
        if isinstance(v, str):
            normalized = v.strip().capitalize()
            if normalized in ("Easy", "Medium", "Hard"):
                return normalized
        return v


class AnswerEvaluationResponse(BaseModel):
    """
    Structured evaluation response schema.
    Conforms directly to Phase 10 specification.
    """
    @classmethod
    @field_validator("technicalAccuracy", mode="before")
    def fallback_technical_accuracy(cls, v: Any) -> Any:
        return v

    def __init__(self, **data: Any):
        if "technical_accuracy" in data and "technicalAccuracy" not in data:
            data["technicalAccuracy"] = data.pop("technical_accuracy")
        if "suggested_answer" in data and "suggestedAnswer" not in data:
            data["suggestedAnswer"] = data.pop("suggested_answer")
        super().__init__(**data)

    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="New evaluations use 60% technical accuracy, 30% relevance and 10% clarity, with evidence safeguards. Replayed evaluations retain their saved scores.",
    )
    rubric_version: Literal["conceptual-v2"] | None = Field(
        default=None, description="Absent or null for earlier evaluations.",
    )
    technicalAccuracy: int = Field(
        ...,
        ge=0,
        le=100,
        description="Technical accuracy dimension score (0-100)",
    )
    clarity: int = Field(
        ...,
        ge=0,
        le=100,
        description="Clarity dimension score (0-100)",
    )
    depth: int = Field(
        ...,
        ge=0,
        le=100,
        description="Legacy diagnostic value (0-100). Excluded from new scores.",
    )
    relevance: int = Field(
        ...,
        ge=0,
        le=100,
        description="Relevance dimension score (0-100)",
    )
    answer_status: AnswerStatus = Field(
        default="CORRECT",
        description="Categorical evaluation status: CORRECT, PARTIAL, INCORRECT, IRRELEVANT, or NON_ANSWER",
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="List of specific strengths demonstrated in the answer",
    )
    improvements: list[str] = Field(
        default_factory=list,
        description="List of actionable improvements and missing/incorrect concepts identified",
    )
    suggestedAnswer: str = Field(
        default="",
        description="Concise reference answer matching difficulty without invented candidate background",
    )
    missing_aspects: list[str] = Field(
        default_factory=list,
        description="Missing aspects or scope omitted from the candidate answer",
    )
    question_type: str = Field(
        default="TECHNICAL",
        description="Detected question evaluation type: INTRODUCTION, HR_BEHAVIORAL, TECHNICAL, PROJECT, SYSTEM_DESIGN, MIXED",
    )
    processing_time_ms: int | None = Field(
        default=None,
        description="Processing latency in milliseconds",
    )

    @property
    def technical_accuracy(self) -> int:
        return self.technicalAccuracy

    @property
    def suggested_answer(self) -> str:
        return self.suggestedAnswer
