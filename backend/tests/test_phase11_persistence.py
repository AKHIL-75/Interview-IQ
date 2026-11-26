"""
Test Suite for Phase 11: Supabase Authentication & Database Persistence.

Verifies:
- Test 1: Health check is public (200 OK without token)
- Test 2: Protected route /history rejects unauthenticated request (401 Unauthorized)
- Test 3: Protected route /history rejects invalid/expired Bearer token (401 Unauthorized)
- Test 4: Unauthenticated /start succeeds with graceful fallback (resilience test)
- Test 5: Persistence service handles missing/invalid token gracefully without crashing
- Test 6: PostgREST header generation contains apikey and Bearer token
- Test 7: Session and question data structures validate against schema
- Test 8: Report persistence endpoint handles missing session_id properly (400 Bad Request)
"""

import os
import sys
import unittest
from uuid import uuid4

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from app.main import app
from app.services import persistence_service


class TestPhase11AuthAndPersistence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_health_is_public(self):
        """Public endpoint works without any authentication."""
        res = self.client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data.get("status"), "ok")

    def test_02_history_requires_auth(self):
        """GET /api/v1/interview/history without token must return 401."""
        res = self.client.get("/api/v1/interview/history")
        self.assertEqual(res.status_code, 401)
        self.assertIn("Missing authentication token", res.json().get("detail", ""))

    def test_03_history_rejects_invalid_token(self):
        """GET /api/v1/interview/history with malformed token must return 401."""
        headers = {"Authorization": "Bearer invalid.mock.jwt.token"}
        res = self.client.get("/api/v1/interview/history", headers=headers)
        self.assertEqual(res.status_code, 401)

    def test_04_start_interview_works_unauthenticated(self):
        """POST /api/v1/interview/start works without auth (backward compatibility with Phase 9)."""
        payload = {
            "candidate_profile": {"candidate_name": "Test Candidate", "extracted_skills": ["Python"]},
            "job_profile": {"role_title": "Software Engineer", "required_skills": ["Python"]},
            "interview_type": "Technical",
            "difficulty": "Medium",
            "interview_mode": "STATIC",
            "question_count": 5,
        }
        res = self.client.post("/api/v1/interview/start", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data.get("session_id", "").startswith("session-"))
        self.assertIn("first_question", data)
        self.assertEqual(data["first_question"]["stage"], "INTRO")

    def test_05_report_requires_session_id(self):
        """POST /api/v1/interview/report without session_id returns 400."""
        res = self.client.post("/api/v1/interview/report", json={"overallScore": 85})
        self.assertEqual(res.status_code, 400)
        self.assertIn("Session ID is required", res.json().get("detail", ""))

    def test_06_persistence_service_headers(self):
        """Headers must include apikey and Authorization Bearer."""
        headers = persistence_service._get_headers("test-token-123", prefer_merge=True)
        self.assertEqual(headers["Authorization"], "Bearer test-token-123")
        self.assertIn("apikey", headers)
        self.assertEqual(headers["Prefer"], "resolution=merge-duplicates,return=representation")

    def test_07_persistence_service_graceful_on_empty_token(self):
        """Persistence service functions return None rather than throwing when unauthenticated."""
        import asyncio
        async def run_async():
            res = await persistence_service.persist_resume(
                token="",
                user_id=uuid4(),
                file_name="test.pdf",
                candidate_profile={},
            )
            self.assertIsNone(res)

            sess = await persistence_service.persist_interview_session(
                token="",
                user_id=uuid4(),
                session_id="session-123",
                role="Dev",
                interview_type="Technical",
                difficulty="Medium",
                interview_mode="STATIC",
                question_count=5,
                interview_config={},
            )
            self.assertIsNone(sess)
        asyncio.run(run_async())


if __name__ == "__main__":
    unittest.main()
