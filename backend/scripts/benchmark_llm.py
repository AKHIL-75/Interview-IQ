"""Synthetic Phase 18 evidence. Default mode is completely offline.

From backend: .venv/Scripts/python.exe -m scripts.benchmark_llm --output ../docs/openrouter-offline.json
Live: add --live ollama, or --live openrouter with explicit backend cloud opt-in.
No real user content, authentication, database writes, or provider output is saved.
"""
import argparse
import asyncio
from collections import Counter
from contextlib import ExitStack
import io
import json
from pathlib import Path
import time
from unittest.mock import patch

import docx
import httpx

from app.core.config import settings
from app.services import llm_service, llm_usage

REAL_CLIENT = httpx.AsyncClient
PROFILE = dict(candidate_name="Synthetic Candidate", extracted_skills=["Java", "SQL"],
               experience_years=0, key_projects=[])
JOB = dict(role_title="Junior Java Developer",required_skills=["Java","SQL"],
           good_to_have_skills=[],experience_level="Fresher")
RESUME = "Synthetic Candidate\nSkills: Java, SQL\nExperience: Fresher. No professional experience."
JD = "Junior Java Developer. Required: Java and SQL. Experience: Fresher."
REFERENCE = "Illustrative example: I heard both viewpoints, agreed a small trial with the team, and used its outcome to settle priorities."
ANSWER = "I listened to each teammate and proposed a small trial. We agreed priorities and completed the shared task."
HR_QUESTIONS = [
    "Tell me about a disagreement you resolved with a teammate.",
    "How do you prioritize competing deadlines?",
    "What motivates you to apply for this role?",
    "Describe a mistake you made and what you learned from it.",
    "How would you give constructive feedback to a colleague?",
    "What are your career goals for the coming year?",
    "Describe how you supported a teammate who needed help.",
    "How do you handle pressure when several people need your attention?",
    "Tell me about a strength you want to develop further.",
    "When did you adapt your communication to a customer?",
    "How would you respond to criticism from your manager?",
    "What would you do if a colleague disagreed with your priorities?",
    "Describe your contribution to improving team morale.",
    "How do you balance responsibilities when workload changes?",
    "Explain a time you delegated work and supported others.",
    "How would you persuade a stakeholder to try your suggestion?",
    "Describe a setback you faced and the lesson you learned.",
    "How would you resolve conflict between two colleagues?",
    "What attracts you to this company?",
    "How do you handle feedback that you find difficult to accept?",
]
JAVA_QUESTIONS = [
    "How does Java garbage collection identify unreachable objects?",
    "What distinguishes a Java interface from an abstract class?",
    "Explain Java thread synchronization and visibility guarantees.",
    "How does a Java HashMap handle hash collisions?",
    "What is Java exception propagation across method calls?",
    "Explain how Java generics use type erasure.",
    "What trade-offs arise when Java strings are immutable?",
    "How does Java class loading use parent delegation?",
    "What does Java autoboxing do with primitive values?",
    "Explain Java method overload resolution at compile time.",
    "How do Java streams evaluate a lazy pipeline?",
    "What makes a Java resource eligible for try-with-resources?",
    "Describe the Java equals and hashCode contract.",
    "How does Java serialization reconstruct object state?",
    "What are the costs of using Java reflection?",
    "Explain Java enum initialization and identity.",
    "What is a Java lambda capture restriction?",
    "How does Java record equality compare components?",
    "Explain Java modules and exported packages.",
    "What happens when Java integer arithmetic overflows?",
]


def summary(events):
    def total(key):
        return sum(e[key] for e in events) if events and all(e[key] is not None for e in events) else None
    return {"http_inference_attempts": sum(e["http_attempts"] for e in events), "calls_by_operation": dict(Counter(e["operation"] for e in events if e["http_attempts"])),
            "workflow_retries": sum(e["workflow_retry_index"] > 0 for e in events),
            "observed_fallback_responses": sum(e["fallback_observed"] is True for e in events),
            "internal_openrouter_attempts": None, "input_tokens": total("input_tokens"),
            "output_tokens": total("output_tokens"), "cost_usd": total("cost_usd"),
            "usage_complete": bool(events) and all(e["cost_usd"] is not None for e in events),
            "events": events}


async def setup():
    from fastapi import UploadFile
    from app.api.v1.endpoints.resume import parse_resume
    from app.services.jd_parser import parse_job_description
    document=docx.Document(); document.add_paragraph(RESUME)
    buf=io.BytesIO(); document.save(buf); buf.seek(0)
    resume=await parse_resume(file=UploadFile(buf, filename="synthetic.docx"), auth=None)
    job,_=await parse_job_description(JD)
    return resume.candidate_profile, job


