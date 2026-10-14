import sqlite3

for fn in ['FAQ.DB.bak-20261012-chat_history', 'faq.db.bak-20261013-141820-services', 'faq.db.bak-20261013-fix-benefits-support']:
    try:
        conn = sqlite3.connect(fn)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print(f"{fn}:")
        print(f"  Tables count: {len(tables)}")
        if 'admins' in tables:
            admins = conn.execute("SELECT username, role FROM admins").fetchall()
            print(f"  Admins: {admins}")
        if 'chat_history' in tables:
            count = conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
            print(f"  Chat rows: {count}")
        if 'user_states' in tables:
            users = conn.execute("SELECT COUNT(*) FROM user_states").fetchone()[0]
            print(f"  Users in user_states: {users}")
        conn.close()
    except Exception as e:
        print(f"{fn} error: {e}")
