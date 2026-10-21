import os
import sys
import json
import sqlite3
import numpy as np

# Add backend and root to sys.path
sys.path.insert(0, os.path.abspath("backend"))
sys.path.insert(0, os.path.abspath("."))

from routing.config import DB_PATH, EMBEDDING_MODEL_PATH
from shared.tenancy import store
from sentence_transformers import SentenceTransformer

def setup_dlf():
    print("=== 1. Ensuring DLF Tenant Registration ===")
    store.ensure_tenant(
        tenant_id="dlf",
        slug="dlf",
        vertical="real_estate",
        waba_phone_id="",
        display_name="DLF Limited | Luxury Residences & Commercial"
    )
    print("DLF tenant ensured in database!")

    print("\n=== 2. Loading Scraped DLF Data ===")
    with open("scraped_dlf_full.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    projects = data["residential_projects"]
    commercial = data["commercial_portfolio"]
    retail = data["retail_portfolio"]
    hospitality = data["hospitality_and_clubs"]
    faqs = data["nri_and_legal_faqs"]

    print("\n=== 3. Seeding DLF Products / Offerings ===")
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Clear previous dlf products if any
    cur.execute("DELETE FROM products WHERE tenant_id = 'dlf'")
    conn.commit()

    offering_count = 0

    # A. Residential Projects
    for p in projects:
        name = p["name"]
        slug = "dlf-" + name.lower().replace(" ", "-").replace("'", "").replace(",", "").replace("/", "-")[:50]
        category = p["category"]
        desc = p["description"]
        short_desc = f"{p['configurations']} in {p['locality']}, {p['city']}"
        price = p["estimated_price"]
        media_url = p.get("image_url") or "https://www.dlf.in/images/projects/8.jpg"
        detail_url = p.get("microsite_url") or "https://www.dlf.in/homes"
        attrs = {
            "city": p["city"],
            "locality": p["locality"],
            "property_type": p["property_type"],
            "configurations": p["configurations"],
            "tier": p["tier"],
            "rera_id": p["rera_id"]
        }

        cur.execute("""
            INSERT INTO products (
                name, slug, category, description, short_description,
                price, mrp, unit, moq, media_url, media_type, ingredients,
                sort_order, variants_json, stock_quantity, nutritional_facts,
                bulk_discount_tiers, attrs_json, short_label, detail_url,
                tenant_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            name, slug, category, desc, short_desc,
            price, "", "unit", "1", media_url, "image", "[]",
            offering_count, "[]", 10, None, "[]",
            json.dumps(attrs), p["property_type"], detail_url, "dlf"
        ))
        offering_count += 1

    # B. Commercial Projects
    for c in commercial:
        name = c["name"]
        slug = "dlf-" + name.lower().replace(" ", "-").replace("&", "and").replace(",", "")[:50]
        category = c["category"]
        desc = c["highlights"]
        short_desc = f"{c['leasable_area']} in {c['locality']}, {c['city']}"
        attrs = {
            "city": c["city"],
            "locality": c["locality"],
            "leasable_area": c["leasable_area"],
            "clients": c.get("clients", "Fortune 500 multinationals")
        }
        cur.execute("""
            INSERT INTO products (
                name, slug, category, description, short_description,
                price, mrp, unit, moq, media_url, media_type, ingredients,
                sort_order, variants_json, stock_quantity, nutritional_facts,
                bulk_discount_tiers, attrs_json, short_label, detail_url,
                tenant_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            name, slug, category, desc, short_desc,
            "Lease / On Request", "", "sq.ft", "5000 sq.ft",
            "https://www.dlf.in/images/offices.jpg", "image", "[]",
            offering_count, "[]", 5, None, "[]",
            json.dumps(attrs), "Grade-A Workspace", "https://www.dlf.in/offices/", "dlf"
        ))
        offering_count += 1

    # C. Retail Malls
    for r in retail:
        name = r["name"]
        slug = "dlf-" + name.lower().replace(" ", "-").replace("&", "and")[:50]
        category = "Retail & Shopping Destination"
        desc = r["highlights"]
        short_desc = f"{r['category']} ({r['area']}) in {r['city']}"
        attrs = {
            "city": r["city"],
            "locality": r["locality"],
            "area": r["area"]
        }
        cur.execute("""
            INSERT INTO products (
                name, slug, category, description, short_description,
                price, mrp, unit, moq, media_url, media_type, ingredients,
                sort_order, variants_json, stock_quantity, nutritional_facts,
                bulk_discount_tiers, attrs_json, short_label, detail_url,
                tenant_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            name, slug, category, desc, short_desc,
            "Retail Leasing Available", "", "store", "1",
            "https://www.dlf.in/images/retail.jpg", "image", "[]",
            offering_count, "[]", 10, None, "[]",
            json.dumps(attrs), "Mall Destination", "https://www.dlf.in/retail/", "dlf"
        ))
        offering_count += 1

    # D. Hospitality & Golf Clubs
    for h in hospitality:
        name = h["name"]
        slug = "dlf-" + name.lower().replace(" ", "-").replace("&", "and")[:50]
        category = "Hospitality & Championship Golf"
        desc = h["highlights"]
        short_desc = f"{h['category']} in {h['city']}"
        attrs = {
            "city": h["city"],
            "locality": h["locality"]
        }
        cur.execute("""
            INSERT INTO products (
                name, slug, category, description, short_description,
                price, mrp, unit, moq, media_url, media_type, ingredients,
                sort_order, variants_json, stock_quantity, nutritional_facts,
                bulk_discount_tiers, attrs_json, short_label, detail_url,
                tenant_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            name, slug, category, desc, short_desc,
            "Membership / Consultation", "", "membership", "1",
            "https://www.dlf.in/images/golf.jpg", "image", "[]",
            offering_count, "[]", 1, None, "[]",
            json.dumps(attrs), "Exclusive Club", "https://www.dlf.in", "dlf"
        ))
        offering_count += 1

    conn.commit()
    print(f"Successfully inserted {offering_count} DLF offerings into database!")

    print("\n=== 4. Ingesting & Embedding DLF Knowledge Base Chunks ===")
    # Remove existing DLF chunks from faq_dataset
    cur.execute("DELETE FROM faq_dataset WHERE tenant_id = 'dlf'")
    conn.commit()

    kb_dir = r"clients\dlf\knowledge"
    model = SentenceTransformer(EMBEDDING_MODEL_PATH)
    chunk_rows = []

    # Read all KB markdown files
    for fname in sorted(os.listdir(kb_dir)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(kb_dir, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()

        # Split markdown into sections by '## ' or '---'
        raw_sections = [s.strip() for s in content.split("## ") if s.strip()]
        for sec in raw_sections:
            if not sec:
                continue
            sec_text = "## " + sec if not sec.startswith("#") else sec
            # If section is very long, split by paragraphs
            if len(sec_text) > 1500:
                paragraphs = [p.strip() for p in sec_text.split("\n\n") if len(p.strip()) > 30]
                for p in paragraphs:
                    chunk_rows.append((fname, p, "kb"))
            else:
                chunk_rows.append((fname, sec_text, "kb"))

    # Also add individual Q&A pairs from NRI FAQs
    for idx, faq in enumerate(faqs, 1):
        qa_text = f"Question: {faq['question']}\nAnswer: {faq['answer']}"
        chunk_rows.append((f"07_nri_investments_and_legal_faqs.md", qa_text, "faq"))

    print(f"Total chunks prepared for embedding: {len(chunk_rows)}")
    print("Computing embeddings with BGE-M3 model...")

    texts_to_embed = [r[1] for r in chunk_rows]
    embeddings = model.encode(texts_to_embed, batch_size=32, show_progress_bar=True, convert_to_numpy=True)
    embeddings = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-10)

    # Insert into faq_dataset
    for (src_file, text_chunk, mod), emb in zip(chunk_rows, embeddings):
        emb_blob = emb.astype(np.float32).tobytes()
        cur.execute("""
            INSERT INTO faq_dataset (
                source_file, content_type, content, page_number,
                embedding, media_url, media_type, module, tenant_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (
            src_file, "text", text_chunk, 1,
            emb_blob, None, None, mod, "dlf"
        ))

    conn.commit()
    conn.close()
    print(f"Ingested and committed {len(chunk_rows)} embedded chunks into faq_dataset for tenant 'dlf'!")

    print("\n=== 5. Rebuilding FAQ Hybrid FAISS Index ===")
    from faq.service import faq_index
    faq_index.build(force=True)
    print("FAQ Hybrid FAISS Index rebuild complete! Total vectors in index:", faq_index.index.ntotal if faq_index.index else 0)

if __name__ == "__main__":
    setup_dlf()
