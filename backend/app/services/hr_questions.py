"""Behavioral question options tied to the interview plan and the preceding turn."""
import re

from app.services.project_context import mentions
from app.services.question_policy import HR_TOPICS


HR_QUESTIONS = dict(zip(HR_TOPICS, (
    ("Tell me about a disagreement you helped resolve on a team.",
     "When have you worked with a teammate whose way of working was different from yours?"),
    ("Describe a mistake you made and what you learned from it.",
     "When did you take responsibility for a problem that others had overlooked?"),
    ("How have you prioritized tasks when two deadlines conflicted?",
     "How would you balance competing responsibilities if both people requesting your help needed it today?"),
    ("Tell me about a time you received feedback that changed your approach.",
     "When have you given constructive feedback to a teammate?"),
    ("What motivates you to pursue this role?",
     "Which of your career goals would you like to work toward in this role?"),
    ("When did you communicate a difficult decision to a stakeholder?",
     "How have you kept your teammates informed when an important plan changed?"),
    ("What part of a recent project was your responsibility?",
     "Tell me about a challenge you faced while working on a project with other people."),
    ("How did you adapt when your team changed plans at short notice?",
     "What did you adjust when expectations changed during a project?"),
    ("Tell me about a time you showed leadership without a formal title.",
     "What have you learned about leadership from sharing responsibilities on a team?"),
    ("How did you handle a challenge when several priorities competed for your attention?",
     "Tell me about a setback your team faced when its first approach failed."),
    ("What strength do you bring to a team?",
     "Which skill are you working to improve, and what have you tried so far?"),
    ("Tell me about a time you managed pressure when something important was at risk.",
     "How do you respond to pressure when someone is waiting for an update?"),
), strict=True))

_FOLLOW_UP = (
    "In that situation, what did you personally do first?",
    "In that situation, how did you decide what to do next?",
    "In your example, what did you observe after taking action?",
    "In the same situation, what would you change if it happened again?",
    "In that example, what did you find most difficult about your decision?",
    "In that situation, what would you do if your first approach did not work?",
)
_RECOVERY = (
    "In the same situation, what would you do first if you faced it tomorrow?",
    "In that situation, how would you ask for help?",
    "In that situation, how would you tell someone what you need?",
    "In the same situation, what would you do if your initial approach failed?",
    "In that situation, how would you check whether your choice helped?",
)
_REFERENCE = re.compile(
    r"\b(?:in (?:that|the same|your) (?:situation|example)|"
    r"you (?:mentioned|said|described)|that (?:choice|decision|disagreement|approach|feedback)|"
    r"your (?:example|response))\b", re.I,
)
_TEAMWORK = re.compile(
    r"\b(?:team(?:mate|work)?s?|colleagues?|(?:work\w*|collaborat\w*) with (?:others|someone|people))\b",
    re.I,
)
_CONTEXT_STOP = set(
    "about after again before candidate could describe example experience first have happened handle "
    "help how just made more next other over please project really role same situation some tell "
    "than that their them then there these they thing things this time want were what when where "
    "which while will with worked would your yourself decision approach step action".split()
)


def _context_terms(text):
    return {re.sub(r"(?:ing|ed|s)$", "", w) for w in re.findall(r"[a-z]{4,}", text.lower())
            if w not in _CONTEXT_STOP}


def grounded_hr_follow_up(question, previous_question, candidate_answer, project=None, *, recovery=False):
    """Check for conversational references or shared evidence, never labels alone."""
    if not previous_question:
        return False
    if project and mentions(question, project["name"]):
        return True
    context = f"{previous_question} {candidate_answer or ''}"
    if _context_terms(question) & _context_terms(context):
        return True
    if recovery and _TEAMWORK.search(question) and _TEAMWORK.search(previous_question):
        return True  # Recovery may request a simpler example of the same behavior.
    return bool(_REFERENCE.search(question))


def hr_fallback_candidates(topic, decision, previous_question, project):
    """Yield (question, topic) candidates; a follow-up retains its assessment."""
    if previous_question and decision in {"TARGETED_FOLLOW_UP", "RECOVERY_QUESTION", "DEEPER_CHALLENGE"}:
        if decision == "RECOVERY_QUESTION":
            for text in _RECOVERY:
                yield text, topic
            return
        if re.search(r"\b(?:disagree\w*|conflict\w*)\b", previous_question, re.I):
            yield "How did you decide which solution was best for the team?", topic
        for text in _FOLLOW_UP:
            yield text, topic
        return
    if topic == "Project experience" and project:
        yield f"For your {project['name']} project, what was your own responsibility?", topic
    if topic in HR_QUESTIONS:
        for text in HR_QUESTIONS[topic]:
            yield text, topic
    for alternative, questions in HR_QUESTIONS.items():
        if alternative != topic:
            for text in questions:
                yield text, alternative
