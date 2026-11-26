import asyncio, json, logging
from app.services.evaluator import evaluate_candidate_answer
from app.schemas.evaluation import AnswerEvaluationRequest
from app.schemas.adaptive import InterviewStartRequest, AdaptiveNextQuestionRequest
from app.services.adaptive_interviewer import process_adaptive_start, process_adaptive_next_question
from app.services.report_generator import generate_final_report
logging.basicConfig(level=logging.WARNING)
from app.services import llm_service
_original = llm_service.generate_json_response
async def observed(**kwargs):
    output = await _original(**kwargs)
    print(json.dumps({'provider_output': output}), flush=True)
    return output
llm_service.generate_json_response = observed
async def main():
    start=await process_adaptive_start(InterviewStartRequest(interview_type='HR',question_count=5))
    questions=[start.first_question.model_dump()]; answers=[]; plan=start.interview_plan; state=start.interview_state
    for i in range(5):
        q=questions[-1]; text="I don't know" if i else 'I am a software developer who works with Python and SQL and enjoys collaborating on small software projects.'
        ev=await evaluate_candidate_answer(AnswerEvaluationRequest(question=q['question'],candidate_answer=text,category=q['category'],stage=q['stage'],topic=q['topic']))
        assert ev.suggestedAnswer and ev.suggestedAnswer!=q['question'] and ev.suggestedAnswer!=text
        answers.append({'questionId':q['id'],'question':q['question'],'answer':text,'evaluation':ev.model_dump()})
        result=await process_adaptive_next_question(AdaptiveNextQuestionRequest(session_id='synthetic-live',previous_question=q['question'],candidate_answer=text,evaluation=ev.model_dump(),category=q['category'],difficulty=q['difficulty'],current_topic=q['topic'],question_history=[x['question'] for x in questions],answer_history=answers,interview_plan=plan,interview_state=state,consecutive_follow_ups=state.get('consecutive_follow_ups',0)))
        print(json.dumps({'question':q['question'],'score':ev.score,'model_answer':ev.suggestedAnswer,'decision':result.decision}),flush=True)
        plan=result.interview_plan;state=result.interview_state
        if result.end_interview: break
        questions.append(result.question.model_dump())
    assert result.end_interview
    report=generate_final_report('synthetic-live','Engineer','HR','Medium',questions,answers,interview_plan=plan,interview_state=state)
    assert len(report['question_analysis'])==5
    print('PASS: five-question local Ollama interview, evaluations, references and report. Storage and authentication not exercised.',flush=True)
    technical=await evaluate_candidate_answer(AnswerEvaluationRequest(question='What is a SQL index and what are its trade-offs?',candidate_answer='An index stores search keys with row references to speed up queries. It uses extra storage and slows writes because entries must be maintained.',category='Technical'))
    print(json.dumps({'technical_score':technical.score,'technical_reference':technical.suggestedAnswer}),flush=True)
asyncio.run(main())
