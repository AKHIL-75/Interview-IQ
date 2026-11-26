"""Ground project questions before they become the saved, visible and spoken text."""
import re

PLACEHOLDERS = {"", "unknown", "untitled project", "key project", "project", "project experience", "n/a", "none"}
FOLLOW_UPS = {"TARGETED_FOLLOW_UP", "DEEPER_CHALLENGE", "RECOVERY_QUESTION"}


def named_projects(projects):
    result = []
    for value in projects or []:
        value = value.model_dump() if hasattr(value, "model_dump") else value
        value = {"name": value} if isinstance(value, str) else value
        if not isinstance(value, dict):
            continue
        name = str(value.get("name") or "").strip()
        if name.casefold() not in PLACEHOLDERS:
            result.append({**value, "name": name})
    return result


def mentions(text, name):
    return bool(re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text or "", re.I))


def resolve_project(projects, *, topic="", previous_question="", candidate_answer="", active_project=None, follow_up=False):
    """Resolve only supplied names. Ambiguous conversation must not select project #1."""
    projects = named_projects(projects)
    if follow_up:
        # A candidate may explicitly move from the planned project to another.
        for text in (candidate_answer, previous_question, topic):
            matches = [p for p in projects if mentions(text, p["name"])]
            if matches:
                return matches[0] if len(matches) == 1 else None
        return None
    matches = [p for p in projects if mentions(topic, p["name"])]
    if matches:
        return matches[0] if len(matches) == 1 else None
    active = named_projects([active_project])
    if active:
        matches = [p for p in projects if p["name"].casefold() == active[0]["name"].casefold()]
        if len(matches) == 1:
            return matches[0]
    return projects[0] if len(projects) == 1 else None


def refers_to_project(text):
    return bool(re.search(
        r"\b(?:your|the|that|this)\s+(?:specific\s+|own\s+)?(?:project|platform|application|app|system|contribution|implementation)\b|"
        r"\b(?:did|have)\s+you\s+(?:personally\s+)?(?:build|built|implement|implemented|design|designed|choose|chosen|contribute|contributed)\b",
        text or "", re.I))


def explicit_project_question(text, project=None, *, required=False, category="Technical"):
    """Add only a supplied identity; never fabricate a feature or contribution."""
    if not text:
        return text
    if not required and project is None:
        return text  # No project scope: "the system" can be a general technical concept.
    if not required and not refers_to_project(text):
        return text
    if (not re.search(r"\b(?:you|your|project|platform|application|contribution)\b", text, re.I)
            and not refers_to_project(text)
            and re.match(r"^(?:what (?:is|are)|how (?:does|do)|define|explain the (?:difference|concept|principle))\b", text, re.I)):
        return text  # A conceptual prerequisite need not be tied to a specific project.
    if not project:
        # Discard unsupported specific claims instead of laundering them through a prefix.
        if category == "HR":
            return "Choose a project you worked on. What was your contribution, and what did you learn from the experience?"
        return "Choose a project you worked on. Can you explain how you implemented one feature and the trade-offs you considered?"
    if mentions(text, project["name"]):
        return text
    question = text[0].lower() + text[1:] if re.match(
        r"^(?:Can|Could|What|How|Why|Describe|Explain|Walk|Tell|Did|Have|Which|When|Where)\b", text) else text
    return f'For your {project["name"]} project, {question}'
