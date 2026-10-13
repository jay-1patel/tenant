import sys, os, asyncio
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

import services.whatsapp_sender as sender
captured = []
async def fake_send(wa_id, text):
    captured.append(text)
    return True
sender.send_text_message = fake_send

from bots.customer_b2c import workflows as wf
from bots.customer_b2c import config as cfg

async def main():
    for t in ["🛠️ Our Services", "hello there my friend"]:
        captured.clear()
        res = await wf._fallback_to_rag("919512777899", t, cfg)
        print(repr(t), "->", res)
        print("   sent:", repr(captured[0][:90]) if captured else None)
        if captured:
            print("   count:", captured[0].count("•"))

asyncio.run(main())
