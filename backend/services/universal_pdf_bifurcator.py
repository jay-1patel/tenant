"""Universal PDF Ingestion & Bifurcation Engine.

Automatically classifies, bifurcates, and routes content from an uploaded PDF into:
1. Products & Offerings (saved to `products` staging table with is_active = 0)
2. FAQs (saved to `faq_dataset` table with content_type = 'qa')
3. Knowledge Base / Context (saved to `knowledge_base` table as semantic chunks)
4. Menu Action Suggestions (recommended top-level WhatsApp buttons <= 20 chars)
5. Business Profile & Contact Metadata (phone, email, address, RERA/license, hours)
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

import database as db

logger = logging.getLogger("pdf_bifurcator")

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADED_DIR = BASE_DIR / "uploaded_files"
BROCHURES_DIR = UPLOADED_DIR / "brochures"
PRODUCT_IMAGES_DIR = UPLOADED_DIR / "product_images"

os.makedirs(BROCHURES_DIR, exist_ok=True)
os.makedirs(PRODUCT_IMAGES_DIR, exist_ok=True)

MIN_IMG_WIDTH = 120
MIN_IMG_HEIGHT = 120


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").lower()).strip("_")
    return cleaned[:50] or f"item_{uuid.uuid4().hex[:6]}"


def _get_tenant_vertical(tenant_id: str) -> str:
    try:
        from shared.tenancy.loader import get_tenant_profile
        prof = get_tenant_profile(tenant_id)
        if prof and prof.vertical:
            return prof.vertical
    except Exception:
        pass
    try:
        from shared.tenancy import store
        rec = store.get_tenant(tenant_id)
        if rec and rec.get("vertical"):
            return rec["vertical"]
    except Exception:
        pass
    return "generic"


def _extract_page_assets(
    doc: fitz.Document, page: fitz.Page, page_num: int, tenant_id: str
) -> List[Dict[str, Any]]:
    """Extract embedded raster images from a page."""
    page_images = []
    try:
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            base_image = doc.extract_image(xref)
            if not base_image:
                continue
            w = base_image.get("width", 0)
            h = base_image.get("height", 0)
            if w < MIN_IMG_WIDTH or h < MIN_IMG_HEIGHT:
                continue

            raw_bytes = base_image.get("image")
            ext = (base_image.get("ext") or "jpg").lower()
            if ext == "jpeg":
                ext = "jpg"

            img_filename = f"{tenant_id}_p{page_num}_{img_idx}_{uuid.uuid4().hex[:6]}.{ext}"
            img_path = PRODUCT_IMAGES_DIR / img_filename

            try:
                pil_img = Image.open(io.BytesIO(raw_bytes))
                if pil_img.mode in ("RGBA", "P"):
                    pil_img = pil_img.convert("RGB")
                pil_img.save(img_path, format="JPEG", quality=88)
                page_images.append({
                    "url": f"/uploaded_files/product_images/{img_filename}",
                    "width": w,
                    "height": h,
                })
            except Exception as e:
                logger.debug("Image save error: %s", e)
    except Exception as e:
        logger.debug("Page image extraction error: %s", e)
    return page_images


def build_bifurcation_prompt(vertical: str, page_text: str, default_category: str = "") -> Tuple[str, str]:
    system_prompt = f"""You are an advanced document ingestion and data bifurcation engine for a multi-tenant business platform ({vertical} vertical).
Your task is to analyze the provided page text from a company document / brochure and strictly BIFURCATE the content into 5 distinct categories:

1. "products":
   - Distinct catalog offerings, properties, apartments, packages, services, or loans.
   - Each product must have:
     • "name": specific offering name
     • "category": category or segment (e.g. "Luxury High-Rise", "Domestic Tour", "Home Loan")
     • "price": price or starting rate (e.g. "₹4.85 Cr", "₹32,000", "8.40% p.a.", "On Request")
     • "short_description": 1-2 sentence highlight (<= 150 chars) for WhatsApp
     • "description": full overview
     • "attrs": dict of vertical specs (for real_estate: city, location, configuration, carpet_area, possession, rera_id, amenities; for travel: destination, duration, itinerary, inclusions; for banking: interest_rate, eligibility, tenure).

2. "faqs":
   - Explicit or implied Frequently Asked Questions, policies, common buyer inquiries, rules, procedures, or eligibility criteria.
   - Format: array of {{"question": "Clear question", "answer": "Comprehensive, factual answer"}}.

3. "kb_chunks":
   - Narrative background information, company overview, mission/vision, architectural technologies, safety standards, corporate policies, terms & conditions.
   - Format: array of {{"title": "Section title", "content": "Full narrative text"}}.

4. "menu_suggestions":
   - Primary high-level service pillars suitable for WhatsApp quick-reply buttons (strictly <= 20 chars).
   - Format: array of {{"title": "Button Title (<=20 chars)", "category": "Category name"}}.

5. "business_info":
   - Any detected corporate contact details, developer license, RERA ID, GST number, office address, customer support phone, email, or operating hours.
   - Format: {{"phone": "", "email": "", "address": "", "rera_id": "", "gstin": "", "hours": ""}}.

