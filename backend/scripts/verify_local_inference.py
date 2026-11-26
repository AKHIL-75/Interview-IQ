"""Opt-in native workflow with real local Qwen and synthetic guest data.

Run from backend: python -m scripts.verify_local_inference
"""
from io import BytesIO
from time import monotonic

from docx import Document
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def main():
    assert settings.LLM_PROVIDER == "ollama" and settings.OLLAMA_MODEL == "qwen3:4b"
    document = Document()
    document.add_paragraph("Robin Sample. Education: BSc Computer Science. Skills: Python, SQL, Java, React.")
    document.add_paragraph("Project: Catalog Search. Implemented a Python search API with SQL indexes and React.")
    fixture = BytesIO()
    document.save(fixture)
    with TestClient(app, headers={"X-Inference-Engine": "local"}) as api:
        def post(path, **kwargs):
            start = monotonic()
            response = api.post(settings.API_V1_PREFIX + path, **kwargs)
            print(path, response.status_code, round(monotonic() - start, 2), "s", flush=True)
            response.raise_for_status()
            return response.json()

        status = api.get(settings.API_V1_PREFIX + "/inference/engines")
        status.raise_for_status()
        assert status.json()["local"] is True
        print("Local engine available", flush=True)
        resume = post("/resume/parse", files={"file": ("synthetic.docx", fixture.getvalue())})
        candidate = resume["candidate_profile"]
        assert resume["raw_text_length"] > 0 and candidate["extracted_skills"]
        job = post("/job/parse", json={"text": "Software engineer building Python APIs and SQL queries. "
                   "Maintain React applications, improve search performance and review Java code."})["job_profile"]
        assert job["required_skills"]
        profiles = {"candidate_profile": candidate, "job_profile": job}
        match = post("/analysis/match", json=profiles)
        questions = post("/interview/generate-questions", json={**profiles, "analysis": match,
                         "question_count": 1})["questions"]
        question = questions[0]
        answer = "I used SQL indexes on the catalog search columns and measured query latency before and after."
        evaluation = post("/evaluation/evaluate", json={"question": question["question"], "candidate_answer": answer})
        assert 0 <= evaluation["score"] <= 100 and evaluation["suggestedAnswer"].strip()
        report = post("/interview/generate-report", json={"questions": questions, "answers": [
            {"questionId": question["id"], "answer": answer, "evaluation": evaluation}]})["report"]
        assert report["question_analysis"][0]["score"] == evaluation["score"]
        print("Verified question, scored answer, reference answer and report preview.", flush=True)


if __name__ == "__main__":
    main()
