"""
Prompt templates and builders for Job Description Processing with Qwen3.
"""

import re

MAX_JD_PROMPT_CHARS = 12000

JOB_EXTRACTION_SYSTEM_INSTRUCTION = """You are an expert technical job description analyzer.
Extract the structured job profile from the provided job description into a valid JSON object with EXACTLY these keys:
- role_title: string (the advertised job or position title, e.g. "Software Engineer", "Frontend Engineer", "Java Developer". If not stated, return "Not specified")
- experience_level: string (extract the required experience stated in the text, e.g. "Fresher / 0-2 years", "0-2 years", "3+ years". If no experience requirement is mentioned anywhere in the text, return "Not specified")
- required_skills: list of strings (technologies, programming languages, frameworks, libraries, databases, cloud platforms, tools explicitly listed as mandatory or required)
- good_to_have_skills: list of strings (skills listed under nice-to-have, preferred, bonus, optional, or plus. If none, return empty list [])

Strict Extraction Rules:
1. Only extract skills explicitly supported by the supplied JD. Do not infer technologies based on the job title or common industry expectations.
2. If the text specifies experience (e.g. 'Experience: Fresher / 0-2 years', '0-2 years', '3+ years', 'Entry level'), extract it into experience_level. Only return 'Not specified' if no experience is stated anywhere in the text.
3. Keep skill names concise, standardized, and readable (e.g. "Java", "Spring Boot", "PostgreSQL", "Docker", "AWS").
4. Deduplicate skills in both lists.
5. If a skill appears in required_skills, do NOT put it in good_to_have_skills.
6. Return ONLY the valid JSON object with nothing else."""


def extract_relevant_jd_sections(job_text: str, max_chars: int = MAX_JD_PROMPT_CHARS) -> str:
    """
    For oversized JDs exceeding practical context limits, preserve relevant
    sections (title, requirements, qualifications, skills, responsibilities,
    experience) instead of blindly truncating at the end.

    For normal-sized JDs, returns the full text without modification.
    """
    text = (job_text or "").strip()
    if len(text) <= max_chars:
        return text

    # Section patterns for relevant JD sections
    section_pattern = re.compile(
        r"(?:^|\n)(?P<header>(?:#{1,4}\s*)?(?:requirements|qualifications|required\s+skills|"
        r"preferred\s+skills|nice\s+to\s+have|bonus|responsibilities|experience|about\s+the\s+role|"
        r"what\s+you(?:'ll|\s+will)\s+do|what\s+we(?:'re|\s+are)\s+looking\s+for|what\s+you\s+bring|"
        r"technical\s+skills|minimum\s+qualifications|preferred\s+qualifications)[^\n:]*[:]?)(?P<body>[\s\S]*?)(?=(?:\n(?:#{1,4}\s*)?[A-Z][A-Za-z\s]{2,30}:?|\Z))",
        re.IGNORECASE,
    )

    matches = list(section_pattern.finditer(text))

    # Always keep the opening portion (first ~1000 characters) containing role title and company overview
    opening = text[:1000].strip()
    collected_sections = [opening]
    current_length = len(opening)

    if matches:
        for match in matches:
            sec_text = (match.group("header") + "\n" + match.group("body")).strip()
            if current_length + len(sec_text) + 2 < max_chars:
                collected_sections.append(sec_text)
                current_length += len(sec_text) + 2
            else:
                # Add partial section if room exists
                remaining = max_chars - current_length - 50
                if remaining > 200:
                    collected_sections.append(sec_text[:remaining] + "\n[... truncated section ...]")
                break
        return "\n\n".join(collected_sections)

    # Fallback if no matching section headers found
    return text[:max_chars] + "\n\n[... Note: Remaining text truncated for context limit ...]"


def build_job_extraction_prompt(job_text: str) -> str:
    """
    Build a structured extraction prompt for Qwen3 from raw job description text.

    Parameters
    ----------
    job_text : str
        The raw or normalized job description text.

    Returns
    -------
    str
        Full prompt ready to be dispatched to Ollama.
    """
    processed_text = extract_relevant_jd_sections(job_text)

    return (
        f"{JOB_EXTRACTION_SYSTEM_INSTRUCTION}\n\n"
        f"--- JOB DESCRIPTION TEXT ---\n"
        f"{processed_text}\n"
        f"--- END JOB DESCRIPTION TEXT ---\n\n"
        f"JSON:"
    )
