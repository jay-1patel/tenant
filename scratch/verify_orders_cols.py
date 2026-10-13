import sqlite3
c = sqlite3.connect("faq.db")
cols = [r[1] for r in c.execute("PRAGMA table_info(orders)")]
print("orders cols:", cols)
for want in ("order_type","payment_method","customer_name","customer_mobile","customer_address","customer_pincode","idempotency_key"):
    print(("OK  " if want in cols else "MISS"), want)
print("tables added:", [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type=\"table\" AND name IN (\"user_consents\",\"webhook_dedup\",\"whatsapp_outbox\",\"serviceable_pincodes\",\"carts\",\"cart_items\",\"checkout_sessions\")")])
