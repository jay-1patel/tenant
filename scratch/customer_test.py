"""Verify the first-contact customer directory behaviour.

Exercises the exact call the orchestrator now makes and checks:
  * first message  -> row created
  * second message -> no duplicate, message_count increments
  * name is preserved / filled, never blanked
Cleans up the test row afterwards.
"""
import sys, os

ROOT = r"C:\keya\leeway_tenant_5"
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, ROOT)

import database
from database import get_db_context, touch_customer, get_request_tenant, _resolve_tenant

WA = "919000000001"
TENANT = get_request_tenant() or _resolve_tenant()
print(f"resolved tenant : {TENANT!r}  (request tenant was {get_request_tenant()!r})")

with get_db_context() as conn:
    conn.execute("DELETE FROM customers WHERE wa_id = ?", (WA,))

touch_customer(TENANT, WA, "")
touch_customer(TENANT, WA, "Asha Verma")
touch_customer(TENANT, WA, "")

with get_db_context() as conn:
    rows = conn.execute(
        "SELECT wa_id, name, phone, tenant_id, message_count, first_seen, last_seen "
        "FROM customers WHERE wa_id = ?", (WA,)
    ).fetchall()

print(f"rows after 3 messages : {len(rows)}  (must be 1 -> no duplicates)")
for r in rows:
    print(f"  wa_id={r['wa_id']} name={r['name']!r} phone={r['phone']!r} "
          f"tenant={r['tenant_id']!r} count={r['message_count']}")
    assert len(rows) == 1
    assert r["message_count"] == 3
    assert r["name"] == "Asha Verma", "volunteered name must win"
    assert r["tenant_id"] == TENANT

with get_db_context() as conn:
    conn.execute("DELETE FROM customers WHERE wa_id = ?", (WA,))
print("cleanup done - test row removed")
print("RESULT: OK")
