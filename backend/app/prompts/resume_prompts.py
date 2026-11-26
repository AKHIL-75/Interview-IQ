"""
Prompt templates and builders for Resume Profile Extraction with Qwen3.
"""

# Sensible character limit for prompt context (approx. 2,500 words)
# Resumes usually have contact, summary, skills, and projects in the first 10,000 chars.
MAX_RESUME_PROMPT_CHARS = 10000


RESUME_EXTRACTION_SYSTEM_INSTRUCTION = """You are an expert technical resume parser.
Extract the candidate profile from this resume into a valid JSON object with these keys:
- candidate_name: string (full name only, e.g. "Alex Example" or "Jane Doe". If not found, use "Unknown". Do not include job titles, taglines, or sentences)
- extracted_skills: list of strings (up to 30 primary technical skills, programming languages, frameworks, databases, developer tools explicitly mentioned)
- experience_years: float (estimated total years of professional experience, e.g. 2.5. If student, fresher, or unstated, use 0.0)
- key_projects: list of objects (maximum 3 most prominent projects), each with:
    - name: string (project name)
    - description: string (concise one-sentence summary of the project)
    - technologies: list of strings (technologies or tools used)

Rules:
1. Do not invent or assume information not in the resume text.
2. Deduplicate extracted_skills.
3. Keep descriptions concise and avoid repeating phrases or tokens.
4. Return ONLY the valid JSON object."""


def build_resume_extraction_prompt(resume_text: str) -> str:
    """
    Build a structured extraction prompt for Qwen3, applying sensible length truncation.

    Parameters
    ----------
    resume_text : str
        The raw extracted text from PDF or DOCX.

    Returns
    -------
    str
        Full prompt ready to be dispatched to Ollama.
    """
    cleaned = (resume_text or "").strip()
    if len(cleaned) > MAX_RESUME_PROMPT_CHARS:
        cleaned = cleaned[:MAX_RESUME_PROMPT_CHARS] + "\n\n[... Note: Remaining text truncated for processing ...]"

    return (
        f"{RESUME_EXTRACTION_SYSTEM_INSTRUCTION}\n\n"
        f"--- CANDIDATE RESUME TEXT ---\n"
        f"{cleaned}\n"
        f"--- END RESUME TEXT ---\n\n"
        f"JSON:"
    )
