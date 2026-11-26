"""Regression checks for request-local Phase 21 optimizations."""
from app.prompts.adaptive_prompts import build_single_question_prompt


def test_adaptive_prompt_removes_only_identical_current_exchange():
    current = dict(question="How did you resolve the disagreement?",
                   answer="I presented both options to my teammate.",
                   evaluation={"answer_status": "CORRECT", "technicalAccuracy": 90})
    earlier = dict(question="What was your role?", answer="I coordinated the team.", evaluation={})
    def prompt(latest):
        return build_single_question_prompt(
            role="Engineer", stage="BEHAVIORAL", target_skill="Teamwork", target_topic="Teamwork",
            target_concept="Resolution", difficulty="Medium", category="HR", previous_question=current["question"],
            candidate_answer=current["answer"], evaluation=current["evaluation"],
            question_history=[earlier["question"], current["question"]], answer_history=[earlier, latest])
    text = prompt(current)
    assert text.count(current['answer']) == 1
    assert earlier['answer'] in text and earlier['question'] in text
    assert 'Earlier, I asked for clarification.' in prompt({**current, 'answer': 'Earlier, I asked for clarification.'})
    assert '"technicalAccuracy": 55' in prompt({**current, 'evaluation': {"technicalAccuracy": 55}})
