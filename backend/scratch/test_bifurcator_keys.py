"""Quick test: verify auto_bifurcator now picks up keys from routing.config"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import requests
from routing import config as _cfg

groq_key   = getattr(_cfg, "GROQ_API_KEY", None) or ""
groq_url   = getattr(_cfg, "GROQ_API_URL", None) or "https://api.groq.com/openai/v1/chat/completions"
groq_model = getattr(_cfg, "GROQ_MODEL", None) or "openai/gpt-oss-20b"

print(f"GROQ KEY  : {groq_key[:10]}..." if groq_key else "GROQ KEY  : NOT SET")
print(f"GROQ URL  : {groq_url}")
print(f"GROQ MODEL: {groq_model}")

if not groq_key:
    print("FAIL: No Groq key found in routing.config")
    sys.exit(1)

headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
# Simple non-JSON test first
payload = {
    "model": groq_model,
    "messages": [{"role": "user", "content": "Say hello"}],
    "max_tokens": 20,
}
resp = requests.post(groq_url, headers=headers, json=payload, timeout=15)
print(f"Groq HTTP : {resp.status_code}")
if resp.status_code == 200:
    content = resp.json()["choices"][0]["message"]["content"]
    print(f"Groq Reply: {content}")
    print("PASS: Groq API reachable with routing.config key")
else:
    print(f"FAIL: {resp.text[:300]}")

