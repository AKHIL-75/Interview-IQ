"""
Phase 13: Interview History & Dashboard Analytics Test Suite
Verifies:
  1. Unauthenticated requests blocked (401)
  2. Authenticated history retrieval for User A
  3. Authenticated analytics calculation for User A
  4. Specific report retrieval by ID for User A
  5. Empty state and zero analytics for User B (no interviews)
  6. RLS user isolation: User B cannot access User A's report or history
"""

if __package__:
    from .live_test_config import require_test_accounts
else:
    from live_test_config import require_test_accounts
_test_accounts = require_test_accounts(2)


import asyncio
import os
import sys
import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings
from app.main import app


async def get_user_token(email: str, password: str) -> dict:
    auth_url = f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/token?grant_type=password"
    headers = {"apikey": settings.SUPABASE_ANON_KEY}
    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.post(auth_url, headers=headers, json={"email": email, "password": password})
        assert res.status_code == 200, f"Login failed for {email}: {"[response body omitted]"}"
        data = res.json()
        return {
            "token": data["access_token"],
            "user_id": data["user"]["id"],
            "email": email,
        }


def test_history_and_analytics():
    print("=" * 70)
    print("STARTING PHASE 13 BACKEND VERIFICATION")
    print("=" * 70)

    client = TestClient(app)

    # 1. Unauthenticated checks
    print("\n[TEST 1] Verifying 401 for unauthenticated endpoints...")
    r1 = client.get("/api/v1/interview/history")
    assert r1.status_code == 401, f"Expected 401, got {r1.status_code}"
    r2 = client.get("/api/v1/interview/analytics")
    assert r2.status_code == 401, f"Expected 401, got {r2.status_code}"
    r3 = client.get("/api/v1/interview/report/some-id")
    assert r3.status_code == 401, f"Expected 401, got {r3.status_code}"
    print("  PASS: Unauthenticated requests correctly rejected with 401")

    # 2. Login User A
    print("\n[TEST 2] Logging in User A ([removed legacy credential])...")
    loop = asyncio.get_event_loop()
    user_a = loop.run_until_complete(get_user_token(_test_accounts["A"]["email"], _test_accounts["A"]["password"]))
    headers_a = {"Authorization": f"Bearer {user_a['token']}"}
    print(f"  PASS: User A logged in. user_id={user_a['user_id']}")

    # 3. User A History
    print("\n[TEST 3] Testing User A GET /api/v1/interview/history...")
    res_hist_a = client.get("/api/v1/interview/history", headers=headers_a)
    assert res_hist_a.status_code == 200, f"History failed: {"[response body omitted]"}"
    hist_a = res_hist_a.json()
    assert hist_a["success"] is True
    assert "history" in hist_a
    assert "reports" in hist_a
    assert hist_a["count"] >= 1
    print(f"  PASS: User A history count: {hist_a['count']}, sessions: {len(hist_a['history'])}, reports: {len(hist_a['reports'])}")
    first_hist = hist_a["history"][0]
    assert "session_id" in first_hist
    assert "status" in first_hist
    assert "overall_score" in first_hist
    print(f"  Sample session: role={first_hist['role']}, status={first_hist['status']}, score={first_hist['overall_score']}")

    # 4. User A Analytics
    print("\n[TEST 4] Testing User A GET /api/v1/interview/analytics...")
    res_ana_a = client.get("/api/v1/interview/analytics", headers=headers_a)
    assert res_ana_a.status_code == 200, f"Analytics failed: {"[response body omitted]"}"
    ana_a = res_ana_a.json()
    assert ana_a["success"] is True
    metrics = ana_a["analytics"]
    assert metrics["total_interviews"] >= 1
    assert metrics["completed_interviews"] >= 1
    assert metrics["average_score"] > 0
    assert "performance_dimensions" in metrics
    assert "technical_accuracy" in metrics["performance_dimensions"]
    assert len(metrics["recent_interviews"]) >= 1
    print(f"  PASS: User A Analytics calculated successfully:")
    print(f"    - Total Interviews: {metrics['total_interviews']}")
    print(f"    - Completed Interviews: {metrics['completed_interviews']}")
    print(f"    - Average Score: {metrics['average_score']}%")
    print(f"    - Performance Dimensions: {metrics['performance_dimensions']}")
    print(f"    - Top Strengths: {metrics['top_strengths']}")
    print(f"    - Skills Identified: {metrics['skills_identified']}")

    # 5. User A Report Retrieval by ID
    print("\n[TEST 5] Testing User A GET /api/v1/interview/report/{id}...")
    sample_rep = hist_a["reports"][0]
    sample_rep_id = sample_rep["id"]
    res_rep = client.get(f"/api/v1/interview/report/{sample_rep_id}", headers=headers_a)
    assert res_rep.status_code == 200, f"Report lookup failed: {"[response body omitted]"}"
    rep_data = res_rep.json()["report"]
    assert rep_data["id"] == sample_rep_id
    assert rep_data["user_id"] == user_a["user_id"]
    print(f"  PASS: Successfully fetched report {sample_rep_id} for User A")

    # 6. Login User B
    print("\n[TEST 6] Logging in User B ([removed legacy credential])...")
    user_b = loop.run_until_complete(get_user_token(_test_accounts["B"]["email"], _test_accounts["B"]["password"]))
    headers_b = {"Authorization": f"Bearer {user_b['token']}"}
    print(f"  PASS: User B logged in. user_id={user_b['user_id']}")

    # 7. User B History (Empty State)
    print("\n[TEST 7] Testing User B GET /api/v1/interview/history (Empty State)...")
    res_hist_b = client.get("/api/v1/interview/history", headers=headers_b)
    assert res_hist_b.status_code == 200
    hist_b = res_hist_b.json()
    assert hist_b["success"] is True
    assert hist_b["count"] == 0
    assert len(hist_b["history"]) == 0
    assert len(hist_b["reports"]) == 0
    print("  PASS: User B returns empty history collection (0 interviews) without error")

    # 8. User B Analytics (Zero State)
    print("\n[TEST 8] Testing User B GET /api/v1/interview/analytics (Zero State)...")
    res_ana_b = client.get("/api/v1/interview/analytics", headers=headers_b)
    assert res_ana_b.status_code == 200
    ana_b = res_ana_b.json()["analytics"]
    assert ana_b["total_interviews"] == 0
    assert ana_b["completed_interviews"] == 0
    assert ana_b["average_score"] == 0
    assert len(ana_b["recent_interviews"]) == 0
    assert len(ana_b["score_trend"]) == 0
    print("  PASS: User B returns zero state metrics (0 total, 0 avg score, empty lists) without crash")

    # 9. RLS Cross-User Isolation
    print("\n[TEST 9] Testing RLS cross-user isolation: User B attempting to read User A's report...")
    res_leak = client.get(f"/api/v1/interview/report/{sample_rep_id}", headers=headers_b)
    assert res_leak.status_code == 404, f"RLS LEAK! User B could access User A's report (Status {res_leak.status_code})"
    print("  PASS: RLS strictly blocked User B from accessing User A's report (HTTP 404 Not Found)")

    print("\n" + "=" * 70)
    print("ALL PHASE 13 BACKEND VERIFICATION TESTS PASSED WITH 100% SUCCESS!")
    print("=" * 70)


if __name__ == "__main__":
    test_history_and_analytics()
