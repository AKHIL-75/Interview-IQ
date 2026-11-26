import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

cand = {
    "candidate_name": "Alex Mercer",
    "experience_years": 3,
    "extracted_skills": ["MongoDB", "Node.js", "Express", "RESTful APIs", "React", "JavaScript", "SQL"],
    "key_projects": [
        {
            "name": "Cinemaverse",
            "description": "Movie database web application using MongoDB and Express.",
            "technologies": ["MongoDB", "Express", "React", "Node.js", "RESTful APIs"]
        }
    ]
}

job = {
    "role_title": "Full Stack Developer",
    "experience_level": "Mid-Level (2-4 years)",
    "required_skills": ["MongoDB", "Node.js", "RESTful APIs", "React"],
    "good_to_have_skills": ["Docker", "TypeScript"],
}

def test_cinemaverse_scenarios():
    print("=================================================================")
    print("TESTING INITIAL QUESTION GENERATION FLOW (/interview/generate-questions)")
    print("=================================================================")

    configurations = [
        ("Technical", "Medium", 5),
        ("Technical", "Medium", 10),
        ("Technical", "Medium", 15),
        ("HR", "Medium", 5),
        ("Mixed", "Medium", 5),
    ]

    for itype, diff, count in configurations:
        print(f"\n---> Testing Config: Type={itype}, Difficulty={diff}, Count={count}")
        payload = {
            "candidate_profile": cand,
            "job_profile": job,
            "analysis": None,
            "interview_type": itype,
            "difficulty": diff,
            "question_count": count,
        }
        t0 = time.time()
        res = client.post("/api/v1/interview/generate-questions", json=payload)
        dt = time.time() - t0
        print(f"Status Code: {res.status_code} in {dt:.1f}s")
        assert res.status_code == 200, f"Failed with {res.status_code}: {res.text}"
        data = res.json()
        assert data["success"] is True
        questions = data["questions"]
        assert len(questions) == count, f"Expected {count} questions, got {len(questions)}"
        print(f"PASS: {len(questions)}/{count} valid questions returned.")
        print(f"  [Q1]: {questions[0]['question'][:90]}...")
        print(f"  [Q1 aspects]: {questions[0]['expected_aspects']}")
        # Verify all questions have required fields
        for q in questions:
            assert q["id"]
            assert q["question"] and len(q["question"]) > 10
            assert q["category"] in ("Technical", "HR")
            assert q["topic"]
            assert q["difficulty"] == diff
            assert q["focus"]
            assert isinstance(q["expected_aspects"], list) and len(q["expected_aspects"]) >= 1

    print("\n=================================================================")
    print("ALL INITIAL GENERATION CONFIGURATIONS (5, 10, 15, HR, MIXED) PASSED!")
    print("=================================================================")

if __name__ == "__main__":
    test_cinemaverse_scenarios()
