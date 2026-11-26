"""
Test prompt for verifying the Qwen3 / Ollama integration.

This prompt asks the model to return a tiny JSON object that proves:
  1. Ollama is running.
  2. The model loaded and executed successfully.
  3. The response is valid, parseable JSON.

This is ONLY for Phase 3 verification.  Resume prompts, interview
prompts, and evaluation prompts belong to later phases.
"""

AI_TEST_PROMPT_TEMPLATE = """You are an AI assistant for Interview-IQ.

Instructions:
1. Answer the user request accurately and concisely.
2. Output ONLY a valid JSON object matching the required format. No extra text or markdown.
3. Required JSON keys:
   - "message": Your complete answer.
   - "model": Your model name (e.g. "qwen3").
   - "success": true

User Request:
{query}

Required JSON format:
{{"message": "Your answer here", "model": "qwen3", "success": true}}
"""

DEFAULT_TEST_QUERY = "Confirm that you are operational and ready to assist."


def build_ai_test_prompt(query: str = "") -> str:
    """
    Build the full prompt instructing the model to answer `query`
    while strictly enforcing the required JSON schema matching AITestResponse.
    """
    clean_query = query.strip() if query and query.strip() else DEFAULT_TEST_QUERY
    return AI_TEST_PROMPT_TEMPLATE.format(query=clean_query)


# Default prompt for backward compatibility
AI_TEST_PROMPT = build_ai_test_prompt()

