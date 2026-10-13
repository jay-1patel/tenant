import sqlite3
c = sqlite3.connect("faq.db"); c.row_factory = sqlite3.Row
print("=== chat_history (all) ===")
for r in c.execute("SELECT id, wa_id, route, created_at, substr(message,1,24) m FROM chat_history ORDER BY id"):
    print("  ", dict(r))
print("=== processed_inbound_messages ===")
print("count:", c.execute("SELECT COUNT(*) FROM processed_inbound_messages").fetchone()[0])
for r in c.execute("SELECT message_id, wa_id, channel, processed_at FROM processed_inbound_messages ORDER BY processed_at DESC LIMIT 10"):
    print("  ", dict(r))
print("=== user_states ===")
for r in c.execute("SELECT wa_id, tenant_id, state, language, updated_at FROM user_states"):
    print("  ", {k: r[k] for k in r.keys()})
