import sys, asyncio, logging, sqlite3
sys.path.insert(0, "backend")
logging.basicConfig(level=logging.DEBUG)
import services.orchestrator as o

async def main():
    r = await o.process_incoming_message("919000000001", "Hi", capture_only=True)
    print("RESULT status:", r.get("status"), "n_msgs:", len(r.get("messages") or []))
    print("RESULT error:", r.get("error"))

asyncio.run(main())
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("customer rows:", [dict(r) for r in c.execute("SELECT tenant_id, wa_id, name, message_count FROM customers WHERE wa_id=?", ("919000000001",))])
