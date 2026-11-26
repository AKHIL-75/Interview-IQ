"""
Comprehensive test suite for Phase 4: Resume Processing & Parsing.

Covers:
- A. Valid PDF extraction + Qwen3 parsing -> 200 OK
- B. Valid DOCX extraction + Qwen3 parsing -> 200 OK
- C. Unsupported file format (.txt) -> 415 Unsupported Media Type
- D. Empty file (0 bytes) -> 400 Bad Request
- E. Corrupted PDF -> 400 Bad Request
- F. Corrupted DOCX -> 400 Bad Request
- G. File > 10 MB -> 413 Payload Too Large
- H. PDF with no extractable text -> 422 Unprocessable Entity
- I. Baseline health endpoint: GET /api/v1/health -> 200 OK
- J. Baseline AI test endpoint: POST /api/v1/ai/test -> 200 OK
- K. Error handling simulation for Ollama failure -> 503 & 502
"""

import io
import json
import os
import sys
from unittest.mock import patch

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import docx
from fastapi.testclient import TestClient
import pypdf

from app.main import app
from app.services import llm_service


def run_all_tests():
    client = TestClient(app)
    print("=================================================================")
    print("STARTING PHASE 4 AUTOMATED TEST SUITE")
    print("=================================================================")

    # -------------------------------------------------------------------------
    # Baseline Regression Tests
    # -------------------------------------------------------------------------
    print("\n[TEST 1] GET /api/v1/health...")
    res = client.get("/api/v1/health")
    assert res.status_code == 200, f"Health check failed: {res.status_code}"
    health_data = res.json()
    assert health_data["status"] == "ok"
    assert health_data["service"] == "interview-iq-backend"
    print(f"  PASS: Health check 200 OK -> {health_data}")

    print("\n[TEST 2] POST /api/v1/ai/test...")
    res = client.post("/api/v1/ai/test", json={"prompt": "Say hello in 3 words"})
    assert res.status_code == 200, f"AI test failed: {res.status_code}"
    ai_data = res.json()
    assert ai_data["success"] is True
    assert "message" in ai_data
    print(f"  PASS: AI test 200 OK (latency: {ai_data.get('latency_ms')} ms)")

    # -------------------------------------------------------------------------
    # File Validation Error Edge Cases
    # -------------------------------------------------------------------------
    print("\n[TEST 3] Unsupported file format (.txt)...")
    res = client.post(
        "/api/v1/resume/parse",
        files={"file": ("resume.txt", b"Name: John Doe\nSkills: Java, Python", "text/plain")}
    )
    assert res.status_code == 415, f"Expected 415, got {res.status_code}"
    print(f"  PASS: HTTP 415 returned: {res.json()['detail']}")

    print("\n[TEST 4] Empty file (0 bytes)...")
    res = client.post(
        "/api/v1/resume/parse",
        files={"file": ("empty.pdf", b"", "application/pdf")}
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}"
    print(f"  PASS: HTTP 400 returned: {res.json()['detail']}")

    print("\n[TEST 5] Corrupted PDF (invalid signature)...")
    res = client.post(
        "/api/v1/resume/parse",
        files={"file": ("corrupted.pdf", b"NOT_A_VALID_PDF_HEADER_DATA", "application/pdf")}
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}"
    print(f"  PASS: HTTP 400 returned: {res.json()['detail']}")

    print("\n[TEST 6] Corrupted DOCX (invalid ZIP header)...")
    res = client.post(
        "/api/v1/resume/parse",
        files={"file": ("corrupted.docx", b"CORRUPTED_DOCX_HEADER", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert res.status_code == 400, f"Expected 400, got {res.status_code}"
    print(f"  PASS: HTTP 400 returned: {res.json()['detail']}")

    print("\n[TEST 7] Oversized file (> 10 MB limit)...")
    large_content = b"%PDF-1.4\n" + (b"0" * (10 * 1024 * 1024 + 2048))
    res = client.post(
        "/api/v1/resume/parse",
        files={"file": ("large.pdf", large_content, "application/pdf")}
    )
    assert res.status_code == 413, f"Expected 413, got {res.status_code}"
    print(f"  PASS: HTTP 413 returned: {res.json()['detail']}")

    print("\n[TEST 8] PDF with no extractable text (blank/scanned)...")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    blank_buf = io.BytesIO()
    writer.write(blank_buf)
    res = client.post(
        "/api/v1/resume/parse",
        files={"file": ("scanned_blank.pdf", blank_buf.getvalue(), "application/pdf")}
    )
    assert res.status_code == 422, f"Expected 422, got {res.status_code}"
    print(f"  PASS: HTTP 422 returned: {res.json()['detail']}")

    # -------------------------------------------------------------------------
    # LLM Error Handling Simulation
    # -------------------------------------------------------------------------
    print("\n[TEST 9] LLM unavailable simulation (Ollama connection error -> 503)...")
    valid_pdf = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 120 >>
stream
BT
/F1 12 Tf
72 720 Td
(Test Candidate) Tj
0 -20 Td
(Skills: Python, SQL) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000236 00000 n 
0000000408 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
487
%%EOF"""

    with patch("app.services.llm_service.generate_json_response", side_effect=llm_service.OllamaConnectionError("Ollama is offline")):
        res = client.post(
            "/api/v1/resume/parse",
            files={"file": ("test.pdf", valid_pdf, "application/pdf")}
        )
        assert res.status_code == 503, f"Expected 503, got {res.status_code}"
        print(f"  PASS: HTTP 503 returned: {res.json()['detail']}")

    print("\n[TEST 10] LLM unparseable JSON simulation -> 502...")
    with patch("app.services.llm_service.generate_json_response", side_effect=llm_service.LLMResponseParseError("Bad JSON")):
        res = client.post(
            "/api/v1/resume/parse",
            files={"file": ("test.pdf", valid_pdf, "application/pdf")}
        )
        assert res.status_code == 502, f"Expected 502, got {res.status_code}"
        print(f"  PASS: HTTP 502 returned: {res.json()['detail']}")

    # -------------------------------------------------------------------------
    # Real End-to-End Test: Valid PDF with Qwen3
    # -------------------------------------------------------------------------
    print("\n[TEST 11] Real PDF Upload & Qwen3 parsing (POST /api/v1/resume/parse)...")
    real_pdf_bytes = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 250 >>
stream
BT
/F1 12 Tf
72 720 Td
(Alex Example) Tj
0 -20 Td
(Software Engineer with 2 years of experience in Java, Python, React, SQL, and Docker.) Tj
0 -20 Td
(Project: Interview-IQ AI mock interview platform using FastAPI and React.) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
0000000236 00000 n 
0000000538 00000 n 
trailer
<< /Size 6 /Root 1 0 R >>
startxref
617
%%EOF"""

    res = client.post(
        "/api/v1/resume/parse",
        files={"file": ("Akhil_Naragani_Resume.pdf", real_pdf_bytes, "application/pdf")}
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    pdf_resp = res.json()
    assert pdf_resp["success"] is True
    assert pdf_resp["file_type"] == "pdf"
    assert "Alex" in pdf_resp["candidate_profile"]["candidate_name"]
    assert len(pdf_resp["candidate_profile"]["extracted_skills"]) >= 2
    assert len(pdf_resp["candidate_profile"]["key_projects"]) >= 1
    print(f"  PASS: Real PDF parsed in {pdf_resp.get('processing_time_ms')} ms")
    print(f"        Candidate: {pdf_resp['candidate_profile']['candidate_name']}")
    print(f"        Skills: {pdf_resp['candidate_profile']['extracted_skills']}")
    print(f"        Experience: {pdf_resp['candidate_profile']['experience_years']} years")
    print(f"        Projects count: {len(pdf_resp['candidate_profile']['key_projects'])}")

    # -------------------------------------------------------------------------
    # Real End-to-End Test: Valid DOCX with Qwen3
    # -------------------------------------------------------------------------
    print("\n[TEST 12] Real DOCX Upload & Qwen3 parsing (POST /api/v1/resume/parse)...")
    doc = docx.Document()
    doc.add_heading("Jane Doe", level=1)
    doc.add_paragraph("Senior Backend Developer with 4 years of experience in Go, Python, and Kubernetes.")
    
    table = doc.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Technical Skills"
    table.rows[0].cells[1].text = "Go, Python, Docker, Kubernetes, gRPC, PostgreSQL, Kafka"
    table.rows[1].cells[0].text = "Education"
    table.rows[1].cells[1].text = "Master of Science in Computer Science"
    
    doc.add_heading("Projects", level=2)
    doc.add_paragraph("Project: DistributedKV - High-performance distributed key-value store using Raft consensus and Go.")
    doc.add_paragraph("Technologies: Go, Raft, gRPC, Docker")
    docx_buf = io.BytesIO()
    doc.save(docx_buf)

    res = client.post(
        "/api/v1/resume/parse",
        files={"file": ("Jane_Doe_Resume.docx", docx_buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    docx_resp = res.json()
    assert docx_resp["success"] is True
    assert docx_resp["file_type"] == "docx"
    assert "Jane" in docx_resp["candidate_profile"]["candidate_name"]
    assert len(docx_resp["candidate_profile"]["extracted_skills"]) >= 2
    assert len(docx_resp["candidate_profile"]["key_projects"]) >= 1
    print(f"  PASS: Real DOCX parsed in {docx_resp.get('processing_time_ms')} ms")
    print(f"        Candidate: {docx_resp['candidate_profile']['candidate_name']}")
    print(f"        Skills: {docx_resp['candidate_profile']['extracted_skills']}")
    print(f"        Experience: {docx_resp['candidate_profile']['experience_years']} years")
    print(f"        Projects count: {len(docx_resp['candidate_profile']['key_projects'])}")

    print("\n=================================================================")
    print("ALL 12 PHASE 4 AUTOMATED TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")


if __name__ == "__main__":
    run_all_tests()
