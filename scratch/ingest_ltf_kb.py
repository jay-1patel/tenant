import sqlite3
import re
from pathlib import Path
import json

DB_PATH = "faq.db"
KNOWLEDGE_DIR = Path("clients/ltfinance/knowledge")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 1. Update tenant 9 in tenants table
c.execute("""
UPDATE tenants SET
    company_name = ?,
    whatsapp_number = ?,
    industry_type = ?,
    welcome_message = ?,
    system_prompt = ?,
    domain = ?
WHERE slug = 'ltfinance'
""", (
    "L&T Finance Limited",
    "+91 7378333451",
    "finance",
    "Welcome to L&T Finance! How can I assist you with your loans or account services today?",
    "You are the official AI virtual assistant for L&T Finance Limited, a leading RBI-registered NBFC. Assist customers with loan inquiries (Two-Wheeler, Personal, Home, Gold, SME, Tractor loans), self-service document downloads (SOA, Repayment Schedule, NOC, Interest Certificates), EMI payments, and grievance redressal. Maintain professional financial decorum, adhere to RBI guidelines, and never ask for or disclose sensitive credentials such as OTP, MPIN, or passwords.",
    "https://www.ltfs.com"
))
conn.commit()
print("Updated tenant 9 in tenants table.")

# 2. Ingest Markdown files into knowledge_base
c.execute("DELETE FROM knowledge_base WHERE tenant_id = 9")
conn.commit()

files = sorted(list(KNOWLEDGE_DIR.glob("*.md")))
for f in files:
    content = f.read_text(encoding="utf-8")
    title = f.stem.replace("_", " ").title()
    category = "Loans & Finance"
    tags = "ltfinance,loans,personal-loan,two-wheeler,home-loan,gold-loan,nbfc,emi"
    source = f.name
    
    # Split by markdown headers
    sections = re.split(r'\n(?=## )', content)
    chunks = [s.strip() for s in sections if s.strip()]
    chunks_json = json.dumps(chunks, ensure_ascii=False)
    
    c.execute("""
    INSERT INTO knowledge_base (title, category, content, tags, source, chunks_json, tenant_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (title, category, content, tags, source, chunks_json, 9))
    print(f"Inserted into knowledge_base: {title} ({len(chunks)} chunks)")

# 3. Ingest FAQs into faq_dataset
c.execute("DELETE FROM faq_dataset WHERE tenant_id = 9")
conn.commit()

faqs_path = KNOWLEDGE_DIR / "06_faqs.md"
faq_text = faqs_path.read_text(encoding="utf-8")
faq_blocks = re.findall(r'###\s*(Q\d+:\s*.*?)\n\*\*A:\*\*\s*(.*?)(?=\n###|\Z)', faq_text, re.DOTALL)
print(f"Extracted {len(faq_blocks)} Q&A pairs from 06_faqs.md")

for idx, (q, a) in enumerate(faq_blocks, 1):
    content_chunk = f"{q.strip()}\nA: {a.strip()}"
    c.execute("""
    INSERT INTO faq_dataset (source_file, content_type, content, page_number, module, tenant_id)
    VALUES (?, ?, ?, ?, ?, ?)
    """, ("ltfs_faqs.md", "faq", content_chunk, idx, "faq", 9))

conn.commit()
print(f"Inserted {len(faq_blocks)} FAQ entries into faq_dataset for tenant 9!")

count_kb = c.execute("SELECT count(*) FROM knowledge_base WHERE tenant_id = 9").fetchone()[0]
count_faq = c.execute("SELECT count(*) FROM faq_dataset WHERE tenant_id = 9").fetchone()[0]
print(f"Tenant 9 Totals: {count_kb} knowledge_base rows, {count_faq} faq_dataset rows.")

conn.close()
