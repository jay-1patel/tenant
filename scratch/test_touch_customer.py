import sys
import sqlite3

sys.path.insert(0, "backend")

from database import touch_customer, _resolve_tenant, get_request_tenant
import sqlite3 as s

tid = _resolve_tenant()
print("resolved tenant:", repr(tid))
print("request tenant:", repr(get_request_tenant()))

wa = "919999999901"
touch_customer(tid, wa, "")
touch_customer(tid, wa, "Asha Verma")

c = s.connect("faq.db")
c.row_factory = s.Row
rows = c.execute("SELECT * FROM customers WHERE wa_id=?", (wa,)).fetchall()
print("rows after touch:", [dict(r) for r in rows])
print("total customers:", c.execute("SELECT COUNT(*) FROM customers").fetchone()[0])
