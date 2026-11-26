"""
Comprehensive test suite for Phase 6: Sentence Transformer Semantic Matching & Gap Analysis.

Covers:
- Test 1: Basic exact skill match (Java <-> Java -> similarity 1.0)
- Test 2: Case normalization (SQL <-> sql -> similarity 1.0)
- Test 3: Semantic relationship (PostgreSQL <-> relational database / RDBMS) meaningfully higher than unrelated (React)
- Test 4: Clear gap (Java <-> Python -> below threshold, identified as gap)
- Test 5: Distinct technology guard (Java <-> JavaScript must NOT match)
- Test 6: Multiple required skills (Java, SQL matched; Python gap)
- Test 7: Good-to-have / preferred skills matching and gap isolation
- Test 8: Empty candidate skills -> score 0, all JD skills are gaps
- Test 9: Empty JD skills -> score 0
- Test 10: Duplicate skills deduplication without double counting
- Test 11: Multiple JD skills competing for candidate skills
- Test 12: Deterministic score calculation verification (80% req + 20% pref)
- Test 13: Model caching / singleton verification (cold vs warm inference)
- Test 14: API validation error (missing body -> 422)
- Test 15: API successful response (POST /api/v1/analysis/match -> 200 OK with valid schema)
"""

import os
import sys
import time

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.schemas.resume import CandidateProfile, CandidateProject
from app.schemas.job import JobProfile
from app.services.semantic_matcher import (
    calculate_match_analysis,
    get_embedding_model,
    is_distinct_technology,
)


