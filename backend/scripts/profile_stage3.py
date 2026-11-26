"""Synthetic, opt-in real Ollama profiling; no credentials, database writes or user answers."""
import asyncio
import json
import time
import sys
from pathlib import Path
from app.services.performance import trace
from app.services.evaluator import evaluate_candidate_answer
from app.services.adaptive_interviewer import generate_single_next_question
from app.schemas.evaluation import AnswerEvaluationRequest
from app.schemas.adaptive import AdaptiveEvaluationInput

TEXT = 'At Quartz Harbor, I used a B-tree index on order_id; the canary phrase is violet comet 47. Reads got faster, while writes required index maintenance.'
QUESTION = 'How does a SQL index work, and what trade-offs does it introduce?'

async def main():
    samples = []
    for index in range(2):
        timing = {'start': time.perf_counter(), 'stages': []}
        token = trace.set(timing)
        try:
            started = time.perf_counter()
            evaluation = await evaluate_candidate_answer(AnswerEvaluationRequest(question=QUESTION, candidate_answer=TEXT, category='Technical', topic='SQL', relevant_skills=['SQL']))
            evaluation_ms = (time.perf_counter() - started) * 1000
            started = time.perf_counter()
            await generate_single_next_question(decision='NEXT_TOPIC', stage='TECHNICAL_FUNDAMENTALS', target_skill='SQL', target_concept='transaction isolation', difficulty='Medium', category='Technical', role='Software Engineer', previous_question=QUESTION, candidate_answer=TEXT, question_history=[QUESTION], evaluation=AdaptiveEvaluationInput(**evaluation.model_dump()), answer_history=[{'question': QUESTION, 'answer': TEXT, 'evaluation': evaluation.model_dump()}])
            sample = {'sample': index + 1, 'evaluation_ms': round(evaluation_ms, 2), 'next_question_ms': round((time.perf_counter()-started)*1000, 2), 'stages': timing['stages'], 'status': 'success'}
        except Exception as error:
            sample = {'sample': index + 1, 'status': type(error).__name__, 'stages': timing['stages']}
        finally:
            trace.reset(token)
        samples.append(sample)
        print(json.dumps(sample), flush=True)
    Path(sys.argv[1]).write_text(json.dumps(samples, indent=2), encoding='utf-8')
    if any(sample['status'] != 'success' for sample in samples): raise SystemExit(1)

if __name__ == '__main__': asyncio.run(main())