class OfflineProvider:
    """Mocks HTTP completions only; all application orchestration runs normally."""
    def __init__(self, subject=None, repairs=False):
        self.questions = iter(JAVA_QUESTIONS if subject else HR_QUESTIONS)
        self.repairs=repairs
        self.failed=set()

    def __call__(self, request):
        operation=llm_usage._operation.get()
        if self.repairs and operation in {"resume_parse", "adaptive_question"} and operation not in self.failed:
            self.failed.add(operation)
            raw="incomplete JSON"
        else:
            if operation=="resume_parse": output=PROFILE
            elif operation=="jd_parse": output=JOB
            elif operation in {"adaptive_question", "initial_question"}: output={"question":next(self.questions),"lead_in":"Let's continue."}
            elif operation=="reference_answer": output={"suggestedAnswer":REFERENCE}
            else:
                output=dict(interpretation=ANSWER, evidence=[ANSWER], central_error=None,
                            answer_status="PARTIAL", technicalAccuracy=65, relevance=80, clarity=80,
                            strengths=["Clear action"], improvements=["Explain the result"],suggestedAnswer="" if self.repairs else REFERENCE)
            raw=json.dumps(output)
        # No synthetic token counts/costs: these are unavailable in offline runs.
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200,json={"model":settings.openrouter_models[-1],"provider":"SyntheticProvider",
                "choices":[{"message":{"content":raw},"finish_reason":"stop"}]})
        return httpx.Response(200,json={"model":settings.OLLAMA_MODEL,"response":raw})


async def workflow(count, subject=None, repairs=False):
    from app.services import adaptive_interviewer as engine
    from app.services.evaluator import evaluate_candidate_answer
    from app.services.report_generator import generate_final_report
    from app.schemas.adaptive import InterviewStartRequest, AdaptiveNextQuestionRequest
    from app.schemas.evaluation import AnswerEvaluationRequest
    candidate,job=await setup()
    started=await engine.process_adaptive_start(InterviewStartRequest(candidate_profile=candidate.model_dump(),job_profile=job.model_dump(),
        interview_type="Technical" if subject else "HR",subject=subject,question_count=count,interview_mode="STATIC"))
    questions=[started.first_question.model_dump()]; answers=[]
    plan,state=started.interview_plan,started.interview_state
    for index in range(count):
        q=questions[-1]
        evaluation=await evaluate_candidate_answer(AnswerEvaluationRequest(question=q["question"],candidate_answer=ANSWER,
            category=q["category"],stage=q["stage"],topic=q["topic"]))
        answers.append(dict(questionId=q["id"],question=q["question"],answer=ANSWER,evaluation=evaluation.model_dump()))
        result=await engine.process_adaptive_next_question(AdaptiveNextQuestionRequest(previous_question=q["question"],
            candidate_answer=ANSWER,evaluation=evaluation.model_dump(),category=q["category"],difficulty=q["difficulty"],
            current_topic=q["topic"],question_history=[x["question"] for x in questions],answer_history=answers,
            interview_plan=plan,interview_state=state,consecutive_follow_ups=state.get("consecutive_follow_ups",0)))
        plan,state=result.interview_plan,result.interview_state
        if result.end_interview: break
        questions.append(result.question.model_dump())
    report=generate_final_report("synthetic-benchmark","Engineer","Technical" if subject else "HR","Medium",
        questions,answers,interview_plan=plan,interview_state=state)
    assert result.end_interview and len(answers)==count and len(report["question_analysis"])==count
    return {"completed_interviews":1,"answered_questions":len(answers),"report_rows":len(report["question_analysis"])}


async def offline_workflow(count, subject=None, repairs=False, provider_name="ollama"):
    from app.services import adaptive_interviewer as engine
    with ExitStack() as stack:
        stack.enter_context(patch.object(settings,"LLM_PROVIDER",provider_name))
        stack.enter_context(patch.object(llm_service.httpx,"AsyncClient",side_effect=lambda **kw:
            REAL_CLIENT(transport=httpx.MockTransport(provider),**kw)))
        # Isolate MiniLM embeddings, which do not make LLM inference requests.
        stack.enter_context(patch.object(engine,"prepare_semantic_history",return_value=None))
        stack.enter_context(patch.object(engine,"semantic_duplicate",return_value=False))
        provider=OfflineProvider(subject,repairs)
        with llm_usage.capture_usage() as events:
            completed=await workflow(count,subject,repairs)
            return dict(mode="offline_mock_http",question_count=count,subject=subject,repairs=repairs,**completed,**summary(events))


def check_live_enabled(provider):
    if settings.LLM_PROVIDER != provider:
        raise ValueError("Live provider must match the explicitly configured backend LLM_PROVIDER")
    if provider=="openrouter" and (not settings.OPENROUTER_BENCHMARK_ENABLED or not settings.OPENROUTER_API_KEY.get_secret_value().strip()):
        raise ValueError("Cloud benchmarks require a configured backend key and OPENROUTER_BENCHMARK_ENABLED=true")


