import sqlite3
import os
from pathlib import Path
import json
import re

DB_PATH = "faq.db"
KNOWLEDGE_DIR = Path("clients/99destinations/knowledge")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# 1. Update tenant 8 details
c.execute("""
UPDATE tenants SET
    company_name = ?,
    whatsapp_number = ?,
    industry_type = ?,
    welcome_message = ?,
    system_prompt = ?,
    domain = ?
WHERE slug = '99destinations'
""", (
    "99 Destinations Holidays Pvt. Ltd.",
    "+91 7874833999",
    "tours_travel",
    "Welcome to 99 Destinations Holidays! How may we assist with your travel plans today?",
    "You are the official AI travel assistant for 99 Destinations Holidays Pvt. Ltd., an officially recognized Gujarat Tourism tour operator (TCGL) and IATA/IATO/TAAI accredited travel agency. Assist travelers with Gujarat tours, spiritual packages, wildlife safaris, Rann Utsav, Seema Darshan, domestic holidays, international tours, cruises, flights, and visas. Be polite, encouraging, and informative.",
    "https://www.99destinations.in"
))
conn.commit()
print("Updated tenant 8 record in tenants table.")

# 2. Ingest Markdown Knowledge files into knowledge_base
# Remove any prior entries for tenant 8
c.execute("DELETE FROM knowledge_base WHERE tenant_id = 8")
conn.commit()

files = sorted(list(KNOWLEDGE_DIR.glob("*.md")))
print(f"Found {len(files)} knowledge files.")

for f in files:
    content = f.read_text(encoding="utf-8")
    title = f.stem.replace("_", " ").title()
    category = "Tours & Travel"
    tags = "99destinations,gujarat-tourism,tours,travel,holidays,flights,visas,rann-utsav"
    source = f.name
    
    # Simple chunking by sections
    sections = re.split(r'\n(?=## )', content)
    chunks = [s.strip() for s in sections if s.strip()]
    chunks_json = json.dumps(chunks, ensure_ascii=False)
    
    c.execute("""
    INSERT INTO knowledge_base (title, category, content, tags, source, chunks_json, tenant_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (title, category, content, tags, source, chunks_json, 8))
    print(f"Inserted into knowledge_base: {title} ({len(chunks)} chunks)")

# 3. Ingest FAQs into faq_dataset
# Parse 07_faqs.md
faqs_path = KNOWLEDGE_DIR / "07_faqs.md"
if faqs_path.exists():
    # Remove prior faqs for tenant 8 if column exists
    c.execute("PRAGMA table_info(faq_dataset)")
    faq_cols = [col[1] for col in c.fetchall()]
    print("faq_dataset columns:", faq_cols)
    
    has_tenant_id = "tenant_id" in faq_cols
    if has_tenant_id:
        c.execute("DELETE FROM faq_dataset WHERE tenant_id = 8")
        conn.commit()
    
    faq_text = faqs_path.read_text(encoding="utf-8")
    faq_blocks = re.findall(r'###\s*Q\d+:\s*(.*?)\n\*\*A:\*\*\s*(.*?)(?=\n###|\Z)', faq_text, re.DOTALL)
    print(f"Extracted {len(faq_blocks)} Q&A pairs from 07_faqs.md")
    
    for q, a in faq_blocks:
        q_clean = q.strip()
        a_clean = a.strip()
        category = "Travel FAQ"
        
        if has_tenant_id:
            c.execute("""
            INSERT INTO faq_dataset (question, answer, category, tenant_id)
            VALUES (?, ?, ?, ?)
            """, (q_clean, a_clean, category, 8))
        else:
            c.execute("""
            INSERT INTO faq_dataset (question, answer, category)
            VALUES (?, ?, ?)
            """, (q_clean, a_clean, category))
    conn.commit()
    print(f"Inserted {len(faq_blocks)} FAQs into faq_dataset.")

conn.close()
print("All ingestion completed successfully!")
