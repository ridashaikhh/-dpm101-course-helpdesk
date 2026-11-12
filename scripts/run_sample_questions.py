"""Send the 12 sample questions to a running instance and print answers + counters.

Usage: python scripts/run_sample_questions.py [BASE_URL]   (default http://localhost:8000)
"""
import re
import sys
import uuid
from pathlib import Path

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
text = (Path(__file__).resolve().parent.parent / "sample_test_questions.txt").read_text(encoding="utf-8")
questions = [m.group(1).strip() for m in re.finditer(r"^\s*\d+\.\s+(.*?)(?:\s{3,}\(.*\))?\s*$", text, re.M)]
questions = [re.sub(r"^\(Follow-up to #8\):\s*", "", q) for q in questions][:12]

cid = None
with httpx.Client(timeout=60) as c:
    for i, q in enumerate(questions, 1):
        r = c.post(f"{BASE}/api/chat", json={"question": q, "conversation_id": cid, "request_id": uuid.uuid4().hex})
        d = r.json()
        cid = d.get("conversation_id", cid)
        print(f"\n#{i} Q: {q}\n   [{r.status_code}] {d.get('served_from', d.get('error_code'))}"
              f" sources={[s['file'] for s in d.get('sources', [])]}\n   A: {d.get('answer') or d.get('message')}")
    print("\nCounters:", c.get(f"{BASE}/api/stats").json())