async def quality_suite():
    """Fixed acceptance checks, separate from score-calibration or human review."""
    from app.services import adaptive_interviewer as engine
    from app.services.evaluator import evaluate_candidate_answer
    from app.schemas.evaluation import AnswerEvaluationRequest
    from app.schemas.adaptive import AdaptiveEvaluationInput
    tasks=[]
    async def task(name, action, check):
        start=time.perf_counter()
        with llm_usage.capture_usage() as events:
            try:
                value=await action()
                row=dict(task=name,structured_success=True,reference_check=bool(check(value)))
                if name.startswith("evaluation_"): row["score"]=value.score; row["answer_status"]=value.answer_status
            except Exception as exc:
                row=dict(task=name,structured_success=False,reference_check=False,error_type=type(exc).__name__)
            row.update(latency_ms=round((time.perf_counter()-start)*1000,3),**summary(events))
            tasks.append(row)
            print(json.dumps({k:v for k,v in row.items() if k!="events"}),flush=True)
    # Setup runs both real extraction paths; count them independently below.
    from fastapi import UploadFile
    from app.api.v1.endpoints.resume import parse_resume
    from app.services.jd_parser import parse_job_description
    document=docx.Document(); document.add_paragraph(RESUME); buf=io.BytesIO();document.save(buf);buf.seek(0)
    await task("resume_extraction",lambda:parse_resume(UploadFile(buf,filename="synthetic.docx"),auth=None),
        lambda v: {"java","sql"}.issubset({s.lower() for s in v.candidate_profile.extracted_skills}) and v.candidate_profile.experience_years==0)
    await task("jd_extraction",lambda:parse_job_description(JD),lambda v:{"java","sql"}.issubset({s.lower() for s in v[0].required_skills}))
    for name,answer,check in [
        ("correct","Binary search requires sorted data. Compare the target to the middle, discard the half that cannot contain it, and repeat. Time is O(log n).",lambda v:v.score>=70 and v.answer_status in {"CORRECT","PARTIAL"}),
        ("partial","Binary search looks in the middle and narrows the search. I am unsure about its preconditions and complexity.",lambda v:0<v.score<85 and v.answer_status=="PARTIAL"),
        ("irrelevant","I like strawberry ice cream and sunny beaches.",lambda v:v.score==0 and v.answer_status=="IRRELEVANT")]:
        request=AnswerEvaluationRequest(question="What is binary search, when is it applicable, and what is its time complexity?",candidate_answer=answer,category="Technical")
        await task("evaluation_"+name,lambda r=request:evaluate_candidate_answer(r),check)
    await task("initial_question",lambda:engine.generate_single_next_question(decision="NEXT_TOPIC",stage="TECHNICAL_FUNDAMENTALS",
        target_skill="Java",target_concept="Java fundamentals",difficulty="Medium",category="Technical",role="Engineer",subject="Java",q_index=1),
        lambda v:"java" in v[0].question.lower())
    await task("adaptive_followup",lambda:engine.generate_single_next_question(decision="TARGETED_FOLLOW_UP",stage="TECHNICAL_FUNDAMENTALS",
        target_skill="Java",target_concept="Java garbage collection",difficulty="Easy",category="Technical",role="Engineer",subject="Java",
        previous_question="How does Java garbage collection work?",candidate_answer="I am unsure about reachability.",
        evaluation=AdaptiveEvaluationInput(score=30,technicalAccuracy=20,relevance=80,depth=10,clarity=50,answer_status="PARTIAL")),
        lambda v:"java" in v[0].question.lower())
    return tasks


async def main(args):
    if args.live:
        check_live_enabled(args.live)
        # No model mutation or free-to-paid escalation is performed by the harness.
        result={"mode":"live_synthetic","provider":args.live,"requested_models":settings.openrouter_models if args.live=="openrouter" else [settings.OLLAMA_MODEL],
                "warmth":"not controlled; first request may include a cold load","network_latency":"included, not isolated"}
        if args.workflow_count:
            started=time.perf_counter()
            with llm_usage.capture_usage() as events:
                completed=await workflow(args.workflow_count,args.subject)
                result.update(question_count=args.workflow_count,subject=args.subject,**completed,**summary(events),latency_ms=round((time.perf_counter()-started)*1000,3))
        else:
            result["tasks"]=await quality_suite()
    else:
        result={"mode":"offline_mock_http","scenarios":[]}
        for count in (5,10,15):
            for subject,repairs in [(None,False),("Java",False),(None,True)]:
                row=await offline_workflow(count,subject,repairs)
                result["scenarios"].append(row)
                print(json.dumps({k:v for k,v in row.items() if k!="events"}),flush=True)
    Path(args.output).write_text(json.dumps(result,indent=2),encoding="utf-8")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live",choices=["ollama","openrouter"])
    parser.add_argument("--output",default="../docs/openrouter-offline.json")
    parser.add_argument("--workflow-count",type=int,choices=[5,10,15],help="Opt-in live synthetic full workflow instead of quality tasks")
    parser.add_argument("--subject",choices=["Java"],help="Optional subject for a live full workflow")
    args=parser.parse_args()
    asyncio.run(main(args))
