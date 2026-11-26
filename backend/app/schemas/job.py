"""
Pydantic schemas for Phase 5: Job Description Processing & Skill Extraction.
"""

import re
from pydantic import BaseModel, Field, field_validator
from app.schemas.request import RequestModel


class JobProfile(BaseModel):
    """
    Structured job profile extracted from a job description.
    """
    role_title: str = Field(
        default="Not specified",
        description="Advertised position or role title (e.g. 'Senior Java Developer')",
    )
    required_skills: list[str] = Field(
        default_factory=list,
        description="Explicitly required or strongly mandatory technical skills, languages, frameworks, tools",
    )
    good_to_have_skills: list[str] = Field(
        default_factory=list,
        description="Preferred, bonus, or nice-to-have skills explicitly mentioned",
    )
    experience_level: str = Field(
        default="Not specified",
        description="Explicit experience requirement statement (e.g. '0-2 years', '3+ years', 'Fresher') or 'Not specified'",
    )

    @field_validator("role_title", mode="before")
    @classmethod
    def clean_role_title(cls, v: str) -> str:
        if not v or not str(v).strip():
            return "Not specified"
        s = str(v).strip()
        # Clean quotes, trailing punctuation
        s = s.strip('"\'`')
        if "\n" in s:
            s = s.split("\n")[0].strip()
        return s or "Not specified"

    @field_validator("experience_level", mode="before")
    @classmethod
    def clean_experience_level(cls, v: str) -> str:
        if not v or not str(v).strip():
            return "Not specified"
        s = str(v).strip().strip('"\'`')
        if "\n" in s:
            s = s.split("\n")[0].strip()
        return s or "Not specified"

    @field_validator("required_skills", mode="before")
    @classmethod
    def clean_required_skills(cls, v) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            v = [s.strip() for s in v.split(",") if s.strip()]
        seen = set()
        cleaned = []
        for item in v:
            item_str = str(item).strip().strip('"\'`')
            if item_str and item_str.lower() not in seen:
                seen.add(item_str.lower())
                cleaned.append(item_str)
        return cleaned

    @field_validator("good_to_have_skills", mode="before")
    @classmethod
    def clean_good_to_have_skills(cls, v, info) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            v = [s.strip() for s in v.split(",") if s.strip()]
        
        # Also check against required_skills already cleaned in the same model if available
        existing_required = set()
        if info.data and "required_skills" in info.data:
            existing_required = {s.lower() for s in info.data["required_skills"]}

        seen = set()
        cleaned = []
        for item in v:
            item_str = str(item).strip().strip('"\'`')
            low = item_str.lower()
            if item_str and low not in seen and low not in existing_required:
                seen.add(low)
                cleaned.append(item_str)
        return cleaned


class JobParseRequest(RequestModel):
    """
    Request payload for POST /api/v1/job/parse.
    """
    text: str = Field(
        ...,
        description="Raw job description text entered or pasted by the user",
        min_length=1,
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Job description text cannot be empty or contain only whitespace.")
        if len(v.strip()) < 10:
            raise ValueError("Job description text is too short to be a valid posting.")
        if len(v) > 50000:
            raise ValueError("Job description exceeds maximum allowed length of 50,000 characters.")
        return v


class JobParseResponse(BaseModel):
    """
    Response schema for POST /api/v1/job/parse.
    """
    success: bool = Field(default=True, description="Indicates successful parsing and extraction")
    raw_text_length: int = Field(..., description="Character count of raw input text")
    job_profile: JobProfile = Field(..., description="Structured job requirements profile")
    processing_time_ms: int | None = Field(default=None, description="Total backend processing time in milliseconds")
    job_description_id: str | None = Field(default=None, description="Persisted job description UUID in Supabase public.job_descriptions")
