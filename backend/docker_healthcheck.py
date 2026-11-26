"""HTTP liveness only: never generates text or probes/writes to Supabase."""
import json
import os
from urllib.request import urlopen

prefix = os.environ.get("API_V1_PREFIX", "/api/v1").rstrip("/")
with urlopen(f"http://127.0.0.1:8000{prefix}/health", timeout=3) as response:
    if response.status != 200 or json.load(response).get("status") != "ok":
        raise SystemExit(1)
