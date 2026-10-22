"""Ingest and align all real estate tenant data for both:
1. DLF Limited (tenant_id = 11, slug = 'dlf')
2. Skyline Realty & Developers (tenant_id = 10, slug = 'skylinerealty')

Guarantees:
- DLF's 172 FAQ chunks updated from tenant_id=1 to tenant_id=11.
- DLF's 7 knowledge base markdown files registered in knowledge_base (tenant_id=11).
- DLF's 7 brochures updated to tenant_id='11' in admin_files, and brochure URLs attached to products.
- Skyline Realty's 8 property offerings inserted into products (tenant_id=10).
- Skyline Realty's 6 knowledge base files chunked, embedded with BGE-M3, and stored in faq_dataset (tenant_id=10).
- Skyline Realty's knowledge_base table populated (tenant_id=10).
- FAQ hybrid index rebuilt (dense FAISS + sparse BM25).
"""

import os
import sys
import json
import re
import sqlite3
import numpy as np

# Set project paths
sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("."))

from routing.config import DB_PATH, EMBEDDING_MODEL_PATH
from sentence_transformers import SentenceTransformer

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def step1_fix_dlf():
    print("\n" + "="*70)
    print("STEP 1: FIXING DLF DATA (tenant_id = 11)")
    print("="*70)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    dlf_md_files = [
        '01_company_and_overview.md',
        '02_super_luxury_and_luxury_residences.md',
        '03_independent_floors_and_plotted_estates.md',
        '04_commercial_offices_and_it_parks.md',
        '05_retail_malls_and_lifestyle_clubs.md',
        '06_booking_payments_and_loans.md',
        '07_nri_investments_and_legal_faqs.md'
    ]

    # 1. Update faq_dataset tenant_id
    cur.execute(f"""
        UPDATE faq_dataset
        SET tenant_id = 11
        WHERE source_file IN ({','.join(['?']*len(dlf_md_files))})
    """, dlf_md_files)
    moved_chunks = cur.rowcount
    conn.commit()
    print(f"-> Assigned {moved_chunks} DLF knowledge chunks in faq_dataset to tenant_id = 11")

    # 2. Ingest DLF markdown files into knowledge_base table for tenant 11
    cur.execute("DELETE FROM knowledge_base WHERE tenant_id = 11")
    conn.commit()

    dlf_kb_dir = os.path.join("clients", "dlf", "knowledge")
    kb_count = 0
    if os.path.exists(dlf_kb_dir):
        for fname in sorted(os.listdir(dlf_kb_dir)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(dlf_kb_dir, fname)
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            title = fname.replace(".md", "").replace("_", " ").title()
            sections = [s.strip() for s in re.split(r'\n(?=## )', content) if s.strip()]
            cur.execute("""
                INSERT INTO knowledge_base (title, category, content, tags, source, chunks_json, tenant_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                title,
                "Real Estate & Luxury Properties",
                content,
                "dlf,realestate,luxury,apartments,floors,commercial,malls,golf,nri",
                fname,
                json.dumps(sections, ensure_ascii=False),
                11
            ))
            kb_count += 1
    conn.commit()
    print(f"-> Ingested {kb_count} documents into knowledge_base for DLF (tenant_id = 11)")

    # 3. Update admin_files for DLF brochures
    cur.execute("""
        UPDATE admin_files
        SET tenant_id = '11'
        WHERE name LIKE 'DLF_%'
    """)
    brochures_updated = cur.rowcount
    conn.commit()
    print(f"-> Updated {brochures_updated} DLF brochure records in admin_files to tenant_id = '11'")

    # 4. Attach brochure URLs to matching DLF products
    brochure_mappings = [
        ("%Dahlia%", "/uploaded_files/kb/DLF_The_Dahlias_Super_Luxury_Deck.pdf"),
        ("%Arbour%", "/uploaded_files/kb/DLF_The_Arbour_Luxury_Residences.pdf"),
        ("%Privana%", "/uploaded_files/kb/DLF_Privana_South_Project_Brochure.pdf"),
        ("%Midtown%", "/uploaded_files/kb/DLF_One_Midtown_Delhi_Brochure.pdf"),
        ("%Floor%", "/uploaded_files/kb/DLF_Independent_Floors_Brochure.pdf"),
    ]
    cur.execute("SELECT id, name, attrs_json FROM products WHERE tenant_id = 11")
    rows = cur.fetchall()
    updated_prods = 0
    for pid, pname, attrs_raw in rows:
        attrs = json.loads(attrs_raw) if attrs_raw else {}
        matched_brochure = None
        for pattern, b_url in brochure_mappings:
            clean_pat = pattern.replace("%", "").lower()
            if clean_pat in pname.lower():
                matched_brochure = b_url
                break
        if not matched_brochure:
            matched_brochure = "/uploaded_files/kb/DLF_Master_Residential_Portfolio.pdf"

        attrs["brochure_url"] = matched_brochure
        cur.execute("UPDATE products SET attrs_json = ? WHERE id = ?", (json.dumps(attrs), pid))
        updated_prods += 1
    conn.commit()
    conn.close()
    print(f"-> Attached brochure URLs to {updated_prods} DLF products in database")


def step2_seed_skyline_products():
    print("\n" + "="*70)
    print("STEP 2: SEEDING SKYLINE REALTY PRODUCTS (tenant_id = 10)")
    print("="*70)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Clear existing products for tenant 10
    cur.execute("DELETE FROM products WHERE tenant_id IN (10, '10', 'skylinerealty')")
    conn.commit()

    products = [
        {
            "name": "Skyline Elegance 2 BHK Luxury",
            "slug": "skyline-elegance-2bhk",
            "category": "Luxury Residential Apartments",
            "price": "₹68 Lakhs",
            "short_desc": "2 BHK Luxury (820 sq.ft carpet) at S.G. Highway, near Science City Junction",
            "desc": (
                "Skyline Elegance 2 BHK Luxury apartment offers 820 sq.ft carpet (1,180 sq.ft super built-up). "
                "Features 2 Bedrooms, 2 Bathrooms, 2 Balconies, and Utility Area. "
                "Equipped with Italian marble finish vitrified tiles, Kohler sanitaryware, and smart home ready wiring. "
                "Towers A & B are Ready-to-Move; Towers C & D scheduled for Dec 2026."
            ),
            "unit": "apartment",
            "media_url": "https://images.unsplash.com/photo-1545324418-cc1a3fa10c00?w=800",
            "short_label": "2 BHK Luxury Flat",
            "detail_url": "https://www.skylinerealty.com/elegance",
            "attrs": {
                "city": "Ahmedabad",
                "locality": "S.G. Highway, near Science City Junction",
                "carpet_area": "820 sq.ft.",
                "super_builtup_area": "1,180 sq.ft.",
                "configuration": "2 BHK (2 Bed, 2 Bath, 2 Balconies, Utility)",
                "rera_id": "PR/GJ/AHMEDABAD/RESIDENTIAL/RAA09876/2024",
                "possession": "Ready-to-Move (Towers A & B) / Dec 2026 (Towers C & D)",
                "parking": "1 Covered Basement Parking Slot Included",
                "property_type": "Residential Apartment",
                "amenities": "Clubhouse, Temperature-controlled pool, Technogym, Mini-theater, Zen garden"
            }
        },
        {
            "name": "Skyline Elegance 2.5 BHK Smart",
            "slug": "skyline-elegance-2-5bhk",
            "category": "Luxury Residential Apartments",
            "price": "₹79 Lakhs",
            "short_desc": "2.5 BHK Smart with WFH Study (960 sq.ft carpet) at S.G. Highway",
            "desc": (
                "Skyline Elegance 2.5 BHK Smart home is designed for modern hybrid professionals. "
                "Spanning 960 sq.ft carpet (1,380 sq.ft super built-up), it includes 2 Bedrooms, "
                "a dedicated Work-From-Home Study room, 2 Bathrooms, and 2 Balconies. "
                "Possession scheduled for December 2026."
            ),
            "unit": "apartment",
            "media_url": "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800",
            "short_label": "2.5 BHK Smart Flat",
            "detail_url": "https://www.skylinerealty.com/elegance",
            "attrs": {
                "city": "Ahmedabad",
                "locality": "S.G. Highway, near Science City Junction",
                "carpet_area": "960 sq.ft.",
                "super_builtup_area": "1,380 sq.ft.",
                "configuration": "2.5 BHK (2 Bed + WFH Study, 2 Bath, 2 Balconies)",
                "rera_id": "PR/GJ/AHMEDABAD/RESIDENTIAL/RAA09876/2024",
                "possession": "Dec 2026",
                "parking": "1 Covered Basement Parking Slot Included",
                "property_type": "Residential Apartment",
                "amenities": "Co-working pods, High-speed Wi-Fi lounge, Clubhouse, Infinity pool"
            }
        },
        {
            "name": "Skyline Elegance 3 BHK Premium",
            "slug": "skyline-elegance-3bhk",
            "category": "Luxury Residential Apartments",
            "price": "₹96 Lakhs",
            "short_desc": "3 BHK Premium (1,150 sq.ft carpet) with Living Deck at S.G. Highway",
            "desc": (
                "Skyline Elegance 3 BHK Premium offers generous spaces spanning 1,150 sq.ft carpet "
                "(1,650 sq.ft super built-up). Includes 3 expansive Bedrooms, 3 Bathrooms, "
                "an open Living & Dining Deck, and a separate utility balcony. "
                "Ready-to-Move options available in Towers A & B."
            ),
            "unit": "apartment",
            "media_url": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?w=800",
            "short_label": "3 BHK Premium Flat",
            "detail_url": "https://www.skylinerealty.com/elegance",
            "attrs": {
                "city": "Ahmedabad",
                "locality": "S.G. Highway, near Science City Junction",
                "carpet_area": "1,150 sq.ft.",
                "super_builtup_area": "1,650 sq.ft.",
                "configuration": "3 BHK (3 Bed, 3 Bath, Living Deck, Separate Utility)",
                "rera_id": "PR/GJ/AHMEDABAD/RESIDENTIAL/RAA09876/2024",
                "possession": "Ready-to-Move / Dec 2026",
                "parking": "1 Covered Basement Parking Slot Included",
                "property_type": "Residential Apartment",
                "amenities": "Full-size badminton court, Squash court, Rooftop cafeteria, Spa & Sauna"
            }
        },
        {
            "name": "Skyline Grandeur 4 BHK Sky Residence",
            "slug": "skyline-grandeur-4bhk-sky-residence",
            "category": "Ultra-Luxury Villas & Penthouses",
            "price": "₹1.75 Cr",
            "short_desc": "4 BHK Sky Residence (2,150 sq.ft carpet) with double-height balcony, Sindhu Bhavan Ext.",
            "desc": (
                "Skyline Grandeur 4 BHK Sky Residence is a bespoke ultra-luxury home on Sindhu Bhavan Extension. "
                "Featuring 2,150 sq.ft carpet (3,100 sq.ft super built-up) with 4 En-suite Master Bedrooms, "
                "Servant Quarters with separate entrance, Double-height panoramic balcony, and 2 Covered Car Parks. "
                "Possession: March 2027."
            ),
            "unit": "residence",
            "media_url": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800",
            "short_label": "4 BHK Sky Residence",
            "detail_url": "https://www.skylinerealty.com/grandeur",
            "attrs": {
                "city": "Ahmedabad",
                "locality": "Sindhu Bhavan Extension",
                "carpet_area": "2,150 sq.ft.",
                "super_builtup_area": "3,100 sq.ft.",
                "configuration": "4 BHK + Servant Quarters (4 En-suite Bath, Double-Height Balcony)",
                "rera_id": "PR/GJ/AHMEDABAD/RESIDENTIAL/RAA11245/2024",
                "possession": "March 2027",
                "parking": "2 Dedicated Covered Car Parking Slots",
                "property_type": "Sky Residence",
                "amenities": "Private lift lobby, 50,000 sq.ft clubhouse, Dolby Atmos preview theater, EV stations"
            }
        },
        {
            "name": "Skyline Grandeur 4 BHK Duplex Penthouse",
            "slug": "skyline-grandeur-4bhk-duplex-penthouse",
            "category": "Ultra-Luxury Villas & Penthouses",
            "price": "₹2.85 Cr",
            "short_desc": "4 BHK Duplex Penthouse (3,200 sq.ft carpet) with Private Rooftop Jacuzzi & Terrace Garden",
            "desc": (
                "Crown jewel living at Skyline Grandeur. 3,200 sq.ft carpet (4,600 sq.ft super built-up) "
                "spanning the top two floors. Features a Private Rooftop Jacuzzi, Landscaped Terrace Garden, "
                "Double-height grand living room, 4 Luxury Bedroom suites, and 3 Reserved Basement Parking Slots."
            ),
            "unit": "penthouse",
            "media_url": "https://images.unsplash.com/photo-1512915922686-57c11dde9b6b?w=800",
            "short_label": "Duplex Penthouse",
            "detail_url": "https://www.skylinerealty.com/grandeur",
            "attrs": {
                "city": "Ahmedabad",
                "locality": "Sindhu Bhavan Extension",
                "carpet_area": "3,200 sq.ft.",
                "super_builtup_area": "4,600 sq.ft.",
                "configuration": "4 BHK Duplex (Private Jacuzzi, Terrace Garden, 4 Bed Suites)",
                "rera_id": "PR/GJ/AHMEDABAD/RESIDENTIAL/RAA11245/2024",
                "possession": "March 2027",
                "parking": "3 Reserved Basement Parking Slots",
                "property_type": "Duplex Penthouse",
                "amenities": "Private Rooftop Jacuzzi, Private Elevators, Banqueting lawn for 300+ guests"
            }
        },
        {
            "name": "Skyline Business Hub Boutique Offices",
            "slug": "skyline-business-hub-boutique-offices",
            "category": "Grade-A Commercial Offices",
            "price": "₹52 Lakhs",
            "short_desc": "Boutique Corporate Offices (650–1,800 sq.ft.) at SG Highway Financial District",
            "desc": (
                "Grade-A Commercial workspace located at SG Highway Central Financial District. "
                "Sizes range from 650 sq.ft. to 1,800 sq.ft., ideal for corporate law firms, CAs, "
                "wealth managers, and medical clinics. 100% DG backup, 6 high-speed Mitsubishi lifts, "
                "and double-height air-conditioned lobby with access control."
            ),
            "unit": "office",
            "media_url": "https://images.unsplash.com/photo-1497366216548-37526070297c?w=800",
            "short_label": "Boutique Office",
            "detail_url": "https://www.skylinerealty.com/business-hub",
            "attrs": {
                "city": "Ahmedabad",
                "locality": "S.G. Highway Financial District",
                "area": "650 sq.ft. to 1,800 sq.ft.",
                "rera_id": "PR/GJ/AHMEDABAD/COMMERCIAL/RAA07654/2023",
                "possession": "Ready for Fit-outs",
                "property_type": "Commercial Office",
                "amenities": "6 Mitsubishi Elevators, 100% DG Backup, 800+ Car Basement Parking, Rooftop Cafe"
            }
        },
        {
            "name": "Skyline Business Hub Corporate Floor Plates",
            "slug": "skyline-business-hub-corporate-floor-plates",
            "category": "Grade-A Commercial Offices",
            "price": "₹45/sq.ft. (Lease) / ₹6,800/sq.ft. (Sale)",
            "short_desc": "Large IT / Corporate Floor Plates (5,000–25,000 sq.ft.) column-free design at SG Highway",
            "desc": (
                "Full floor and multi-floor commercial plates spanning 5,000 sq.ft. to 25,000 sq.ft. "
                "Column-free design with 3.8-meter clear ceiling heights for optimal workstation density. "
                "Available on lease (₹45/sq.ft. warm shell) or outright sale (₹6,800/sq.ft.). "
                "IGBC Gold certified sustainable building with EV charging stations."
            ),
            "unit": "floor",
            "media_url": "https://images.unsplash.com/photo-1497215728101-856f4ea42174?w=800",
            "short_label": "Corporate Floor Plate",
            "detail_url": "https://www.skylinerealty.com/business-hub",
            "attrs": {
                "city": "Ahmedabad",
                "locality": "S.G. Highway Financial District",
                "area": "5,000 sq.ft. to 25,000 sq.ft.",
                "ceiling_height": "3.8 meters",
                "rera_id": "PR/GJ/AHMEDABAD/COMMERCIAL/RAA07654/2023",
                "possession": "Immediate Handover",
                "property_type": "Corporate Floor Plate",
                "amenities": "Central HVAC chillers, Dedicated service lifts, Turnstile security, Conference halls"
            }
        },
        {
            "name": "Skyline Business Hub Retail Showrooms",
            "slug": "skyline-business-hub-retail-showrooms",
            "category": "High-Street Retail Showrooms",
            "price": "₹1.65 Cr",
            "short_desc": "High-Street Road-Facing Retail Showrooms (1,200–4,500 sq.ft.) with 18-ft frontage",
            "desc": (
                "High-footfall Ground and First Floor commercial retail spaces facing SG Highway main corridor. "
                "Units from 1,200 sq.ft. to 4,500 sq.ft. with prominent 18-ft clear glass frontage. "
                "Perfect for national banks, luxury jewelers, electronics anchors, and fine-dine restaurants."
            ),
            "unit": "showroom",
            "media_url": "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?w=800",
            "short_label": "Retail Showroom",
            "detail_url": "https://www.skylinerealty.com/business-hub",
            "attrs": {
                "city": "Ahmedabad",
                "locality": "S.G. Highway Financial District",
                "area": "1,200 sq.ft. to 4,500 sq.ft.",
                "frontage": "18-ft clear glass frontage",
                "rera_id": "PR/GJ/AHMEDABAD/COMMERCIAL/RAA07654/2023",
                "possession": "Ready for Interior Work",
                "property_type": "Retail Showroom",
                "amenities": "Dedicated customer valet parking, High-visibility branding facade, 24x7 security"
            }
        }
    ]

    for idx, p in enumerate(products):
        cur.execute("""
            INSERT INTO products (
                name, slug, category, description, short_description,
                price, mrp, unit, moq, media_url, media_type, ingredients,
                sort_order, variants_json, stock_quantity, nutritional_facts,
                bulk_discount_tiers, attrs_json, short_label, detail_url,
                tenant_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            p["name"], p["slug"], p["category"], p["desc"], p["short_desc"],
            p["price"], "", p["unit"], "1", p["media_url"], "image", "[]",
            idx, "[]", 5, None, "[]",
            json.dumps(p["attrs"], ensure_ascii=False), p["short_label"], p["detail_url"], 10
        ))

    conn.commit()
    conn.close()
    print(f"-> Successfully inserted {len(products)} Skyline Realty products under tenant_id = 10")


def step3_ingest_skyline_knowledge():
    print("\n" + "="*70)
    print("STEP 3: INGESTING & EMBEDDING SKYLINE REALTY KNOWLEDGE (tenant_id = 10)")
    print("="*70)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    kb_dir = os.path.join("clients", "skylinerealty", "knowledge")
    if not os.path.exists(kb_dir):
        print(f"ERROR: Directory not found: {kb_dir}")
        conn.close()
        return

    # 1. Update knowledge_base table
    cur.execute("DELETE FROM knowledge_base WHERE tenant_id = 10")
    conn.commit()

    kb_files = sorted([f for f in os.listdir(kb_dir) if f.endswith(".md")])
    for fname in kb_files:
        fpath = os.path.join(kb_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        title = fname.replace(".md", "").replace("_", " ").title()
        sections = [s.strip() for s in re.split(r'\n(?=## )', content) if s.strip()]
        cur.execute("""
            INSERT INTO knowledge_base (title, category, content, tags, source, chunks_json, tenant_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            title,
            "Real Estate & Properties",
            content,
            "skyline,realestate,apartments,flats,villas,bhk,commercial,rera,site-visit",
            fname,
            json.dumps(sections, ensure_ascii=False),
            10
        ))
    conn.commit()
    print(f"-> Updated {len(kb_files)} files in knowledge_base for tenant_id = 10")

    # 2. Prepare chunks for faq_dataset
    cur.execute("DELETE FROM faq_dataset WHERE tenant_id = 10")
    conn.commit()

    chunks_to_embed = []

    for fname in kb_files:
        fpath = os.path.join(kb_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        if fname == "06_rera_and_faq.md":
            # Extract Q&A pairs specifically for FAQ module
            qas = re.findall(r'###\s*(Q\d+[\.:]\s*.*?)\n\s*A[\.:]\s*(.*?)(?=\n###|\Z)', content, re.DOTALL)
            for q, a in qas:
                qa_text = f"{q.strip()}\nAnswer: {a.strip()}"
                chunks_to_embed.append((fname, qa_text, "faq"))

            # Also add the top sections (RERA and Site visit info)
            top_sections = content.split("## 3. Frequently Asked Questions")[0]
            sec_blocks = [s.strip() for s in top_sections.split("## ") if s.strip()]
            for sec in sec_blocks:
                sec_text = "## " + sec if not sec.startswith("#") else sec
                chunks_to_embed.append((fname, sec_text, "kb"))
        else:
            sec_blocks = [s.strip() for s in content.split("## ") if s.strip()]
            for sec in sec_blocks:
                sec_text = "## " + sec if not sec.startswith("#") else sec
                if len(sec_text) > 1500:
                    paragraphs = [p.strip() for p in sec_text.split("\n\n") if len(p.strip()) > 30]
                    for p in paragraphs:
                        chunks_to_embed.append((fname, p, "kb"))
                else:
                    chunks_to_embed.append((fname, sec_text, "kb"))

    print(f"-> Prepared {len(chunks_to_embed)} chunks for Skyline Realty embedding.")
    print("-> Loading BGE-M3 embedding model...")
    model = SentenceTransformer(EMBEDDING_MODEL_PATH)

    texts = [c[1] for c in chunks_to_embed]
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=True, convert_to_numpy=True)
    embeddings = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10)

    for idx, ((fname, text, mod), emb) in enumerate(zip(chunks_to_embed, embeddings), 1):
        emb_blob = emb.astype(np.float32).tobytes()
        cur.execute("""
            INSERT INTO faq_dataset (
                source_file, content_type, content, page_number,
                embedding, media_url, media_type, module, tenant_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            fname, "text" if mod == "kb" else "faq", text, idx,
            emb_blob, None, None, mod, 10
        ))

    conn.commit()
    conn.close()
    print(f"-> Successfully inserted {len(chunks_to_embed)} embedded chunks into faq_dataset for tenant_id = 10")


def step4_rebuild_index():
    print("\n" + "="*70)
    print("STEP 4: REBUILDING HYBRID FAQ FAISS & BM25 INDEX")
    print("="*70)
    from faq.service import faq_index
    faq_index.build(force=True)
    total_vectors = faq_index.index.ntotal if faq_index.index else 0
    print(f"-> Hybrid FAQ index successfully rebuilt! Total vectors indexed: {total_vectors}")


def step5_verify():
    print("\n" + "="*70)
    print("STEP 5: VERIFICATION & AUDIT")
    print("="*70)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Product counts
    cur.execute("SELECT tenant_id, count(*) FROM products GROUP BY tenant_id")
    print("Products per tenant_id:")
    for r in cur.fetchall():
        print(" ", dict(r) if hasattr(r, 'keys') else r)

    # FAQ dataset chunk counts
    cur.execute("SELECT tenant_id, count(*) FROM faq_dataset GROUP BY tenant_id")
    print("\nFAQ dataset chunks per tenant_id:")
    for r in cur.fetchall():
        print(" ", dict(r) if hasattr(r, 'keys') else r)

    # Knowledge base counts
    cur.execute("SELECT tenant_id, count(*) FROM knowledge_base GROUP BY tenant_id")
    print("\nKnowledge base entries per tenant_id:")
    for r in cur.fetchall():
        print(" ", dict(r) if hasattr(r, 'keys') else r)

    conn.close()

if __name__ == "__main__":
    step1_fix_dlf()
    step2_seed_skyline_products()
    step3_ingest_skyline_knowledge()
    step4_rebuild_index()
    step5_verify()
    print("\n" + "="*70)
    print("ALL REAL ESTATE DATA INGESTION & INTEGRATION COMPLETE!")
    print("="*70)
