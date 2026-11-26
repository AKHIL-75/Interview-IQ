"""
Comprehensive test suite for Phase 5: Job Description Processing & Skill Extraction.

Covers:
- Test 1: Baseline health check (GET /api/v1/health -> 200 OK)
- Test 2: Input validation: Missing text field -> 422 Unprocessable Entity
- Test 3: Input validation: Empty text string -> 400/422 Bad Request
- Test 4: Input validation: Whitespace-only text -> 400/422 Bad Request
- Test 5: Input validation: Too short text (< 15 chars) -> 422 Unprocessable Entity
- Test 6: Input validation: Oversized text (> 50,000 chars) -> 413/422
- Test 7: Error handling: Ollama unavailable simulation -> 503 Service Unavailable
- Test 8: Error handling: Invalid/malformed LLM JSON simulation -> 502 Bad Gateway
- Test 9: Unit test: Duplicate skills deduplication in JobProfile schema
- Test 10: Unit test: No hallucination & clean normalization of synonym keys
- Test 11: Real Qwen3 End-to-End: Valid JD without explicit experience
- Test 12: Real Qwen3 End-to-End: Valid JD with explicit experience ("0-2 years")
"""

import os
import sys
from unittest.mock import patch

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.services import llm_service
from app.schemas.job import JobProfile
from app.services.jd_parser import normalize_job_keys, normalize_jd_text