def run_all_tests():
    client = TestClient(app)
    print("=================================================================")
    print("STARTING PHASE 6 AUTOMATED TEST SUITE")
    print("=================================================================")

    # -------------------------------------------------------------------------
    # Test 1 & 2: Exact Match and Case Normalization
    # -------------------------------------------------------------------------
    print("\n[TEST 1 & 2] Exact skill match and case normalization (Java <-> Java, SQL <-> sql)...")
    cand = CandidateProfile(
        candidate_name="Test Dev",
        extracted_skills=["Java", "SQL"],
        experience_years=2.0,
        key_projects=[],
    )
    job = JobProfile(
        role_title="Backend Developer",
        required_skills=["Java", "sql"],
        good_to_have_skills=[],
        experience_level="2+ years",
    )
    result = calculate_match_analysis(cand, job, threshold=0.60)
    assert result.match_score == 100, f"Expected 100, got {result.match_score}"
    assert len(result.matched_skills) == 2
    assert len(result.skill_gaps) == 0
    for match in result.matched_skills:
        assert match.similarity >= 0.99, f"Exact match similarity should be ~1.0: {match}"
    print(f"  PASS: Exact matches scored 100% with similarity 1.0 -> {result.matched_skills}")

    # -------------------------------------------------------------------------
    # Test 3: Semantic / Synonym-style Match (PostgreSQL <-> relational database / RDBMS)
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Semantic / domain relationship (PostgreSQL <-> relational database)...")
    cand_pg = CandidateProfile(
        candidate_name="DB Admin",
        extracted_skills=["PostgreSQL"],
        experience_years=3.0,
        key_projects=[],
    )
    job_rdbms = JobProfile(
        role_title="Database Engineer",
        required_skills=["relational database"],
        good_to_have_skills=[],
        experience_level="3+ years",
    )
    res_pg = calculate_match_analysis(cand_pg, job_rdbms, threshold=0.60)
    assert len(res_pg.matched_skills) == 1, f"PostgreSQL should match relational database: {res_pg}"
    assert res_pg.matched_skills[0].similarity >= 0.50

    # Compare against unrelated technology (React <-> relational database)
    cand_react = CandidateProfile(
        candidate_name="Frontend Dev",
        extracted_skills=["React"],
        experience_years=3.0,
        key_projects=[],
    )
    res_react = calculate_match_analysis(cand_react, job_rdbms, threshold=0.60)
    assert len(res_react.matched_skills) == 0, f"React must NOT match relational database: {res_react}"
    assert len(res_react.skill_gaps) == 1
    print(f"  PASS: PostgreSQL matched 'relational database' (similarity: {res_pg.matched_skills[0].similarity}), while React was a gap.")

    # -------------------------------------------------------------------------
    # Test 4: Clear Gap (Java <-> Python)
    # -------------------------------------------------------------------------
    print("\n[TEST 4] Clear gap (Java candidate vs Python JD)...")
    cand_java = CandidateProfile(
        candidate_name="Java Dev",
        extracted_skills=["Java"],
        experience_years=2.0,
        key_projects=[],
    )
    job_py = JobProfile(
        role_title="Python Developer",
        required_skills=["Python"],
        good_to_have_skills=[],
        experience_level="2+ years",
    )
    res_py = calculate_match_analysis(cand_java, job_py, threshold=0.60)
    assert res_py.match_score == 0
    assert len(res_py.matched_skills) == 0
    assert len(res_py.skill_gaps) == 1
    assert res_py.skill_gaps[0].skill == "Python"
    print(f"  PASS: Python correctly identified as a gap for a Java candidate (score: {res_py.match_score})")

    # -------------------------------------------------------------------------
    # Test 5: Distinct Technology Guard (Java <-> JavaScript must NOT match)
    # -------------------------------------------------------------------------
    print("\n[TEST 5] Distinct technology guard (Java must NOT match JavaScript)...")
    assert is_distinct_technology("Java", "JavaScript") is True
    assert is_distinct_technology("javascript", "java") is True
    assert is_distinct_technology("C", "C++") is True
    assert is_distinct_technology("Python", "Python") is False

    cand_only_java = CandidateProfile(
        candidate_name="Java Only",
        extracted_skills=["Java"],
        experience_years=2.0,
        key_projects=[],
    )
    job_js = JobProfile(
        role_title="Frontend Developer",
        required_skills=["JavaScript"],
        good_to_have_skills=[],
        experience_level="2+ years",
    )
    res_js = calculate_match_analysis(cand_only_java, job_js, threshold=0.30)  # Even with low threshold
    assert len(res_js.matched_skills) == 0, f"Java and JavaScript must never match: {res_js.matched_skills}"
    assert len(res_js.skill_gaps) == 1
    print("  PASS: Distinct technology guard successfully prevented Java from matching JavaScript.")

    # -------------------------------------------------------------------------
    # Test 6: Multiple Required Skills Matching
    # -------------------------------------------------------------------------
    print("\n[TEST 6] Multiple required skills (Java, SQL, React vs Java, SQL, Python)...")
    cand_multi = CandidateProfile(
        candidate_name="Full Stack Dev",
        extracted_skills=["Java", "SQL", "React"],
        experience_years=2.0,
        key_projects=[],
    )
    job_multi = JobProfile(
        role_title="Backend Developer",
        required_skills=["Java", "SQL", "Python"],
        good_to_have_skills=[],
        experience_level="2+ years",
    )
    res_multi = calculate_match_analysis(cand_multi, job_multi, threshold=0.60)
    # 2 out of 3 required matched -> 67%
    assert res_multi.match_score == 67, f"Expected 67, got {res_multi.match_score}"
    assert len(res_multi.matched_skills) == 2
    matched_names = {m.required_skill for m in res_multi.matched_skills}
    assert "Java" in matched_names and "SQL" in matched_names
    assert len(res_multi.skill_gaps) == 1
    assert res_multi.skill_gaps[0].skill == "Python"
    print(f"  PASS: 2 of 3 matched -> score: {res_multi.match_score}%, matched: {matched_names}, gap: Python")

    # -------------------------------------------------------------------------
    # Test 7: Good-to-Have / Preferred Skills
    # -------------------------------------------------------------------------
    print("\n[TEST 7] Good-to-have / preferred skills...")
    cand_pref = CandidateProfile(
        candidate_name="Cloud Engineer",
        extracted_skills=["Java", "Docker"],
        experience_years=3.0,
        key_projects=[],
    )
    job_pref = JobProfile(
        role_title="Cloud Engineer",
        required_skills=["Java"],
        good_to_have_skills=["Docker", "AWS"],
        experience_level="3+ years",
    )
    res_pref = calculate_match_analysis(cand_pref, job_pref, threshold=0.60)
    # Required: 1/1 (100%), Preferred: 1/2 (50%)
    # Formula: (0.80 * 1.0 + 0.20 * 0.5) * 100 = 90%
    assert res_pref.match_score == 90, f"Expected 90, got {res_pref.match_score}"
    assert len(res_pref.matched_skills) == 1
    assert len(res_pref.preferred_matches) == 1
    assert res_pref.preferred_matches[0].required_skill == "Docker"
    assert len(res_pref.preferred_gaps) == 1
    assert res_pref.preferred_gaps[0].skill == "AWS"
    print(f"  PASS: Preferred skills evaluated correctly -> score: {res_pref.match_score}%, pref_matched: Docker, pref_gap: AWS")

    # -------------------------------------------------------------------------
    # Test 8: Empty Candidate Skills Edge Case
    # -------------------------------------------------------------------------
    print("\n[TEST 8] Empty candidate skills edge case...")
    cand_empty = CandidateProfile(
        candidate_name="No Skills Dev",
        extracted_skills=[],
        experience_years=0.0,
        key_projects=[],
    )
    res_empty_cand = calculate_match_analysis(cand_empty, job_multi, threshold=0.60)
    assert res_empty_cand.match_score == 0
    assert len(res_empty_cand.matched_skills) == 0
    assert len(res_empty_cand.skill_gaps) == 3
    print(f"  PASS: Empty candidate skills safely produced score 0 with 3 gaps.")

    # -------------------------------------------------------------------------
    # Test 9: Empty JD Skills Edge Case
    # -------------------------------------------------------------------------
    print("\n[TEST 9] Empty JD skills edge case...")
    job_empty = JobProfile(
        role_title="Vague Role",
        required_skills=[],
        good_to_have_skills=[],
        experience_level="Not specified",
    )
    res_empty_jd = calculate_match_analysis(cand_multi, job_empty, threshold=0.60)
    assert res_empty_jd.match_score == 0
    assert len(res_empty_jd.matched_skills) == 0
    assert len(res_empty_jd.skill_gaps) == 0
    print(f"  PASS: Empty JD skills safely produced score 0 without exceptions.")

    # -------------------------------------------------------------------------
    # Test 10: Duplicate Skills Deduplication
    # -------------------------------------------------------------------------
    print("\n[TEST 10] Duplicate skills deduplication...")
    cand_dups = CandidateProfile(
        candidate_name="Duplicate Dev",
        extracted_skills=["Java", "java", "JAVA", "Spring"],
        experience_years=2.0,
        key_projects=[],
    )
    job_dups = JobProfile(
        role_title="Backend Dev",
        required_skills=["Java", "java", "Spring"],
        good_to_have_skills=[],
        experience_level="2+ years",
    )
    res_dups = calculate_match_analysis(cand_dups, job_dups, threshold=0.60)
    assert res_dups.match_score == 100
    assert len(res_dups.matched_skills) == 2  # Java and Spring (deduplicated)
    assert res_dups.summary.total_required == 2
    print(f"  PASS: Deduplication verified: {res_dups.summary.total_required} required skills, 100% score.")

    # -------------------------------------------------------------------------
    # Test 11: Multiple JD Skills Competing for Candidate Skills
    # -------------------------------------------------------------------------
    print("\n[TEST 11] Multiple JD skills competing for candidate skills...")
    cand_single = CandidateProfile(
        candidate_name="Java Dev",
        extracted_skills=["Java"],
        experience_years=1.0,
        key_projects=[],
    )
    job_competing = JobProfile(
        role_title="Polyglot Dev",
        required_skills=["Java", "C++", "Python"],
        good_to_have_skills=[],
        experience_level="1+ years",
    )
    res_competing = calculate_match_analysis(cand_single, job_competing, threshold=0.60)
    assert len(res_competing.matched_skills) == 1
    assert res_competing.matched_skills[0].required_skill == "Java"
    assert len(res_competing.skill_gaps) == 2
    assert res_competing.match_score == 33  # 1/3 = 33%
    print(f"  PASS: Candidate skill matched Java only; C++ and Python are gaps (score: {res_competing.match_score}%).")

    # -------------------------------------------------------------------------
    # Test 12: Deterministic Score Formula Verification
    # -------------------------------------------------------------------------
    print("\n[TEST 12] Deterministic score formula check (Viva formula)...")
    # 4 required, 2 matched -> 50% req coverage
    # 2 preferred, 1 matched -> 50% pref coverage
    # Score = round((0.80 * 0.50 + 0.20 * 0.50) * 100) = 50%
    cand_formula = CandidateProfile(
        candidate_name="Formula Dev",
        extracted_skills=["Java", "SQL", "Docker"],
        experience_years=2.0,
        key_projects=[],
    )
    job_formula = JobProfile(
        role_title="Backend Dev",
        required_skills=["Java", "SQL", "Python", "Go"],
        good_to_have_skills=["Docker", "Kubernetes"],
        experience_level="2+ years",
    )
    res_formula = calculate_match_analysis(cand_formula, job_formula, threshold=0.60)
    assert res_formula.summary.required_coverage == 0.5
    assert res_formula.summary.preferred_coverage == 0.5
    assert res_formula.match_score == 50, f"Expected 50, got {res_formula.match_score}"
    print(f"  PASS: Viva formula verified: 50% req + 50% pref -> match score = {res_formula.match_score}%.")

    # -------------------------------------------------------------------------
    # Test 13: Model Singleton & Latency Recording
    # -------------------------------------------------------------------------
    print("\n[TEST 13] Model singleton and cold vs warm latency recording...")
    t0 = time.perf_counter()
    m1 = get_embedding_model()
    t1 = time.perf_counter()
    m2 = get_embedding_model()
    t2 = time.perf_counter()
    assert m1 is m2, "get_embedding_model must return identical cached singleton instance"
    first_call_ms = (t1 - t0) * 1000
    cached_call_ms = (t2 - t1) * 1000
    print(f"  PASS: Singleton verified (First access: {first_call_ms:.2f} ms, Cached access: {cached_call_ms:.4f} ms)")

    # -------------------------------------------------------------------------
    # Test 14: API Validation Error Handling
    # -------------------------------------------------------------------------
    print("\n[TEST 14] API validation error handling (POST /api/v1/analysis/match with invalid body)...")
    res_err = client.post("/api/v1/analysis/match", json={})
    assert res_err.status_code == 422, f"Expected 422, got {res_err.status_code}"
    print(f"  PASS: HTTP 422 returned for missing required fields: {res_err.json()['detail']}")

    # -------------------------------------------------------------------------
    # Test 15: Real API End-to-End Test (POST /api/v1/analysis/match -> 200 OK)
    # -------------------------------------------------------------------------
    print("\n[TEST 15] Real API End-to-End test (POST /api/v1/analysis/match)...")
    payload = {
        "candidate_profile": {
            "candidate_name": "Alex Example",
            "extracted_skills": ["Java", "SQL", "React", "Docker"],
            "experience_years": 2.0,
            "key_projects": [
                {
                    "name": "Interview-IQ",
                    "description": "AI mock interview platform",
                    "technologies": ["FastAPI", "React"],
                }
            ],
        },
        "job_profile": {
            "role_title": "Full Stack Engineer",
            "required_skills": ["Java", "SQL", "Python"],
            "good_to_have_skills": ["Docker", "AWS"],
            "experience_level": "2+ years",
        },
        "threshold": 0.60,
    }
    t_api_start = time.perf_counter()
    res_api = client.post("/api/v1/analysis/match", json=payload)
    api_ms = (time.perf_counter() - t_api_start) * 1000
    assert res_api.status_code == 200, f"Expected 200, got {res_api.status_code}: {res_api.text}"
    api_data = res_api.json()

    assert api_data["success"] is True
    assert "match_score" in api_data
    assert isinstance(api_data["match_score"], int)
    assert 0 <= api_data["match_score"] <= 100
    # Required: match_label must NOT exist in Phase 6 schema per user requirement
    assert "match_label" not in api_data, "match_label should not be present in Phase 6 API response"
    assert "matched_skills" in api_data
    assert "skill_gaps" in api_data
    assert "preferred_matches" in api_data
    assert "preferred_gaps" in api_data
    assert "requirements" in api_data
    assert "summary" in api_data
    assert len(api_data["requirements"]) == 5  # 3 req + 2 pref

    print(f"  PASS: Live API returned 200 OK in {api_ms:.1f} ms")
    print(f"        Match Score: {api_data['match_score']}%")
    print(f"        Matched Skills: {[m['required_skill'] for m in api_data['matched_skills']]}")
    print(f"        Skill Gaps: {[g['skill'] for g in api_data['skill_gaps']]}")
    print(f"        Preferred Matches: {[m['required_skill'] for m in api_data['preferred_matches']]}")
    print(f"        Preferred Gaps: {[g['skill'] for g in api_data['preferred_gaps']]}")

    # -------------------------------------------------------------------------
    # Test 16: User Explicit Live Test Cases (Cases A, B, C, D)
    # -------------------------------------------------------------------------
    print("\n[TEST 16] User Explicit Live Test Cases (Cases A, B, C, D)...")
    
    # Case A: Candidate [Java, SQL], JD [Java, SQL, Python]
    # Expected: Java -> matched, SQL -> matched, Python -> gap
    print("  Testing Case A (Java + SQL candidate vs Java + SQL + Python JD)...")
    case_a_cand = CandidateProfile(candidate_name="Case A", extracted_skills=["Java", "SQL"], experience_years=1.0)
    case_a_jd = JobProfile(role_title="Backend", required_skills=["Java", "SQL", "Python"], good_to_have_skills=[])
    res_a = calculate_match_analysis(case_a_cand, case_a_jd, threshold=0.60)
    matched_a = {m.required_skill for m in res_a.matched_skills}
    gaps_a = {g.skill for g in res_a.skill_gaps}
    assert "Java" in matched_a and "SQL" in matched_a, f"Java and SQL must be matched in Case A: {matched_a}"
    assert "Python" in gaps_a, f"Python must be a gap in Case A: {gaps_a}"
    assert res_a.match_score == 67, f"Expected 67% in Case A, got {res_a.match_score}"
    print(f"    Case A PASS: Matched={matched_a}, Gaps={gaps_a}, Score={res_a.match_score}%")

    # Case B: Candidate [PostgreSQL], JD [Relational Database / RDBMS]
    # Expected: Semantic / taxonomy match above threshold 0.60
    print("  Testing Case B (PostgreSQL candidate vs 'Relational Database / RDBMS' JD)...")
    case_b_cand = CandidateProfile(candidate_name="Case B", extracted_skills=["PostgreSQL"], experience_years=2.0)
    case_b_jd = JobProfile(role_title="DB Dev", required_skills=["Relational Database / RDBMS"], good_to_have_skills=[])
    res_b = calculate_match_analysis(case_b_cand, case_b_jd, threshold=0.60)
    assert len(res_b.matched_skills) == 1, f"Expected 1 matched skill in Case B: {res_b}"
    assert res_b.matched_skills[0].required_skill == "Relational Database / RDBMS"
    assert res_b.matched_skills[0].candidate_skill == "PostgreSQL"
    assert len(res_b.skill_gaps) == 0, f"Expected 0 gaps in Case B: {res_b.skill_gaps}"
    assert res_b.match_score == 100, f"Expected 100% in Case B, got {res_b.match_score}"
    print(f"    Case B PASS: Matched '{res_b.matched_skills[0].required_skill}' with '{res_b.matched_skills[0].candidate_skill}' at sim {res_b.matched_skills[0].similarity}, Score={res_b.match_score}%")

    # Case C: Candidate [Java], JD [Python]
    # Expected: Python -> gap
    print("  Testing Case C (Java candidate vs Python JD)...")
    case_c_cand = CandidateProfile(candidate_name="Case C", extracted_skills=["Java"], experience_years=1.0)
    case_c_jd = JobProfile(role_title="Python Dev", required_skills=["Python"], good_to_have_skills=[])
    res_c = calculate_match_analysis(case_c_cand, case_c_jd, threshold=0.60)
    assert len(res_c.matched_skills) == 0, f"Expected 0 matched in Case C: {res_c.matched_skills}"
    assert len(res_c.skill_gaps) == 1 and res_c.skill_gaps[0].skill == "Python"
    assert res_c.match_score == 0
    print(f"    Case C PASS: Python is a gap, Score={res_c.match_score}%")

    # Case D: Candidate [Java], JD [JavaScript]
    # Expected: JavaScript must NOT be considered equivalent to Java (distinct technology guard)
    print("  Testing Case D (Java candidate vs JavaScript JD)...")
    case_d_cand = CandidateProfile(candidate_name="Case D", extracted_skills=["Java"], experience_years=1.0)
    case_d_jd = JobProfile(role_title="JS Dev", required_skills=["JavaScript"], good_to_have_skills=[])
    res_d = calculate_match_analysis(case_d_cand, case_d_jd, threshold=0.60)
    assert len(res_d.matched_skills) == 0, f"Java must NOT match JavaScript in Case D: {res_d.matched_skills}"
    assert len(res_d.skill_gaps) == 1 and res_d.skill_gaps[0].skill == "JavaScript"
    assert res_d.match_score == 0
    print(f"    Case D PASS: JavaScript prevented from matching Java, Score={res_d.match_score}%")

    print("\n=================================================================")
    print("ALL 16 PHASE 6 AUTOMATED TESTS (INCL. CASES A, B, C, D) PASSED!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
