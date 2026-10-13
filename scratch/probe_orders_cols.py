import sqlite3

c = sqlite3.connect("faq.db")
c.row_factory = sqlite3.Row
tid = "l"

queries = {
    "customer_name": "SELECT customer_name FROM orders WHERE tenant_id=? LIMIT 1",
    "customer_mobile": "SELECT customer_mobile FROM orders WHERE tenant_id=? LIMIT 1",
    "order_type": "SELECT order_type FROM orders WHERE tenant_id=? LIMIT 1",
    "big_union": """SELECT wa_id FROM (
           SELECT wa_id FROM orders WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION
           SELECT wa_id FROM complaints WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION
           SELECT wa_id FROM chat_history WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION
           SELECT wa_id FROM user_states WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION
           SELECT wa_id FROM customers WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
       )""",
}
for name, sql in queries.items():
    params = (tid, tid, tid, tid, tid) if name == "big_union" else (tid,)
    try:
        c.execute(sql, params).fetchall()
        print(f"OK   {name}")
    except Exception as e:
        print(f"FAIL {name}: {e}")
