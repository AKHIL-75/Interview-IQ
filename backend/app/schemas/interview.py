"""
Pydantic schemas for Phase 7: Personalized Question Generation.
"""

import time
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from app.schemas.subjects import SubjectRequest
from app.schemas.request import RequestModel

from app.schemas.resume import CandidateProfile
from app.schemas.job import JobProfile
from app.schemas.analysis import MatchAnalysisResponse


InterviewType = Literal["Technical", "HR", "Mixed"]
InterviewDifficulty = Literal["Easy", "Medium", "Hard"]
QuestionCategory = Literal["Technical", "HR"]
InterviewStage = Literal["INTRO", "RESUME_JD", "TECHNICAL_FUNDAMENTALS", "PROJECT", "ADVANCED_TECHNICAL", "ADAPTIVE"]


class QuestionGenerationRequest(SubjectRequest):
    """
    Request payload for POST /api/v1/interview/generate-questions.
    Consumes candidate profile (Phase 4), job profile (Phase 5),
    optional semantic analysis (Phase 6), and interview configurations.
    """
    candidate_profile: CandidateProfile = Field(
        ...,
        description="Candidate profile extracted from resume in Phase 4",
    )
    job_profile: JobProfile = Field(
        ...,
        description="Job profile extracted from job description in Phase 5",
    )
    analysis: MatchAnalysisResponse | None = Field(
        default=None,
        description="Optional semantic match analysis from Phase 6 (matched skills, gaps)",
    )
    interview_type: InterviewType = Field(
        default="Technical",
        description="Interview type: 'Technical', 'HR', or 'Mixed'",
    )
    difficulty: InterviewDifficulty = Field(
        default="Medium",
        description="Difficulty level: 'Easy', 'Medium', or 'Hard'",
    )
    question_count: int = Field(
        default=10,
        strict=True,
        ge=1,
        le=20,
        description="Number of personalized questions to generate (1 to 20)",
    )

    @field_validator("interview_type", mode="before")
    @classmethod
    def normalize_interview_type(cls, v: str) -> str:
        if isinstance(v, str):
            val = v.strip().capitalize()
            if val in ("Technical", "Hr", "HR", "Mixed"):
                return "HR" if val.upper() == "HR" else val
        return v

    @field_validator("difficulty", mode="before")
    @classmethod
    def normalize_difficulty(cls, v: str) -> str:
        if isinstance(v, str):
            val = v.strip().capitalize()
            if val in ("Easy", "Medium", "Hard"):
                return val
        return v


class GeneratedQuestion(BaseModel):
    """
    Represents an individual personalized interview question.
    Directly compatible with frontend QuestionCard and InterviewPage components.
    """
    id: str = Field(..., description="Unique question identifier (e.g. 'q1', 'q2')")
    question: str = Field(..., description="The interview question text")
    category: QuestionCategory = Field(
        default="Technical",
        description="Question category: 'Technical' or 'HR'",
    )
    topic: str = Field(..., description="Target skill or topic (e.g. 'Java', 'SQL', 'Teamwork')")
    difficulty: InterviewDifficulty = Field(
        default="Medium",
        description="Difficulty rating: 'Easy', 'Medium', or 'Hard'",
    )
    stage: InterviewStage = Field(
        default="TECHNICAL_FUNDAMENTALS",
        description="Interview stage: INTRO, RESUME_JD, TECHNICAL_FUNDAMENTALS, PROJECT, ADVANCED_TECHNICAL, ADAPTIVE",
    )
    is_follow_up: bool = Field(
        default=False,
        description="Whether this question is an adaptive follow-up",
    )
    focus: str = Field(
        default="General",
        description="Assessment focus (e.g. 'Matched Skill', 'Skill Gap', 'Project Experience', 'Behavioral')",
    )
    expected_aspects: list[str] = Field(
        default_factory=list,
        description="Key conceptual points or evaluation criteria expected in a solid answer",
    )

    @field_validator("stage", mode="before")
    @classmethod
    def normalize_stage(cls, v: str) -> str:
        if isinstance(v, str):
            clean = v.strip().upper()
            if clean in ("INTRO", "RESUME_JD", "TECHNICAL_FUNDAMENTALS", "PROJECT", "ADVANCED_TECHNICAL", "ADAPTIVE"):
                return clean
            if "INTRO" in clean:
                return "INTRO"
            if "RESUME" in clean or "JD" in clean:
                return "RESUME_JD"
            if "FUNDAMENTAL" in clean:
                return "TECHNICAL_FUNDAMENTALS"
            if "PROJECT" in clean:
                return "PROJECT"
            if "ADVANCED" in clean:
                return "ADVANCED_TECHNICAL"
            if "ADAPTIVE" in clean or "FOLLOW" in clean:
                return "ADAPTIVE"
        return "TECHNICAL_FUNDAMENTALS"

    @field_validator("question", mode="before")
    @classmethod
    def clean_question(cls, v: str) -> str:
        return str(v).strip()

    @field_validator("topic", mode="before")
    @classmethod
    def clean_topic(cls, v: str) -> str:
        return str(v).strip() if v else "General"

    @field_validator("category", mode="before")
    @classmethod
    def clean_category(cls, v: str) -> str:
        if isinstance(v, str):
            val = v.strip().upper()
            if val == "HR":
                return "HR"
            return "Technical"
        return "Technical"

    @field_validator("difficulty", mode="before")
    @classmethod
    def clean_diff(cls, v: str) -> str:
        if isinstance(v, str):
            val = v.strip().capitalize()
            if val in ("Easy", "Medium", "Hard"):
                return val
        return "Medium"


