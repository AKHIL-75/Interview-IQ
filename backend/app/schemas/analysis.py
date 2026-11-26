"""
Pydantic schemas for Phase 6: Semantic Matching & Gap Analysis.
"""

from pydantic import BaseModel, Field
from app.schemas.request import RequestModel
from app.schemas.resume import CandidateProfile
from app.schemas.job import JobProfile


class SkillMatchItem(BaseModel):
    """
    Represents an individual matched skill between the JD and candidate resume.
    """
    required_skill: str = Field(..., description="Target skill from the job description")
    candidate_skill: str = Field(..., description="Best matching skill from the candidate's resume")
    similarity: float = Field(..., description="Cosine similarity score (0.00 to 1.00)")
    category: str = Field(..., description="Skill priority category: 'required' or 'preferred'")
    status: str = Field(default="explicit_match", description="Match classification: explicit_match, covered_through_parent, covered_through_alias, covered_semantically")
    parent_skill: str | None = Field(default=None, description="Parent concept name if covered through parent")
    evidence: str | None = Field(default=None, description="Explanation of evidence or relationship")


class SkillGapItem(BaseModel):
    """
    Represents a missing skill requirement from the job description.
    """
    skill: str = Field(..., description="Missing or unmatched job requirement")
    category: str = Field(..., description="Skill priority category: 'required' or 'preferred'")
    reason: str = Field(
        default="No sufficiently similar candidate skill found",
        description="Reason why the skill was classified as a gap",
    )
    status: str = Field(default="true_gap", description="Classification: true_gap or not_explicitly_evidenced")


class RequirementCheckItem(BaseModel):
    """
    Item for the UI Job Requirements checklist.
    """
    text: str = Field(..., description="Requirement description or skill name")
    matched: bool = Field(..., description="True if candidate possesses this skill or semantic equivalent")
    matched_with: str | None = Field(default=None, description="Candidate skill that satisfied this requirement")
    similarity: float | None = Field(default=None, description="Similarity score of the match if found")
    status: str = Field(default="explicit_match", description="Evidence status of this requirement item")


class MatchAnalysisRequest(RequestModel):
    """
    Request payload for POST /api/v1/analysis/match.
    Consumes CandidateProfile (Phase 4) and JobProfile (Phase 5).
    """
    candidate_profile: CandidateProfile = Field(
        ...,
        description="Candidate profile extracted from resume in Phase 4",
    )
    job_profile: JobProfile = Field(
        ...,
        description="Job profile extracted from job description in Phase 5",
    )
    threshold: float = Field(
        default=0.60,
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold above which a skill is classified as matched",
    )


class MatchAnalysisSummary(BaseModel):
    """
    Summary breakdown of the match calculation.
    """
    total_required: int
    matched_required: int
    total_preferred: int
    matched_preferred: int
    total_candidate_skills: int
    required_coverage: float
    preferred_coverage: float
    threshold_used: float


class MatchAnalysisResponse(BaseModel):
    """
    Response schema for POST /api/v1/analysis/match.
    """
    success: bool = Field(default=True, description="Indicates successful match analysis")
    match_score: int = Field(..., ge=0, le=100, description="Overall match score from 0 to 100")
    matched_skills: list[SkillMatchItem] = Field(default_factory=list, description="Matched required skills")
    skill_gaps: list[SkillGapItem] = Field(default_factory=list, description="Unmatched required skills (TRUE GAPS ONLY)")
    preferred_matches: list[SkillMatchItem] = Field(default_factory=list, description="Matched preferred/good-to-have skills")
    preferred_gaps: list[SkillGapItem] = Field(default_factory=list, description="Unmatched preferred/good-to-have skills")
    
    # UI-convenience fields for seamless integration with existing components
    skills_found: list[str] = Field(default_factory=list, description="List of all explicitly or directly matched skill names")
    covered_through_parent: list[str] = Field(default_factory=list, description="List of skills covered through parent concepts (e.g. Polymorphism via OOP)")
    not_explicitly_evidenced: list[str] = Field(default_factory=list, description="Sub-skills under a known parent not explicitly evidenced in resume")
    gap_skills: list[str] = Field(default_factory=list, description="List of all TRUE missing skill gaps only for SkillBadge display")
    requirements: list[RequirementCheckItem] = Field(default_factory=list, description="Checklist items for Job Requirements card")
    requirement_groups: list[dict] = Field(default_factory=list, description="Normalized requirement groups and their coverage status")
    
    summary: MatchAnalysisSummary = Field(..., description="Quantitative summary of coverage metrics")
    processing_time_ms: int | None = Field(default=None, description="Backend analysis execution time in milliseconds")
