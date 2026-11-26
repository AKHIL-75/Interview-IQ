"""
Test Suite for Resume–JD Skill Matching, Taxonomy & Gap Analysis Bug Fixes.

Verifies:
- TEST 1: Resume = Java; JD = Java / Python / C++ -> Programming requirement = SATISFIED; C++ NOT a gap
- TEST 2: Resume = Python; JD = Java / Python / C++ -> Programming requirement = SATISFIED
- TEST 3: Resume = Java; JD = Java / Python / C++ -> No programming-language gap
- TEST 4: Resume = OOP; JD = Encapsulation, Inheritance, Polymorphism, Abstraction -> OOP covered, children covered through parent, NO TRUE_GAP for OOP children
- TEST 5: Resume = DSA + Arrays + Linked Lists + Trees; JD = Arrays, Strings, Linked Lists, Stacks, Queues, Trees -> Arrays/LL/Trees = explicit, Strings/Stacks/Queues = not explicitly evidenced, none becomes TRUE_GAP
- TEST 6: Resume = REST APIs; JD = RESTful APIs -> semantic/alias match
- TEST 7: Completely unrelated skill (e.g. Kubernetes for HTML candidate) -> TRUE_GAP
- TEST 8: Resume with only generic DSA; JD with advanced DSA topics -> parent coverage / not-explicitly-evidenced, not false explicit
- COMPREHENSIVE ACCENTURE JD TEST: The exact Resume + JD reported by the user, proving that:
    * C++, Encapsulation, Inheritance, Polymorphism, Abstraction, Arrays, Linked Lists, Trees, Graphs, DP, Joins, Normalization, Server-side Development are NEVER in gap_skills.
    * Only TRUE GAPS appear in gap_skills.
    * Match score is realistically weighted (>= 70% instead of 30%).
"""

import os
import sys
import unittest

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schemas.resume import CandidateProfile
from app.schemas.job import JobProfile
from app.services.semantic_matcher import calculate_match_analysis