class QuestionGenerationResponse(BaseModel):
    """
    Response schema for POST /api/v1/interview/generate-questions.
    """
    success: bool = Field(default=True, description="Indicates successful question generation")
    questions: list[GeneratedQuestion] = Field(
        default_factory=list,
        description="List of personalized interview questions",
    )
    count: int = Field(..., description="Number of questions generated")
    interview_type: str = Field(..., description="Requested interview type")
    difficulty: str = Field(..., description="Requested difficulty level")
    role: str = Field(..., description="Target role title")
    processing_time_ms: int | None = Field(
        default=None,
        description="Execution duration in milliseconds",
    )


# ============================================================================
# Phase 8: Interview State Management & Live Session Schemas
# ============================================================================

InterviewSessionStatus = Literal["not_started", "active", "completed", "abandoned"]


class InterviewAnswerRecord(BaseModel):
    """
    Stable record representing an answered or skipped interview question.
    Guarantees no duplicate records per question ID.
    """
    question_id: str = Field(..., description="Unique question ID matching GeneratedQuestion.id")
    question: str = Field(..., description="The interview question text")
    answer: str = Field(default="", description="The candidate's submitted answer text")
    started_at: int = Field(..., description="Timestamp in milliseconds when candidate viewed question")
    submitted_at: int = Field(..., description="Timestamp in milliseconds when answer was submitted or skipped")
    skipped: bool = Field(default=False, description="Whether question was skipped without an answer")
    timed_out: bool = Field(default=False, description="Whether question timed out")
    time_spent: int = Field(default=0, ge=0, description="Total seconds spent on this question")
    evaluation: dict | None = Field(default=None, description="Optional evaluation record")
    feedback: dict | None = Field(default=None, description="Optional feedback record")


class InterviewProgressStats(BaseModel):
    """
    Derived progress metrics calculated dynamically from session state.
    """
    current_question_index: int = Field(..., ge=0)
    current_question_number: int = Field(..., ge=1)
    total_questions: int = Field(..., ge=0)
    answered_count: int = Field(..., ge=0)
    skipped_count: int = Field(..., ge=0)
    remaining_count: int = Field(..., ge=0)
    progress_percent: int = Field(..., ge=0, le=100)


