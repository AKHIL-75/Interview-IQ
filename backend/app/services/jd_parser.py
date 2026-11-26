"""
Job Description Parser Service — Normalizes JD text and extracts structured
skills and requirements using local Qwen3 inference via Ollama.
"""
from app.services import llm_usage


import re
from app.prompts.job_prompts import build_job_extraction_prompt
from app.schemas.job import JobProfile
from app.services import llm_service


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MIN_JD_LENGTH = 15
MAX_JD_LENGTH = 50000


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------

class JDParserError(Exception):
    """Base exception for job description parsing errors."""
    pass


class EmptyJDError(JDParserError):
    """Raised when job description text is empty or whitespace-only."""
    pass


class JDTooShortError(JDParserError):
    """Raised when job description text is too short to be meaningful."""
    pass


class JDTooLargeError(JDParserError):
    """Raised when job description text exceeds the maximum character threshold."""
    pass


# ---------------------------------------------------------------------------
# Normalization & Validation
# ---------------------------------------------------------------------------

def normalize_jd_text(text: str) -> str:
    """
    Normalize raw job description text without stripping semantic content.

    - Unifies line breaks (\r\n -> \n, \r -> \n)
    - Normalizes unicode dashes (en-dash, em-dash) and quotes to ASCII
    - Strips non-printable control characters
    - Normalizes internal tabs/multiple spaces
    - Collapses excessive blank lines (3+ into 2)
    - Trims leading/trailing whitespace
    """
    if not text:
        return ""

    # Unify line breaks
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Normalize unicode dashes and quotes
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')

    # Remove non-printable control characters except \n and \t
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)

    # Clean trailing whitespace on lines and collapse multiple inline spaces/tabs
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.split("\n")]
    text = "\n".join(lines)

    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def validate_jd_text(raw_text: str) -> str:
    """
    Validate raw job description input.

    Raises
    ------
    EmptyJDError
        If text is missing or contains only whitespace.
    JDTooShortError
        If text contains fewer than MIN_JD_LENGTH non-whitespace characters.
    JDTooLargeError
        If text length exceeds MAX_JD_LENGTH characters.
    """
    if not raw_text or not raw_text.strip():
        raise EmptyJDError("Job description text cannot be empty or contain only whitespace.")

    normalized = normalize_jd_text(raw_text)

    if len(normalized) < MIN_JD_LENGTH:
        raise JDTooShortError(
            f"Job description is too short ({len(normalized)} chars). "
            f"Please provide at least {MIN_JD_LENGTH} characters of job description text."
        )

    if len(raw_text) > MAX_JD_LENGTH:
        raise JDTooLargeError(
            f"Job description ({len(raw_text)} chars) exceeds maximum allowed {MAX_JD_LENGTH} characters."
        )

    return normalized


def normalize_job_keys(data: dict) -> dict:
    """
    Map common LLM synonym keys to JobProfile schema keys.
    """
    normalized = dict(data)

    # Role Title mapping
    if "role_title" not in normalized or not normalized["role_title"]:
        for alias in ("title", "job_title", "position", "position_title", "role"):
            if alias in normalized and normalized[alias]:
                normalized["role_title"] = str(normalized[alias]).strip()
                break

    # Required Skills mapping
    if "required_skills" not in normalized or not normalized["required_skills"]:
        for alias in ("skills", "mandatory_skills", "requirements", "core_skills", "technical_skills", "must_have_skills"):
            if alias in normalized and isinstance(normalized[alias], (list, str)):
                normalized["required_skills"] = normalized[alias]
                break

    # Good to have skills mapping
    if "good_to_have_skills" not in normalized or not normalized["good_to_have_skills"]:
        for alias in ("preferred_skills", "nice_to_have_skills", "bonus_skills", "optional_skills", "nice_to_have"):
            if alias in normalized and isinstance(normalized[alias], (list, str)):
                normalized["good_to_have_skills"] = normalized[alias]
                break

    # Experience Level mapping
    if "experience_level" not in normalized or not normalized["experience_level"]:
        for alias in ("experience", "years_of_experience", "experience_required", "experience_years", "level"):
            if alias in normalized and normalized[alias] is not None:
                normalized["experience_level"] = str(normalized[alias]).strip()
                break

    return normalized


# ---------------------------------------------------------------------------
# Public Parsing Pipeline
# ---------------------------------------------------------------------------

@llm_usage.operation("jd_parse")
async def parse_job_description(raw_text: str) -> tuple[JobProfile, str]:
    """
    Validate, normalize, and extract structured JobProfile from raw JD text.

    Parameters
    ----------
    raw_text : str
        The raw job description entered by the user.

    Returns
    -------
    tuple[JobProfile, str]
        A tuple of (validated JobProfile, normalized_text).

    Raises
    ------
    EmptyJDError, JDTooShortError, JDTooLargeError
        Validation errors for improper input.
    OllamaConnectionError, OllamaTimeoutError, LLMResponseParseError, LLMServiceError
        Exceptions propagated from llm_service for caller handling.
    """
    normalized_text = validate_jd_text(raw_text)

    prompt = build_job_extraction_prompt(normalized_text)

    # Run Qwen3 inference with task-tuned parameters (num_predict=300 per Phase 3 baseline)
    llm_output = await llm_service.generate_json_response(
        prompt=prompt,
        think=False,
        num_predict=300,
        temperature=0.1,
    )

    cleaned_dict = normalize_job_keys(llm_output)
    job_profile = JobProfile(**cleaned_dict)

    return job_profile, normalized_text
