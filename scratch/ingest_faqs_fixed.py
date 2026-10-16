import sqlite3
import re
from pathlib import Path

DB_PATH = "faq.db"
faqs_path = Path("clients/99destinations/knowledge/07_faqs.md")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Remove prior entries for tenant 8 in faq_dataset
c.execute("DELETE FROM faq_dataset WHERE tenant_id = 8")
conn.commit()

faq_text = faqs_path.read_text(encoding="utf-8")
faq_blocks = re.findall(r'###\s*(Q\d+:\s*.*?)\n\*\*A:\*\*\s*(.*?)(?=\n###|\Z)', faq_text, re.DOTALL)
print(f"Extracted {len(faq_blocks)} Q&A pairs from 07_faqs.md")

for idx, (q, a) in enumerate(faq_blocks, 1):
    content_chunk = f"{q.strip()}\nA: {a.strip()}"
    c.execute("""
    INSERT INTO faq_dataset (source_file, content_type, content, page_number, module, tenant_id)
    VALUES (?, ?, ?, ?, ?, ?)
    """, ("99destinations_faqs.md", "faq", content_chunk, idx, "faq", 8))

conn.commit()
print(f"Successfully inserted {len(faq_blocks)} FAQ entries into faq_dataset for tenant 8!")

# Check count
count_kb = c.execute("SELECT count(*) FROM knowledge_base WHERE tenant_id = 8").fetchone()[0]
count_faq = c.execute("SELECT count(*) FROM faq_dataset WHERE tenant_id = 8").fetchone()[0]
print(f"Tenant 8 Total: {count_kb} knowledge_base rows, {count_faq} faq_dataset rows.")

conn.close()
