"""Dry-run of GET /campaigns/recipients logic against the live DB."""
import sqlite3

conn = sqlite3.connect(r"C:\keya\leeway_tenant_5\FAQ.DB")
conn.row_factory = sqlite3.Row
tenant_id = "leewaysoftech"

customer_ids = conn.execute(
    """SELECT wa_id FROM (
           SELECT wa_id FROM customers WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION
           SELECT wa_id FROM orders WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION
           SELECT wa_id FROM complaints WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION
           SELECT wa_id FROM chat_history WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
           UNION
           SELECT wa_id FROM user_states WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''
       )""",
    (tenant_id,) * 5,
).fetchall()

customers = []
for row in customer_ids:
    wa_id = row["wa_id"]
    cust = conn.execute(
        "SELECT name, phone, city, company FROM customers WHERE tenant_id = ? AND wa_id = ?",
        (tenant_id, wa_id),
    ).fetchone()
    name = cust["name"] if cust and cust["name"] else ""
    phone = cust["phone"] if cust and cust["phone"] else ""
    city = cust["city"] if cust and cust["city"] else ""
    company = cust["company"] if cust and cust["company"] else ""
    if not name:
        order = conn.execute(
            """SELECT customer_name, customer_mobile FROM orders
               WHERE tenant_id = ? AND wa_id = ? AND customer_name IS NOT NULL AND customer_name != ''
               ORDER BY id DESC LIMIT 1""",
            (tenant_id, wa_id),
        ).fetchone()
        if order:
            name = order["customer_name"]
            phone = phone or order["customer_mobile"] or ""
    if not name:
        chat = conn.execute(
            """SELECT sender_name FROM chat_history
               WHERE tenant_id = ? AND wa_id = ? AND sender_name IS NOT NULL AND sender_name != ''
               ORDER BY id DESC LIMIT 1""",
            (tenant_id, wa_id),
        ).fetchone()
        if chat:
            name = chat["sender_name"]
    customers.append({"wa_id": wa_id, "name": name, "phone": phone, "city": city, "company": company})

distributors = conn.execute(
    """SELECT wa_id, name, phone, region, tier, city FROM distributors
       WHERE tenant_id = ? AND wa_id IS NOT NULL AND wa_id != ''""",
    (tenant_id,),
).fetchall()

print(f"customer wa_ids found : {len(customers)}  -> {[c['wa_id'] for c in customers]}")
print(f"distributors found    : {len(distributors)} -> {[d['wa_id'] for d in distributors]}")
print(f"recipients (merged)   : {len(customers) + len(distributors)}")
for d in distributors:
    print("   distributor:", d["wa_id"], d["name"], d["city"])
