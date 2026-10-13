import sqlite3
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("customer for sim-customer-probe:",
      [dict(r) for r in c.execute("SELECT tenant_id, wa_id, name, message_count FROM customers WHERE wa_id=?", ("sim-customer-probe",))])
