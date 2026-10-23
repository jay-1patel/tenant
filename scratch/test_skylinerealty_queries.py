import sys, os
sys.path.insert(0, 'backend')
sys.path.insert(0, '.')
import asyncio
from faq.service import handle_faq_query

queries = [
    "What residential apartment configurations does Skyline Realty have?",
    "What is the starting price of 2 BHK and 3 BHK at Skyline Elegance?",
    "Tell me about Skyline Grandeur duplex penthouses and sky residences.",
    "What are the commercial office options at Skyline Business Hub?",
    "What is the booking token amount and is it refundable?",
    "Are home loans pre-approved by banks like SBI and Meridian Bank?"
]

async def test_skyline_bot():
    print("=== TESTING SKYLINE REALTY CHATBOT RETRIEVAL & ANSWER GENERATION ===\n")
    for q in queries:
        print("="*60)
        print("CUSTOMER QUERY:", q)
        payload = {"message": q, "tenant_id": "skylinerealty", "user_id": "test_skyline_buyer"}
        res = await handle_faq_query(payload)
        ans = res.get("answer", "")
        buttons = res.get("buttons", [])
        print("BOT RESPONSE:\n")
        print(ans.encode('ascii', 'ignore').decode('ascii')[:400])
        if buttons:
            print("\nINTERACTIVE BUTTONS:", [b.get("title") for b in buttons])
        print("\n")

if __name__ == "__main__":
    asyncio.run(test_skyline_bot())
