import sqlite3
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
def q(sql, *p):
    return [dict(r) for r in c.execute(sql, p)]
print("distributors total:", q("SELECT COUNT(*) n FROM distributors"))
print("distributors by tenant:", q("SELECT tenant_id, COUNT(*) n FROM distributors GROUP BY tenant_id"))
print("customers by tenant:", q("SELECT tenant_id, COUNT(*) n FROM customers GROUP BY tenant_id"))
print("chat_history distinct wa:", q("SELECT tenant_id, COUNT(DISTINCT wa_id) n FROM chat_history GROUP BY tenant_id"))
print("user_states distinct wa:", q("SELECT tenant_id, COUNT(DISTINCT wa_id) n FROM user_states GROUP BY tenant_id"))
print("orders distinct wa:", q("SELECT tenant_id, COUNT(DISTINCT wa_id) n FROM orders GROUP BY tenant_id"))
