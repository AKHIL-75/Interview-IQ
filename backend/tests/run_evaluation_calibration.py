"""Opt-in real local Qwen experiment using synthetic answers; never writes DB rows."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.schemas.evaluation import AnswerEvaluationRequest
from app.services.evaluator import evaluate_candidate_answer


async def main():
    output = Path(sys.argv[1])
    evaluate = evaluate_candidate_answer
    if '--before' in sys.argv:
        # Load the captured pre-change implementation only for this isolated experiment.
        snapshots = Path(__file__).resolve().parents[2] / 'docs/evaluation-calibration'
        prompt_namespace, evaluator_namespace = {}, {}
        exec(compile((snapshots / 'prompt-before.txt').read_text(encoding='utf-8-sig'), 'baseline_prompt', 'exec'), prompt_namespace)
        exec(compile((snapshots / 'evaluator-before.txt').read_text(encoding='utf-8-sig'), 'baseline_evaluator', 'exec'), evaluator_namespace)
        evaluator_namespace['build_evaluation_prompt'] = prompt_namespace['build_evaluation_prompt']
        evaluate = evaluator_namespace['evaluate_candidate_answer']
    cases = json.loads(Path(__file__).with_name("fixtures").joinpath("evaluation_calibration.json").read_text())
    results = []
    for case in cases:
        request = AnswerEvaluationRequest(**{k: v for k, v in case.items() if k != "id"}, job_title="Entry-level Software Engineer")
        try:
            result = (await evaluate(request)).model_dump()
            results.append({"id": case["id"], "result": result})
            print(case["id"], result["score"], flush=True)
        except Exception as exc:
            results.append({"id": case["id"], "error_type": type(exc).__name__})
            print(case["id"], type(exc).__name__, flush=True)
        output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 1 if any("error_type" in row for row in results) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