CRITICAL INSTRUCTIONS:
- If a category is not present on this page, return an empty array [] or empty object {{}}.
- Do not invent data; extract only what is stated or strongly implied by the page.
- Return ONLY valid JSON conforming to the schema. No markdown conversational text.

Expected JSON format:
{{
  "products": [...],
  "faqs": [...],
  "kb_chunks": [...],
  "menu_suggestions": [...],
  "business_info": {{...}}
}}"""

    user_prompt = f"""Page Text:
--------------------------------
{page_text[:7000]}
--------------------------------
Default Category Hint: {default_category or 'General'}

Analyze, classify, and bifurcate all content on this page into the 5 categories in valid JSON:"""

    return system_prompt, user_prompt


async def call_bifurcation_llm(system_prompt: str, user_prompt: str) -> Dict[str, Any]:
    import httpx
    try:
        from routing import config
        api_url = getattr(config, "GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
        api_key = getattr(config, "GROQ_API_KEY", "")
        model = getattr(config, "GROQ_MODEL", "openai/gpt-oss-20b")
    except Exception:
        api_url = os.environ.get("GROQ_API_URL", "https://api.groq.com/openai/v1/chat/completions")
        api_key = os.environ.get("GROQ_API_KEY", "")
        model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

    if not api_key:
        logger.warning("No LLM API key available for bifurcation.")
        return {}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }

    raw_text = ""
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(api_url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            raw_text = data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning(f"Bifurcation JSON mode failed: {e}. Retrying standard...")
        try:
            payload.pop("response_format", None)
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(api_url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                raw_text = data["choices"][0]["message"]["content"]
        except Exception as retry_err:
            logger.error(f"Bifurcation LLM failed: {retry_err}")
            return {}

    if not raw_text:
        return {}

    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception as parse_err:
        logger.error(f"Failed to parse bifurcation JSON: {parse_err}. Raw text:\n{raw_text[:400]}")

    return {}


# ── Database Storage Routines for the 5 Buckets ─────────────────────────────

def _save_faq_pairs(faqs: List[Dict[str, str]], tenant_id: str, source_file: str, page_number: int = 1) -> int:
    """Save extracted Q&A pairs into faq_dataset."""
    if not faqs:
        return 0
    t_num = None
    try:
        from shared.tenancy import store
        rec = store.get_tenant(tenant_id)
        if rec and rec.get("id"):
            t_num = rec["id"]
    except Exception:
        pass
    if t_num is None:
        t_num = int(tenant_id) if str(tenant_id).isdigit() else 1

    saved = 0
    with db.get_db_context() as conn:
        for f in faqs:
            q = (f.get("question") or "").strip()
            a = (f.get("answer") or "").strip()
            if not q or not a:
                continue
            content = f"Q: {q}\nA: {a}"
            conn.execute(
                """INSERT INTO faq_dataset (source_file, content_type, content, page_number, module, tenant_id)
                   VALUES (?, 'qa', ?, ?, 'faq', ?)""",
                (source_file, content, page_number, t_num),
            )
            saved += 1
    return saved


def _save_kb_chunks(kb_chunks: List[Dict[str, str]], tenant_id: str, source_file: str) -> int:
    """Save narrative reference chunks into knowledge_base."""
    if not kb_chunks:
        return 0
    t_num = None
    try:
        from shared.tenancy import store
        rec = store.get_tenant(tenant_id)
        if rec and rec.get("id"):
            t_num = rec["id"]
    except Exception:
        pass
    if t_num is None:
        t_num = int(tenant_id) if str(tenant_id).isdigit() else 1

    saved = 0
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.get_db_context() as conn:
        for c in kb_chunks:
            title = (c.get("title") or source_file).strip()
            content = (c.get("content") or "").strip()
            if not content:
                continue
            conn.execute(
                """INSERT INTO knowledge_base (title, category, content, tags, source, chunks_json, created_at, tenant_id)
                   VALUES (?, 'reference', ?, '[]', ?, ?, ?, ?)""",
                (title, content, source_file, json.dumps([content]), now_str, t_num),
            )
            saved += 1
    return saved


# ── Main Entry Point: Bifurcate and Ingest ───────────────────────────────────

async def bifurcate_and_ingest_pdf(
    pdf_bytes: bytes,
    filename: str,
    tenant_id: str,
    default_category: str = "",
    actor: dict = None,
    pre_extracted_images: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Universal pipeline: extracts, classifies, and routes all content in the PDF
    into Products, FAQs, Knowledge Base, Menu Suggestions, and Business Profile.
    """
    vertical = _get_tenant_vertical(tenant_id)
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename)
    doc_id = uuid.uuid4().hex[:8]
    brochure_filename = f"{tenant_id}_{doc_id}_{safe_name}"
    brochure_path = BROCHURES_DIR / brochure_filename

    with open(brochure_path, "wb") as f:
        f.write(pdf_bytes)

    brochure_url = f"/uploaded_files/brochures/{brochure_filename}"

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"Failed to open PDF with PyMuPDF: {e}")
        return {
            "success": False,
            "error": f"Failed to open PDF: {e}",
            "filename": filename,
        }

    total_pages = len(doc)
    all_staged_products = []
    all_faqs = []
    all_kb_chunks = []
    all_menu_suggestions = []
    merged_business_info = {}
    seen_products = set()
    seen_faqs = set()

    for page_idx in range(total_pages):
        page = doc[page_idx]
        page_num = page_idx + 1
        text = page.get_text("text").strip()
        if len(text) < 30:
            continue

        images = _extract_page_assets(doc, page, page_num, tenant_id)
        sys_prompt, usr_prompt = build_bifurcation_prompt(vertical, text, default_category)
        parsed = await call_bifurcation_llm(sys_prompt, usr_prompt)

        # 1. Process Products
        prods = parsed.get("products") or []
        for idx, prod in enumerate(prods):
            name = (prod.get("name") or "").strip()
            if not name or len(name) < 2 or name.lower() in seen_products:
                continue
            seen_products.add(name.lower())

            category = (prod.get("category") or default_category or "General").strip()
            price = str(prod.get("price") or "").strip()
            short_desc = (prod.get("short_description") or "").strip()
            desc = (prod.get("description") or short_desc).strip()
            attrs = prod.get("attrs") or {}
            attrs["brochure_url"] = brochure_url

            media_url = images[min(idx, len(images) - 1)]["url"] if images else brochure_url
            media_type = "pdf" if media_url.endswith(".pdf") else "image"
            slug = f"{_slugify(name)}_{uuid.uuid4().hex[:6]}"

            try:
                prod_id = db.save_product(
                    name=name,
                    slug=slug,
                    category=category,
                    description=desc,
                    short_description=short_desc,
                    price=price,
                    media_url=media_url,
                    media_type=media_type,
                    attrs_json=attrs,
                    tenant_id=tenant_id,
                    is_active=0,  # Staging / Draft
                    actor=actor,
                )
                all_staged_products.append({
                    "id": prod_id,
                    "name": name,
                    "slug": slug,
                    "category": category,
                    "price": price,
                    "short_description": short_desc,
                    "media_url": media_url,
                    "brochure_url": brochure_url,
                    "attrs": attrs,
                    "page_number": page_num,
                    "is_active": 0,
                })
            except Exception as e:
                logger.error(f"Could not stage product '{name}': {e}")

        # 2. Process FAQs
        faqs = parsed.get("faqs") or []
        page_faqs = []
        for f in faqs:
            q = (f.get("question") or "").strip()
            a = (f.get("answer") or "").strip()
            if q and a and q.lower() not in seen_faqs:
                seen_faqs.add(q.lower())
                page_faqs.append({"question": q, "answer": a})
                all_faqs.append({"question": q, "answer": a, "page_number": page_num})
        _save_faq_pairs(page_faqs, tenant_id, filename, page_number=page_num)

        # 3. Process KB Chunks
        kb = parsed.get("kb_chunks") or []
        page_kb = []
        for k in kb:
            title = (k.get("title") or f"{filename} - Page {page_num}").strip()
            content = (k.get("content") or "").strip()
            if content and len(content) > 40:
                page_kb.append({"title": title, "content": content})
                all_kb_chunks.append({"title": title, "content": content[:150] + "...", "page_number": page_num})
        _save_kb_chunks(page_kb, tenant_id, filename)

        # 4. Process Menu Suggestions
        menu_items = parsed.get("menu_suggestions") or []
        for m in menu_items:
            m_title = (m.get("title") or "").strip()[:20]
            if m_title and not any(s["title"].lower() == m_title.lower() for s in all_menu_suggestions):
                all_menu_suggestions.append({
                    "title": m_title,
                    "category": m.get("category", m_title),
                })

        # 5. Process Business Info
        b_info = parsed.get("business_info") or {}
        if isinstance(b_info, dict):
            for k, v in b_info.items():
                if v and str(v).strip() and not merged_business_info.get(k):
                    merged_business_info[k] = str(v).strip()

    doc.close()

    # Trigger background index rebuild if new FAQs were added
    if all_faqs:
        try:
            from faq.service import faq_index
            asyncio.create_task(asyncio.to_thread(faq_index.build, force=True))
            logger.info("Triggered background FAQ index rebuild for newly ingested FAQs.")
        except Exception as e:
            logger.debug("Could not trigger FAQ index rebuild: %s", e)

    return {
        "success": True,
        "filename": filename,
        "brochure_url": brochure_url,
        "total_pages": total_pages,
        "summary": {
            "products_staged": len(all_staged_products),
            "faqs_ingested": len(all_faqs),
            "kb_chunks_ingested": len(all_kb_chunks),
            "menu_suggestions_count": len(all_menu_suggestions),
            "business_info_detected": merged_business_info,
        },
        "staged_products": all_staged_products,
        "faqs": all_faqs,
        "kb_chunks": all_kb_chunks,
        "menu_suggestions": all_menu_suggestions,
        "business_info": merged_business_info,
    }