class TestSkillMatchingTaxonomy(unittest.TestCase):

    def test_01_or_requirement_satisfied_by_java(self):
        """TEST 1: Resume = Java, JD = Java / Python / C++ -> SATISFIED, C++ NOT a gap."""
        cand = CandidateProfile(
            candidate_name="Java Dev",
            extracted_skills=["Java"],
            experience_years=2.0,
        )
        job = JobProfile(
            role_title="Backend Engineer",
            required_skills=["Java / Python / C++"],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)
        self.assertEqual(result.match_score, 100)
        self.assertEqual(len(result.gap_skills), 0)
        self.assertNotIn("C++", result.gap_skills)
        self.assertNotIn("Python", result.gap_skills)
        self.assertTrue(result.requirements[0].matched)

    def test_02_or_requirement_satisfied_by_python(self):
        """TEST 2: Resume = Python, JD = Java / Python / C++ -> SATISFIED."""
        cand = CandidateProfile(
            candidate_name="Python Dev",
            extracted_skills=["Python"],
            experience_years=2.0,
        )
        job = JobProfile(
            role_title="Backend Engineer",
            required_skills=["Java / Python / C++"],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)
        self.assertEqual(result.match_score, 100)
        self.assertEqual(len(result.gap_skills), 0)
        self.assertTrue(result.requirements[0].matched)

    def test_03_or_chain_separate_skills_no_false_gap(self):
        """TEST 3: Resume = Java, JD has Java, Python, C++ from an OR chain -> No programming gap."""
        cand = CandidateProfile(
            candidate_name="Java Dev",
            extracted_skills=["Java"],
            experience_years=2.0,
        )
        # When JD skills came from 'Java / Python / C++'
        job = JobProfile(
            role_title="Software Engineer",
            required_skills=["Java / Python / C++"],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)
        self.assertEqual(result.gap_skills, [])

    def test_04_oop_parent_covers_children(self):
        """TEST 4: Resume = OOP, JD = Encapsulation, Inheritance, Polymorphism, Abstraction -> No TRUE_GAP."""
        cand = CandidateProfile(
            candidate_name="Core Dev",
            extracted_skills=["OOP"],
            experience_years=1.0,
        )
        job = JobProfile(
            role_title="Software Engineer",
            required_skills=["Encapsulation", "Inheritance", "Polymorphism", "Abstraction"],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)
        # All 4 children covered through parent
        self.assertEqual(result.gap_skills, [])
        self.assertEqual(len(result.covered_through_parent), 4)
        for child in ["Encapsulation", "Inheritance", "Polymorphism", "Abstraction"]:
            self.assertIn(child, result.covered_through_parent)
            self.assertNotIn(child, result.gap_skills)
        # Grouped score for OOP should be >= 85%
        self.assertGreaterEqual(result.match_score, 85)

    def test_05_dsa_explicit_and_not_evidenced(self):
        """TEST 5: Resume = DSA + Arrays + Linked Lists + Trees; JD = Arrays, Strings, Linked Lists, Stacks, Queues, Trees."""
        cand = CandidateProfile(
            candidate_name="Algo Dev",
            extracted_skills=["Data Structures & Algorithms", "Arrays", "Linked Lists", "Trees"],
            experience_years=1.0,
        )
        job = JobProfile(
            role_title="Problem Solver",
            required_skills=["Arrays", "Strings", "Linked Lists", "Stacks", "Queues", "Trees"],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)
        # Arrays, Linked Lists, Trees are explicitly found
        self.assertIn("Arrays", result.skills_found)
        self.assertIn("Linked Lists", result.skills_found)
        self.assertIn("Trees", result.skills_found)
        # Strings, Stacks, Queues are under parent DSA -> not_explicitly_evidenced, NOT gap_skills!
        self.assertIn("Strings", result.not_explicitly_evidenced)
        self.assertIn("Stacks", result.not_explicitly_evidenced)
        self.assertIn("Queues", result.not_explicitly_evidenced)
        # None of them must be in gap_skills!
        self.assertEqual(result.gap_skills, [])

    def test_06_alias_normalization_rest_apis(self):
        """TEST 6: Resume = REST APIs, JD = RESTful APIs -> alias match."""
        cand = CandidateProfile(
            candidate_name="API Dev",
            extracted_skills=["REST APIs"],
            experience_years=2.0,
        )
        job = JobProfile(
            role_title="Backend Dev",
            required_skills=["RESTful APIs"],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)
        self.assertEqual(result.match_score, 100)
        self.assertIn("RESTful APIs", result.skills_found)
        self.assertEqual(result.gap_skills, [])

    def test_07_unrelated_skill_is_true_gap(self):
        """TEST 7: Completely unrelated skill (e.g. Kubernetes for HTML candidate) -> TRUE_GAP."""
        cand = CandidateProfile(
            candidate_name="HTML Dev",
            extracted_skills=["HTML"],
            experience_years=1.0,
        )
        job = JobProfile(
            role_title="DevOps Engineer",
            required_skills=["Kubernetes"],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)
        self.assertEqual(result.match_score, 0)
        self.assertIn("Kubernetes", result.gap_skills)
        self.assertEqual(len(result.gap_skills), 1)

    def test_08_generic_dsa_only_uses_parent_coverage(self):
        """TEST 8: Resume contains only generic DSA, JD contains advanced topics -> parent coverage, not false explicit."""
        cand = CandidateProfile(
            candidate_name="Generic DSA Dev",
            extracted_skills=["Data Structures & Algorithms"],
            experience_years=1.0,
        )
        job = JobProfile(
            role_title="Algorithms Dev",
            required_skills=["Stacks", "Queues", "Binary Trees"],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)
        # They should NOT be falsely reported as explicitly in the resume
        for item in ["Stacks", "Queues", "Binary Trees"]:
            self.assertNotIn(item, result.skills_found)
            # They should be in not_explicitly_evidenced or covered_through_parent
            self.assertTrue(item in result.not_explicitly_evidenced or item in result.covered_through_parent)
            # And critically, NOT in gap_skills
            self.assertNotIn(item, result.gap_skills)

    def test_09_full_accenture_jd_and_resume_benchmark(self):
        """
        FULL ACCENTURE BENCHMARK TEST:
        Resume has:
            Java, Python, JavaScript, SQL,
            OOP, Data Structures & Algorithms, DBMS, Operating Systems,
            arrays, linked lists, trees, graphs, dynamic programming,
            HTML, CSS, REST APIs, Git.
        JD has:
            Programming: Java / Python / C++ / JavaScript
            OOP: Encapsulation, Inheritance, Polymorphism, Abstraction
            DSA: Arrays, Strings, Linked Lists, Stacks, Queues, Trees, Sorting, Searching, Basic Algorithms
            Database: SQL, Joins, Queries, Normalization
            Web: HTML, CSS, JavaScript
            Backend: REST APIs, Server-side Development
            Software Engineering: SDLC, Git, Testing, Debugging
            Cloud: Basic Cloud Concepts
            Agile/Scrum: Sprints, User Stories, Team Collaboration
        """
        cand = CandidateProfile(
            candidate_name="Alex Example",
            extracted_skills=[
                "Java", "Python", "JavaScript", "SQL",
                "OOP", "Data Structures & Algorithms", "DBMS", "Operating Systems",
                "arrays", "linked lists", "trees", "graphs", "dynamic programming",
                "HTML", "CSS", "REST APIs", "Git",
            ],
            experience_years=2.0,
        )
        job = JobProfile(
            role_title="Associate Software Engineer",
            required_skills=[
                "Java / Python / C++ / JavaScript",
                "Encapsulation", "Inheritance", "Polymorphism", "Abstraction",
                "Arrays", "Strings", "Linked Lists", "Stacks", "Queues", "Trees", "Sorting", "Searching", "Basic Algorithms",
                "SQL", "Joins", "Queries", "Normalization",
                "HTML", "CSS", "JavaScript",
                "REST APIs", "Server-side Development",
                "SDLC", "Git", "Testing", "Debugging",
                "Basic Cloud Concepts",
                "Sprints", "User Stories", "Team Collaboration",
            ],
            good_to_have_skills=[],
        )
        result = calculate_match_analysis(cand, job)

        # 1. C++ MUST NOT be a gap!
        self.assertNotIn("C++", result.gap_skills)
        self.assertNotIn("Java / Python / C++ / JavaScript", result.gap_skills)

        # 2. OOP children MUST NOT be gaps!
        for oop_child in ["Encapsulation", "Inheritance", "Polymorphism", "Abstraction"]:
            self.assertNotIn(oop_child, result.gap_skills)

        # 3. Explicit DSA skills MUST NOT be gaps!
        for dsa_skill in ["Arrays", "Linked Lists", "Trees", "Sorting", "Searching", "Basic Algorithms"]:
            self.assertNotIn(dsa_skill, result.gap_skills)

        # 4. Database children MUST NOT be gaps!
        for db_skill in ["SQL", "Joins", "Queries", "Normalization"]:
            self.assertNotIn(db_skill, result.gap_skills)

        # 5. Backend skills MUST NOT be gaps!
        self.assertNotIn("REST APIs", result.gap_skills)
        self.assertNotIn("Server-side Development", result.gap_skills)

        # 6. Web skills MUST NOT be gaps!
        for web_skill in ["HTML", "CSS", "JavaScript"]:
            self.assertNotIn(web_skill, result.gap_skills)

        # 7. Only TRUE GAPS should be in gap_skills (Cloud, Agile/Scrum concepts)
        for true_gap in ["Basic Cloud Concepts", "Sprints", "User Stories", "Team Collaboration"]:
            self.assertIn(true_gap, result.gap_skills)

        # 8. Match score must be realistically high (>= 70%) rather than the old broken 30%!
        print(f"\n[BENCHMARK] Match Score: {result.match_score}% (was 30% before bug fix)")
        print(f"[BENCHMARK] Skills Found: {result.skills_found}")
        print(f"[BENCHMARK] Covered Through Parent: {result.covered_through_parent}")
        print(f"[BENCHMARK] Not Explicitly Evidenced: {result.not_explicitly_evidenced}")
        print(f"[BENCHMARK] True Skill Gaps: {result.gap_skills}")

        self.assertGreaterEqual(result.match_score, 70)


if __name__ == "__main__":
    unittest.main()
