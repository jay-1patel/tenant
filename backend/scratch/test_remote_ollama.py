import requests

url = "https://prominent-faster-dropper.ngrok-free.dev/api/chat"
headers = {"ngrok-skip-browser-warning": "true", "Content-Type": "application/json"}
payload = {
    "model": "qwen3:8b",
    "messages": [{"role": "user", "content": "Respond strictly with valid JSON: {\"test\": \"success\"}"}],
    "format": "json",
    "stream": False
}
try:
    r = requests.post(url, headers=headers, json=payload, timeout=25)
    print("Status:", r.status_code)
    print("Response:", r.json().get("message", {}).get("content"))
except Exception as e:
    print("Error:", e)

