import asyncio, json, logging
from unittest.mock import patch
from app.services import adaptive_interviewer as e
from app.schemas.adaptive import AdaptiveEvaluationInput
from app.services.question_policy import category_matches, is_opening, semantic_duplicate
logging.basicConfig(level=logging.INFO)
q='Can you share a specific time when you had to resolve a disagreement with a teammate during a project?'
original=e.llm_service.generate_json_response
async def observed(**kwargs):
    result=await original(**kwargs)
    text=result.get('question','')
    print(json.dumps({'generated':result,'category_ok':category_matches(text,'HR'),'opening':is_opening(text),'lexical_duplicate':e.is_duplicate_question(text,[q]),'semantic_duplicate':semantic_duplicate(text,[q])}),flush=True)
    return result
async def main():
    with patch.object(e.llm_service,'generate_json_response',observed):
        try:
            result=await e.generate_single_next_question(decision='RECOVERY_QUESTION',stage='BEHAVIORAL',target_skill='Teamwork and disagreement',target_concept='Teamwork and disagreement',difficulty='Easy',category='HR',role='Software Engineer',previous_question=q,candidate_answer="I don't know",question_history=[q],evaluation=AdaptiveEvaluationInput(score=0,technicalAccuracy=0,relevance=0,depth=0,clarity=0,answer_status='NON_ANSWER'))
            print(result)
        except Exception:
            logging.exception('synthetic_reproduction_failed')
asyncio.run(main())