def run_all_tests():
    client = TestClient(app)
    print("=================================================================")
    print("STARTING PHASE 5 AUTOMATED TEST SUITE")
    print("=================================================================")

    # -------------------------------------------------------------------------
    # Baseline Check
    # -------------------------------------------------------------------------
    print("\n[TEST 1] GET /api/v1/health...")
    res = client.get("/api/v1/health")
    assert res.status_code == 200, f"Health check failed: {res.status_code}"
    health_data = res.json()
    assert health_data["status"] == "ok"
    print(f"  PASS: Health check 200 OK -> {health_data}")

    # -------------------------------------------------------------------------
    # Input Validation Edge Cases
    # -------------------------------------------------------------------------
    print("\n[TEST 2] Missing 'text' in payload -> 422...")
    res = client.post("/api/v1/job/parse", json={})
    assert res.status_code == 422, f"Expected 422, got {res.status_code}"
    print(f"  PASS: HTTP 422 returned for missing field: {res.json()['detail']}")

    print("\n[TEST 3] Empty text string -> 400 or 422...")
    res = client.post("/api/v1/job/parse", json={"text": ""})
    assert res.status_code in (400, 422), f"Expected 400 or 422, got {res.status_code}"
    print(f"  PASS: HTTP {res.status_code} returned for empty text")

    print("\n[TEST 4] Whitespace-only text -> 400 or 422...")
    res = client.post("/api/v1/job/parse", json={"text": "   \n\t  \n  "})
    assert res.status_code in (400, 422), f"Expected 400 or 422, got {res.status_code}"
    print(f"  PASS: HTTP {res.status_code} returned for whitespace text")

    print("\n[TEST 5] Too short text (< 15 chars) -> 422...")
    res = client.post("/api/v1/job/parse", json={"text": "Hire dev"})
    assert res.status_code in (400, 422), f"Expected 400 or 422, got {res.status_code}"
    print(f"  PASS: HTTP {res.status_code} returned for too-short text")

    print("\n[TEST 6] Oversized text (> 50,000 chars) -> 413 or 422...")
    oversized = "We need engineers. " * 3000  # > 55,000 characters
    res = client.post("/api/v1/job/parse", json={"text": oversized})
    assert res.status_code in (413, 422), f"Expected 413 or 422, got {res.status_code}"
    print(f"  PASS: HTTP {res.status_code} returned for oversized text")

    # -------------------------------------------------------------------------
    # LLM Error Handling Simulation
    # -------------------------------------------------------------------------
    print("\n[TEST 7] LLM unavailable simulation (Ollama connection error -> 503)...")
    with patch("app.services.llm_service.generate_json_response", side_effect=llm_service.OllamaConnectionError("Ollama is offline")):
        res = client.post(
            "/api/v1/job/parse",
            json={"text": "We are hiring a Java Developer with Spring Boot and SQL skills."}
        )
        assert res.status_code == 503, f"Expected 503, got {res.status_code}"
        print(f"  PASS: HTTP 503 returned: {res.json()['detail']}")

    print("\n[TEST 8] LLM unparseable JSON simulation -> 502...")
    with patch("app.services.llm_service.generate_json_response", side_effect=llm_service.LLMResponseParseError("Model produced invalid json")):
        res = client.post(
            "/api/v1/job/parse",
            json={"text": "We are hiring a Java Developer with Spring Boot and SQL skills."}
        )
        assert res.status_code == 502, f"Expected 502, got {res.json()['detail']}"
        print(f"  PASS: HTTP 502 returned: {res.json()['detail']}")

    # -------------------------------------------------------------------------
    # Unit Tests for Sanitization and Deduplication
    # -------------------------------------------------------------------------
    print("\n[TEST 9] Schema unit test: Deduplicate skills & cross-list isolation...")
    profile = JobProfile(
        role_title="Backend Engineer",
        required_skills=["Java", "Spring Boot", "java", "SPRING BOOT", "SQL"],
        good_to_have_skills=["SQL", "Docker", "AWS", "docker"],
        experience_level="3+ years",
    )
    assert profile.required_skills == ["Java", "Spring Boot", "SQL"], f"Dedup failed: {profile.required_skills}"
    # SQL is in required_skills so it must not appear in good_to_have_skills, and docker must be deduped
    assert "SQL" not in profile.good_to_have_skills, f"Cross-list leak: {profile.good_to_have_skills}"
    assert profile.good_to_have_skills == ["Docker", "AWS"], f"Good to have failed: {profile.good_to_have_skills}"
    print(f"  PASS: Skills correctly deduplicated without cross-contamination -> {profile.required_skills}, {profile.good_to_have_skills}")

    print("\n[TEST 10] Unit test: Key normalization from LLM synonym outputs...")
    mock_synonym_llm_output = {
        "job_title": "Full Stack Engineer",
        "mandatory_skills": ["Python", "FastAPI", "React"],
        "nice_to_have": ["Docker", "Kubernetes"],
        "years_of_experience": "0-2 years",
    }
    normalized = normalize_job_keys(mock_synonym_llm_output)
    norm_profile = JobProfile(**normalized)
    assert norm_profile.role_title == "Full Stack Engineer"
    assert norm_profile.required_skills == ["Python", "FastAPI", "React"]
    assert norm_profile.good_to_have_skills == ["Docker", "Kubernetes"]
    assert norm_profile.experience_level == "0-2 years"
    print(f"  PASS: Synonyms normalized to JobProfile: {norm_profile}")

    # -------------------------------------------------------------------------
    # Real End-to-End Qwen3 Tests
    # -------------------------------------------------------------------------
    print("\n[TEST 11] Real Qwen3 End-to-End: Valid JD without explicit experience...")
    jd_sample_1 = (
        "We are hiring a Java Developer with experience in Java, Spring Boot, SQL and REST APIs. "
        "Knowledge of Docker and AWS is preferred."
    )
    res = client.post("/api/v1/job/parse", json={"text": jd_sample_1})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data_1 = res.json()
    assert data_1["success"] is True
    assert "job_profile" in data_1
    jp_1 = data_1["job_profile"]
    print(f"  PASS: Real JD parsed in {data_1.get('processing_time_ms')} ms")
    print(f"        Role Title: {jp_1.get('role_title')}")
    print(f"        Required Skills: {jp_1.get('required_skills')}")
    print(f"        Good-to-Have Skills: {jp_1.get('good_to_have_skills')}")
    print(f"        Experience Level: {jp_1.get('experience_level')}")

    # Verify role_title reflects Java Developer
    assert "Java" in jp_1["role_title"] or "Developer" in jp_1["role_title"], f"Unexpected title: {jp_1['role_title']}"
    # Verify required_skills contains core tech
    req_skills_lower = [s.lower() for s in jp_1["required_skills"]]
    assert any("java" in s for s in req_skills_lower), "Java missing from required skills"
    assert any("spring" in s for s in req_skills_lower), "Spring Boot missing from required skills"
    # Verify good to have contains Docker or AWS
    good_skills_lower = [s.lower() for s in jp_1["good_to_have_skills"]]
    assert any("docker" in s or "aws" in s for s in good_skills_lower), "Docker/AWS missing from good to have skills"
    # Verify experience level is not invented
    assert "not specified" in jp_1["experience_level"].lower() or jp_1["experience_level"] == "Not specified", (
        f"Experience level was invented when not in JD: {jp_1['experience_level']}"
    )

    print("\n[TEST 12] Real Qwen3 End-to-End: Valid JD with explicit experience (Fresher / 0-2 years)...")
    jd_sample_2 = (
        "Frontend Engineer Position\n"
        "Experience: Fresher / 0-2 years\n"
        "Requirements:\n"
        "- Modern JavaScript, TypeScript, React, and CSS\n"
        "- Understanding of Git and RESTful services\n"
        "Bonus:\n"
        "- Next.js and TailwindCSS"
    )
    res = client.post("/api/v1/job/parse", json={"text": jd_sample_2})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    data_2 = res.json()
    jp_2 = data_2["job_profile"]
    print(f"  PASS: Real JD 2 parsed in {data_2.get('processing_time_ms')} ms")
    print(f"        Role Title: {jp_2.get('role_title')}")
    print(f"        Required Skills: {jp_2.get('required_skills')}")
    print(f"        Good-to-Have Skills: {jp_2.get('good_to_have_skills')}")
    print(f"        Experience Level: {jp_2.get('experience_level')}")

    # Verify experience_level captures 0-2 years or Fresher
    exp_lower = jp_2["experience_level"].lower()
    assert "0" in exp_lower or "2" in exp_lower or "fresher" in exp_lower, (
        f"Expected 0-2 years or Fresher, got: {jp_2['experience_level']}"
    )
    req_skills_2_lower = [s.lower() for s in jp_2["required_skills"]]
    assert any("react" in s for s in req_skills_2_lower), "React missing from required skills"

    # -------------------------------------------------------------------------
    # Controlled Absent-Technology Test (Prompt anti-hallucination verification)
    # -------------------------------------------------------------------------
    print("\n[TEST 13] Controlled absent-technology test (verify unstated tools are NOT extracted)...")
    controlled_jd = (
        "Backend Python Engineer\n"
        "We are hiring a Backend Engineer to build APIs using Python, Flask, and PostgreSQL.\n"
        "Experience: 1-3 years.\n"
        "Responsibilities include writing clean Python code, designing database schemas, and unit testing."
    )
    # Deliberately absent: Docker, Kubernetes, AWS, Django, React, Java
    res = client.post("/api/v1/job/parse", json={"text": controlled_jd})
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    ctrl_profile = res.json()["job_profile"]
    all_extracted = [s.lower() for s in (ctrl_profile["required_skills"] + ctrl_profile["good_to_have_skills"])]
    
    # Assert explicitly supported skills are extracted
    assert any("python" in s for s in all_extracted), f"Python should be extracted: {all_extracted}"
    assert any("flask" in s for s in all_extracted), f"Flask should be extracted: {all_extracted}"
    
    # Assert deliberately absent technologies are NOT returned
    deliberately_absent = ["docker", "kubernetes", "aws", "django", "react", "java"]
    for absent in deliberately_absent:
        assert not any(absent == s or f" {absent}" in s or f"{absent} " in s for s in all_extracted), (
            f"Technology '{absent}' was not in JD but was inferred/extracted: {all_extracted}"
        )
    print(f"  PASS: Controlled test verified absent technologies ({deliberately_absent}) were NOT extracted.")
    print(f"        Extracted: {all_extracted}")

    # -------------------------------------------------------------------------
    # Section-Aware Truncation Test
    # -------------------------------------------------------------------------
    print("\n[TEST 14] Section-aware JD truncation test for oversized text...")
    from app.prompts.job_prompts import extract_relevant_jd_sections
    oversized_jd = (
        "Senior Cloud Architect\nAbout TechCorp: " + ("TechCorp is a leading enterprise company. " * 300) + "\n\n"
        "Requirements:\n- Go, Distributed Systems, Microservices, Kubernetes\n\n"
        "Preferred Skills:\n- Rust, gRPC, Terraform\n\n"
        "Experience:\n- 5+ years building distributed infrastructure\n\n"
        "Benefits:\n" + ("Health, Dental, Vision, 401k matching. " * 300)
    )
    extracted_sections = extract_relevant_jd_sections(oversized_jd, max_chars=3000)
    assert len(extracted_sections) <= 3000
    assert "Requirements:" in extracted_sections
    assert "Go" in extracted_sections
    assert "Preferred Skills:" in extracted_sections
    assert "5+ years" in extracted_sections
    print(f"  PASS: Section-aware extractor preserved Requirements, Preferred Skills, and Experience in {len(extracted_sections)} chars")

    print("\n=================================================================")
    print("ALL 14 PHASE 5 AUTOMATED TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
