import sys, os
sys.path.insert(0, 'backend')
sys.path.insert(0, '.')
import asyncio
from faq.service import handle_faq_query

queries = [
    "What super luxury residential projects does DLF offer in Gurugram?",
    "Tell me about The Dahlias and The Camellias",
    "Can an NRI buy commercial property in India without RBI approval?",
    "Where is DLF Mall of India and what are its features?",
    "What are the payment plans and booking process for DLF apartments?"
]

async def test_dlf_bot():
    print("=== TESTING DLF CHATBOT RETRIEVAL & ANSWER GENERATION ===\n")
    for q in queries:
        print("="*60)
        print("CUSTOMER QUERY:", q)
        payload = {"message": q, "tenant_id": "dlf", "user_id": "test_nri_buyer"}
        res = await handle_faq_query(payload)
        ans = res.get("answer", "")
        buttons = res.get("buttons", [])
        print("BOT RESPONSE:\n")
        print(ans.encode('ascii', 'ignore').decode('ascii')[:400])
        if buttons:
            print("\nINTERACTIVE BUTTONS:", [b.get("title") for b in buttons])
        print("\n")

if __name__ == "__main__":
    asyncio.run(test_dlf_bot())
