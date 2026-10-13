import sqlite3
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("user_states for sim-customer-probe:")
for r in c.execute("SELECT wa_id, tenant_id, state, lang, status FROM user_states WHERE wa_id=?", ("sim-customer-probe",)):
    print("  ", dict(r))
print("all user_states:")
for r in c.execute("SELECT wa_id, tenant_id, state, status FROM user_states"):
    print("  ", dict(r))
