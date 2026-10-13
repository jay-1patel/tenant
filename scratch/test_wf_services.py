import sys, os, asyncio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from bots.customer_b2c import workflows as wf
from services.incoming_listener import _reply_text

wa = "919512777899"
for t in ["🛠️ Our Services", "Our Services", "our services", "🧠 Technologies", "Careers", "hello", "what are your services"]:
    print(repr(t), "->", wf._is_services_title(wa, t))

print("_reply_text live text:", repr(_reply_text([{"type": "text", "text": "Here are the services we offer:\n• *SMS Gateway*", "sent_live": True}])))
print("_reply_text mixed:", repr(_reply_text([
    {"type": "text", "text": "hi", "sent_live": True},
    {"type": "list", "body": "menu body", "sent_live": True},
    {"type": "buttons", "text": "pick", "sent_live": False},
])))
