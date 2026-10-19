import sqlite3
import re
from pathlib import Path
import json

DB_PATH = "faq.db"
KNOWLEDGE_DIR = Path("clients/skylinerealty/knowledge")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 1. Update tenant 10 in tenants table
c.execute("""
UPDATE tenants SET
    company_name = ?,
    whatsapp_number = ?,
    industry_type = ?,
    vertical = ?,
    display_name = ?,
    welcome_message = ?,
    system_prompt = ?,
    domain = ?
WHERE id = 10 OR slug = 'skylinerealty'
""", (
    "Skyline Realty & Developers",
    "+91 98765 43210",
    "real_estate",
    "real_estate",
    "Skyline Realty",
    "Welcome to Skyline Realty! 🏙️ Discover our premium residential residences & commercial spaces, or schedule a guided site visit today.",
    "You are the official AI Property Advisor for Skyline Realty & Developers, a premier developer with 18+ years of excellence. Assist buyers with residential apartment configurations (2, 3 & 4 BHK), luxury villas, commercial IT offices, pricing plans, construction status, RERA numbers, and site visit scheduling. Maintain a polished, professional, and consultative tone.",
    "https://www.skylinerealty.com"
))
conn.commit()
print("Updated tenant 10 in tenants table.")

# 2. Ingest Markdown files into knowledge_base
c.execute("DELETE FROM knowledge_base WHERE tenant_id = 10")
conn.commit()

files = sorted(list(KNOWLEDGE_DIR.glob("*.md")))
for f in files:
    content = f.read_text(encoding="utf-8")
    title = f.stem.replace("_", " ").title()
    category = "Real Estate & Properties"
    tags = "realestate,property,apartments,flats,villas,bhk,luxury,rera,site-visit"
    source = f.name
    
    sections = re.split(r'\n(?=## )', content)
    chunks = [s.strip() for s in sections if s.strip()]
    chunks_json = json.dumps(chunks, ensure_ascii=False)
    
    c.execute("""
    INSERT INTO knowledge_base (title, category, content, tags, source, chunks_json, tenant_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (title, category, content, tags, source, chunks_json, 10))
    print(f"Inserted into knowledge_base: {title} ({len(chunks)} chunks)")

# 3. Ingest FAQs into faq_dataset
c.execute("DELETE FROM faq_dataset WHERE tenant_id = 10")
conn.commit()

faqs_path = KNOWLEDGE_DIR / "06_rera_and_faq.md"
faq_text = faqs_path.read_text(encoding="utf-8")
faq_blocks = re.findall(r'###\s*(Q\d+[\.:]\s*.*?)\n\s*A[\.:]\s*(.*?)(?=\n###|\Z)', faq_text, re.DOTALL)
print(f"Extracted {len(faq_blocks)} Q&A pairs from 06_rera_and_faq.md")

for idx, (q, a) in enumerate(faq_blocks, 1):
    content_chunk = f"{q.strip()}\nA: {a.strip()}"
    c.execute("""
    INSERT INTO faq_dataset (source_file, content_type, content, page_number, module, tenant_id)
    VALUES (?, ?, ?, ?, ?, ?)
    """, ("skyline_faqs.md", "faq", content_chunk, idx, "faq", 10))

conn.commit()
print(f"Inserted {len(faq_blocks)} FAQ entries into faq_dataset for tenant 10!")

count_kb = c.execute("SELECT count(*) FROM knowledge_base WHERE tenant_id = 10").fetchone()[0]
count_faq = c.execute("SELECT count(*) FROM faq_dataset WHERE tenant_id = 10").fetchone()[0]
print(f"Tenant 10 Totals: {count_kb} knowledge_base rows, {count_faq} faq_dataset rows.")

conn.close()
