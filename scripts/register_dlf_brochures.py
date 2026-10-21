import sqlite3
import os
import json

import sys
sys.path.insert(0, '.')
from routing.config import DB_PATH
KB_DIR = r"c:\Users\Leeway\Desktop\chatbot2\backend\uploaded_files\kb"

brochures = [
    {
        "filename": "DLF_Master_Residential_Portfolio.pdf",
        "name": "DLF Master Residential Portfolio Deck",
        "module": "catalogue",
        "desc": "Complete overview of all DLF luxury residences, floors, and township developments across India."
    },
    {
        "filename": "DLF_The_Dahlias_Super_Luxury_Deck.pdf",
        "name": "The Dahlias Super Luxury Deck",
        "module": "product_brochure",
        "desc": "Ultra-luxury sky mansions on Golf Course Road, Sector 54, Gurugram."
    },
    {
        "filename": "DLF_The_Arbour_Luxury_Residences.pdf",
        "name": "The Arbour Luxury Residences Brochure",
        "module": "product_brochure",
        "desc": "4 BHK luxury high-rise towers on Golf Course Extension Road, Sector 63, Gurugram."
    },
    {
        "filename": "DLF_Privana_South_Project_Brochure.pdf",
        "name": "DLF Privana South & West Brochure",
        "module": "product_brochure",
        "desc": "4 BHK + Staff residences and penthouses in 116-acre township, Sector 76-77, Gurugram."
    },
    {
        "filename": "DLF_One_Midtown_Delhi_Brochure.pdf",
        "name": "DLF One Midtown Delhi Brochure",
        "module": "product_brochure",
        "desc": "2, 3 & 4 BHK luxury residences neighboring 128 acres of greenery in Moti Nagar, West Delhi."
    },
    {
        "filename": "DLF_Independent_Floors_Brochure.pdf",
        "name": "DLF Independent Luxury Floors Brochure",
        "module": "product_brochure",
        "desc": "Low-rise stilt + 4 floors living in DLF City Phases I-IV & Alameda Sector 73, Gurugram."
    },
    {
        "filename": "DLF_NRI_Investment_Legal_Handbook.pdf",
        "name": "DLF NRI Investment & Legal Handbook",
        "module": "general",
        "desc": "Official FEMA 1999 rules, RBI general permissions, banking, taxation & repatriation guide."
    }
]

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

# Remove previous DLF brochure records in admin_files
cur.execute("DELETE FROM admin_files WHERE tenant_id = 'dlf'")
conn.commit()

for b in brochures:
    fpath = os.path.join(KB_DIR, b["filename"])
    size = os.path.getsize(fpath) if os.path.exists(fpath) else 0
    url = f"/uploaded_files/kb/{b['filename']}"
    cur.execute("""
        INSERT INTO admin_files (name, ext, module, size, doc_id, file_path, url, tenant_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (b["filename"], "pdf", b["module"], size, None, fpath, url, "dlf"))
    print(f"Registered in admin_files: {b['filename']} ({size} bytes, url: {url})")

conn.commit()
conn.close()
print("All 7 brochures successfully registered in database for tenant 'dlf'!")