class InterviewSessionState(BaseModel):
    """
    Full interview session state supporting client-server synchronization,
    refresh recovery, question navigation, and progress tracking.
    """
    session_id: str = Field(..., description="Stable unique session identifier")
    created_at: int = Field(default_factory=lambda: int(time.time() * 1000), description="Timestamp in ms when session was created")
    started_at: int = Field(default_factory=lambda: int(time.time() * 1000), description="Timestamp in ms when interview began")
    status: InterviewSessionStatus = Field(default="active", description="Current session status")
    questions: list[GeneratedQuestion] = Field(
        default_factory=list,
        description="Persisted list of personalized questions from Phase 7",
    )
    current_question_index: int = Field(
        default=0,
        ge=0,
        description="Zero-based index of current question",
    )
    answers: list[InterviewAnswerRecord] = Field(
        default_factory=list,
        description="List of submitted or skipped answer records (one per question)",
    )
    skipped_questions: list[str] = Field(
        default_factory=list,
        description="List of skipped question IDs",
    )
    current_question_started_at: int = Field(
        default_factory=lambda: int(time.time() * 1000),
        description="Timestamp in ms when current question was started/restored",
    )
    completed_at: int | None = Field(
        default=None,
        description="Timestamp in ms when interview completed",
    )
    interview_config: dict = Field(
        default_factory=dict,
        description="Configuration metadata (role, difficulty, interview_type, mode)",
    )

    @field_validator("current_question_index", mode="before")
    @classmethod
    def validate_index_bounds(cls, v: int) -> int:
        if isinstance(v, int) and v < 0:
            return 0
        return v

    def get_current_question(self) -> GeneratedQuestion | None:
        """Returns the current question object or None if out of bounds."""
        if 0 <= self.current_question_index < len(self.questions):
            return self.questions[self.current_question_index]
        return None

    def add_or_update_answer(
        self,
        question_id: str,
        answer_text: str,
        submitted_at: int,
        started_at: int | None = None,
        time_spent: int = 0,
        evaluation: dict | None = None,
        feedback: dict | None = None,
    ) -> InterviewAnswerRecord:
        """
        Idempotently adds or updates an answer record for a question ID.
        Prevents duplicate answer entries for the same question.
        """
        target_q = None
        for q in self.questions:
            if q.id == question_id:
                target_q = q
                break

        question_text = target_q.question if target_q else ""
        effective_started_at = started_at or self.current_question_started_at

        # If question was in skipped_questions, remove it
        if question_id in self.skipped_questions:
            self.skipped_questions.remove(question_id)

        new_record = InterviewAnswerRecord(
            question_id=question_id,
            question=question_text,
            answer=answer_text,
            started_at=effective_started_at,
            submitted_at=submitted_at,
            skipped=False,
            timed_out=False,
            time_spent=max(0, time_spent),
            evaluation=evaluation,
            feedback=feedback,
        )

        for i, existing in enumerate(self.answers):
            if existing.question_id == question_id:
                self.answers[i] = new_record
                return new_record

        self.answers.append(new_record)
        return new_record

    def skip_question(
        self,
        question_id: str,
        submitted_at: int,
        started_at: int | None = None,
        time_spent: int = 0,
        timed_out: bool = False,
    ) -> InterviewAnswerRecord:
        """
        Idempotently marks a question as skipped.
        Prevents duplicate answer records and duplicate skipped_questions entries.
        """
        target_q = None
        for q in self.questions:
            if q.id == question_id:
                target_q = q
                break

        question_text = target_q.question if target_q else ""
        effective_started_at = started_at or self.current_question_started_at

        if question_id not in self.skipped_questions:
            self.skipped_questions.append(question_id)

        skip_record = InterviewAnswerRecord(
            question_id=question_id,
            question=question_text,
            answer="",
            started_at=effective_started_at,
            submitted_at=submitted_at,
            skipped=True,
            timed_out=timed_out,
            time_spent=max(0, time_spent),
            evaluation={"score": 0, "technicalAccuracy": 0, "clarity": 0, "depth": 0},
            feedback=None,
        )

        for i, existing in enumerate(self.answers):
            if existing.question_id == question_id:
                self.answers[i] = skip_record
                return skip_record

        self.answers.append(skip_record)
        return skip_record

    def advance_question(self, timestamp: int) -> bool:
        """
        Advances to the next question if available.
        Updates current_question_index and current_question_started_at.
        Returns True if advanced, False if already at or beyond the last question.
        """
        if self.current_question_index < len(self.questions) - 1:
            self.current_question_index += 1
            self.current_question_started_at = timestamp
            return True
        return False

    def complete_session(self, timestamp: int) -> None:
        """Marks the session as completed and sets completed_at."""
        self.status = "completed"
        self.completed_at = timestamp

    def get_progress(self) -> InterviewProgressStats:
        """Calculates current dynamic progress metrics."""
        total = len(self.questions)
        answered = len([a for a in self.answers if not a.skipped])
        skipped = len(self.skipped_questions)
        processed = len(self.answers)
        remaining = max(0, total - processed)
        percent = round((processed / total) * 100) if total > 0 else 0

        return InterviewProgressStats(
            current_question_index=self.current_question_index,
            current_question_number=min(self.current_question_index + 1, total) if total > 0 else 1,
            total_questions=total,
            answered_count=answered,
            skipped_count=skipped,
            remaining_count=remaining,
            progress_percent=min(100, percent),
        )

    @classmethod
    def restore_safely(cls, data: dict) -> "InterviewSessionState | None":
        """
        Safely validates and restores session state from serialized dictionary.
        Returns None if data is malformed without throwing unhandled exceptions.
        """
        if not isinstance(data, dict):
            return None
        try:
            # Ensure required questions list is present
            if "questions" not in data or not isinstance(data["questions"], list) or len(data["questions"]) == 0:
                return None
            idx = data.get("current_question_index", 0)
            if idx < 0:
                data["current_question_index"] = 0
            elif idx >= len(data["questions"]):
                data["current_question_index"] = max(0, len(data["questions"]) - 1)
            return cls(**data)
        except Exception:
            return None
