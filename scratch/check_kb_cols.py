import sqlite3

conn = sqlite3.connect('faq.db')
c = conn.cursor()
for table in ['faq_dataset', 'knowledge_base']:
    c.execute(f"PRAGMA table_info({table})")
    print(f"\nColumns for {table}:")
    for col in c.fetchall():
        print(" ", col)
    c.execute(f"SELECT * FROM {table} LIMIT 2")
    print(f"Sample row from {table}:")
    for row in c.fetchall():
        print(" ", row)

conn.close()
