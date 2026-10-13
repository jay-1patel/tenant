import sys, sqlite3
sys.path.insert(0, "backend")
from database import touch_customer
touch_customer("l", "918690983030", "Probe")
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("for wa 918690983030:")
for r in c.execute("SELECT id, tenant_id, wa_id, name, message_count FROM customers WHERE wa_id=?", ("918690983030",)):
    print("  ", dict(r))
print("all customers:")
for r in c.execute("SELECT id, tenant_id, wa_id, name, message_count FROM customers"):
    print("  ", dict(r))
