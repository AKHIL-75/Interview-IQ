"""
Pydantic schemas for Phase 4: Resume Processing & Parsing.
"""

from pydantic import BaseModel, Field, field_validator


class CandidateProject(BaseModel):
    """Structured representation of a project listed on a resume."""
    name: str = Field(..., description="Project title or name")
    description: str = Field(default="", description="Brief overview of project scope, problem, and achievements")
    technologies: list[str] = Field(default_factory=list, description="Technologies, libraries, or tools used")

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v: str) -> str:
        return str(v).strip() if v else "Untitled Project"

    @field_validator("description", mode="before")
    @classmethod
    def clean_description(cls, v: str) -> str:
        return str(v).strip() if v else ""

    @field_validator("technologies", mode="before")
    @classmethod
    def clean_technologies(cls, v) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            v = [t.strip() for t in v.split(",") if t.strip()]
        # Deduplicate while preserving order
        seen = set()
        cleaned = []
        for item in v:
            item_str = str(item).strip()
            if item_str and item_str.lower() not in seen:
                seen.add(item_str.lower())
                cleaned.append(item_str)
        return cleaned


class CandidateProfile(BaseModel):
    """
    Structured candidate profile extracted from a resume.
    """
    candidate_name: str = Field(
        default="Unknown",
        description="Full name of the candidate or 'Unknown' if not clearly identified"
    )
    extracted_skills: list[str] = Field(
        default_factory=list,
        description="List of technical and domain skills, tools, and frameworks"
    )
    experience_years: float = Field(
        default=0.0,
        ge=0.0,
        description="Estimated total professional experience in years (0 for freshers/students)"
    )
    key_projects: list[CandidateProject] = Field(
        default_factory=list,
        description="Key engineering or academic projects mentioned in the resume"
    )

    @field_validator("candidate_name", mode="before")
    @classmethod
    def clean_candidate_name(cls, v: str) -> str:
        if not v or not str(v).strip():
            return "Unknown"
        s = str(v).strip()
        if ":" in s:
            s = s.split(":")[0].strip()
        if "\n" in s:
            s = s.split("\n")[0].strip()
        return s or "Unknown"

    @field_validator("experience_years", mode="before")
    @classmethod
    def clean_experience_years(cls, v) -> float:
        if v is None:
            return 0.0
        try:
            val = float(v)
            return max(0.0, val)
        except (ValueError, TypeError):
            return 0.0

    @field_validator("extracted_skills", mode="before")
    @classmethod
    def clean_extracted_skills(cls, v) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            v = [s.strip() for s in v.split(",") if s.strip()]
        seen = set()
        cleaned = []
        for item in v:
            item_str = str(item).strip()
            if item_str and item_str.lower() not in seen:
                seen.add(item_str.lower())
                cleaned.append(item_str)
        return cleaned


class ResumeParseResponse(BaseModel):
    """
    API response schema returned by POST /api/v1/resume/parse.
    """
    success: bool = Field(default=True, description="Indicates successful parsing and extraction")
    filename: str = Field(..., description="Original filename of the uploaded resume")
    file_type: str = Field(..., description="Normalized file format: 'pdf' or 'docx'")
    raw_text_length: int = Field(..., description="Character count of raw extracted text")
    candidate_profile: CandidateProfile = Field(..., description="Structured candidate profile")
    processing_time_ms: int | None = Field(default=None, description="Total backend processing time in milliseconds")
    resume_id: str | None = Field(default=None, description="Persisted resume UUID in Supabase public.resumes")
