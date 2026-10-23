"""Automated PDF-to-Products extraction engine with vertical schema awareness,
image cropping, and draft staging.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image

import database as db

logger = logging.getLogger("pdf_product_extractor")

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADED_DIR = BASE_DIR / "uploaded_files"
BROCHURES_DIR = UPLOADED_DIR / "brochures"
PRODUCT_IMAGES_DIR = UPLOADED_DIR / "product_images"

os.makedirs(BROCHURES_DIR, exist_ok=True)
os.makedirs(PRODUCT_IMAGES_DIR, exist_ok=True)

# Minimum pixel dimensions to filter out tiny icons/dividers
MIN_IMG_WIDTH = 120
MIN_IMG_HEIGHT = 120


# ── Vertical Schema Definitions ─────────────────────────────────────────────

VERTICAL_SCHEMAS = {
    "real_estate": {
        "description": "Real Estate Properties (Apartments, Villas, Commercial Offices, Plots)",
        "fields": {
            "name": "Project or Property name (e.g., 'DLF The Arbour 4 BHK')",
            "category": "Category (e.g., 'Luxury Apartments', 'Commercial Offices', 'Villas', 'Penthouses')",
            "price": "Price or Starting Rate (e.g., '₹8.5 Cr', '₹45 Lakh', 'Price on Request')",
            "short_description": "1-2 sentence highlight for WhatsApp preview (<= 150 chars)",
            "description": "Full overview including developer, location, and key features",
            "attrs": {
                "city": "City name (e.g. Gurugram, Mumbai, Bangalore, Ahmedabad)",
                "location": "Locality or sector (e.g. Golf Course Extension Road, Sector 63)",
                "configuration": "BHK or Type (e.g. 2 BHK, 3 BHK + Servant, 4 BHK Luxury, Commercial Suite)",
                "carpet_area": "Carpet area or Super built-up area (e.g. 2,150 sq.ft.)",
                "possession": "Possession timeline or status (e.g. Ready to Move, Dec 2026)",
                "rera_id": "RERA registration number if mentioned (or empty)",
                "amenities": "Key amenities separated by commas (e.g. Clubhouse, Swimming Pool, 24/7 Security)",
            },
        },
    },
    "tours_travel": {
        "description": "Tour Packages & Destinations (Domestic & International Tours, Itineraries)",
        "fields": {
            "name": "Package name (e.g., 'Royal Rajasthan Heritage 5N/6D')",
            "category": "Category (e.g., 'Domestic Tours', 'International Holidays', 'Honeymoon Packages')",
            "price": "Price per person / starting rate (e.g., '₹32,000 per person')",
            "short_description": "1-2 sentence summary with duration and highlights",
            "description": "Full package description and key tour attractions",
            "attrs": {
                "destination": "Main destination or circuit (e.g. Rajasthan, Kerala, Dubai, Bali)",
                "duration": "Duration (e.g. 5 Nights / 6 Days)",
                "itinerary": "Day-by-day itinerary summary (e.g. Day 1: Arrival, Day 2: Sightseeing...)",
                "inclusions": "Key inclusions (e.g. 4-Star Stay, Breakfast & Dinner, AC Cab, Sightseeing)",
                "exclusions": "Key exclusions (e.g. Airfare, Personal Expenses, Visa fees)",
                "hotel_rating": "Accommodation type (e.g. 3-Star / 4-Star / Luxury Heritage)",
            },
        },
    },
    "banking": {
        "description": "Banking & Lending Products (Accounts, Credit Cards, Loans, Deposits)",
        "fields": {
            "name": "Product name (e.g., 'Meridian Premier Home Loan')",
            "category": "Category (e.g., 'Home Loans', 'Credit Cards', 'Savings Accounts', 'Fixed Deposits')",
            "price": "Interest rate or annual fee (e.g., '8.40% p.a.', 'Nil / ₹499 annual fee')",
            "short_description": "Key interest rate and primary benefit",
            "description": "Full terms, features, and bank guidelines",
            "attrs": {
                "interest_rate": "Interest rate or charges (e.g. 8.40% - 9.15% p.a.)",
                "eligibility": "Eligibility criteria (e.g. Salaried min income ₹50k/mo, Age 21-60)",
                "min_balance": "Minimum average balance or down payment",
                "tenure": "Maximum tenure (e.g. Up to 30 years)",
                "features": "Key benefits (e.g. Zero prepayment penalty, instant pre-approval)",
            },
        },
    },
    "finance": {
        "description": "Finance, Tax & Corporate Advisory Services",
        "fields": {
            "name": "Service offering name (e.g., 'Corporate Tax & GST Retainer')",
            "category": "Category (e.g., 'Tax & GST', 'Audit & Assurance', 'Wealth Planning')",
            "price": "Fee structure or starting fee (e.g., '₹15,000 / month', 'Custom Quote')",
            "short_description": "Key deliverables and service scope",
            "description": "Full advisory scope and compliance coverage",
            "attrs": {
                "service_type": "Advisory type (e.g. Monthly Retainer, One-Time Audit)",
                "deliverables": "Deliverables (e.g. Monthly GSTR-1 & 3B, Annual Return, Tax Planning)",
                "engagement_model": "Engagement term (e.g. Annual contract, Per assignment)",
            },
        },
    },
    "it_software": {
        "description": "IT & Software Services (Web, Mobile Apps, Cloud, AI Solutions)",
        "fields": {
            "name": "Service or solution name (e.g., 'Custom Mobile App Development')",
            "category": "Category (e.g., 'Mobile Apps', 'Web Development', 'AI & Machine Learning')",
            "price": "Starting project cost or hourly rate (e.g., 'Starting ₹2.5 Lakh', '₹1,500/hr')",
            "short_description": "Technology stack and core capability",
            "description": "Full scope, architecture, and engagement highlights",
            "attrs": {
                "tech_stack": "Technologies used (e.g. React Native, Flutter, Node.js, AWS)",
                "deliverables": "Deliverables (e.g. Source code, UI/UX designs, Store publishing)",
                "timeline": "Typical turnaround (e.g. 6 - 10 Weeks)",
            },
        },
    },
    "generic": {
        "description": "General Products & Offerings Catalog",
        "fields": {
            "name": "Product name",
            "category": "Product category",
            "price": "Price (e.g. '₹999')",
            "short_description": "Short highlight for WhatsApp preview",
            "description": "Comprehensive product details",
            "attrs": {
                "sku": "SKU or Item Code",
                "unit": "Unit (piece, box, kg, pack)",
                "specifications": "Key technical specifications or features",
            },
        },
    },
}


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


# ── Step 1: PDF Text & Image Stream Extraction ──────────────────────────────

def extract_pdf_assets(
    pdf_bytes: bytes, tenant_id: str, filename: str
) -> Tuple[str, List[Dict[str, Any]]]:
    """Save the brochure PDF and extract all pages with text and high-res images."""
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", filename)
    doc_id = uuid.uuid4().hex[:8]
    brochure_filename = f"{tenant_id}_{doc_id}_{safe_name}"
    brochure_path = BROCHURES_DIR / brochure_filename

    with open(brochure_path, "wb") as f:
        f.write(pdf_bytes)

    brochure_url = f"/uploaded_files/brochures/{brochure_filename}"
    pages_data = []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"Failed to open PDF with PyMuPDF: {e}")
        return brochure_url, []

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1
        text = page.get_text("text").strip()

        # Extract embedded raster images
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

                # Filter out tiny icon / divider artifacts
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
                except Exception as img_err:
                    logger.debug(f"Could not convert/save image: {img_err}")
        except Exception as e:
            logger.debug(f"Image extraction error on page {page_num}: {e}")

        pages_data.append({
            "page_number": page_num,
            "text": text,
            "images": page_images,
        })

    doc.close()
    return brochure_url, pages_data


# ── Step 2: LLM Structured Ingestion ─────────────────────────────────────────

def build_llm_prompt(vertical: str, page_text: str, default_category: str = "") -> Tuple[str, str]:
    schema_info = VERTICAL_SCHEMAS.get(vertical, VERTICAL_SCHEMAS["generic"])
    fields_desc = json.dumps(schema_info["fields"], indent=2)

    system_prompt = f"""You are an expert catalog parser and data extractor for {schema_info['description']}.
Your task is to analyze the provided page text from a product/property/service brochure and extract all distinct offerings/products into structured JSON.

CRITICAL INSTRUCTIONS:
1. Extract ALL distinct products, properties, units, services, or packages mentioned on the page.
2. If multiple items (e.g. 2 BHK, 3 BHK, 4 BHK or different tour packages) are listed, output each as a separate item in the "products" array.
3. If no product or offering is found on this page (e.g. it's only a cover page, table of contents, disclaimer, or company profile), return `{{"products": []}}`.
4. Prices: Preserve exact currency symbols and text (e.g. '₹8.5 Cr', '₹35,000', 'Price on Request').
5. Short description: Maximum 150 characters, clear, highlighting key specs for a WhatsApp card.
6. The "attrs" dictionary must strictly contain the vertical-specific metadata.
7. Return ONLY valid JSON conforming to the schema below. No conversational text, no markdown wrappers outside the JSON.

Expected JSON Structure:
{{
  "products": [
    {fields_desc}
  ]
}}"""

    user_prompt = f"""Brochure Page Text:
--------------------------------
{page_text[:7000]}
--------------------------------
Default Category Hint (if not specified in text): {default_category or 'General'}

Extract all products/offerings from the above text in JSON format:"""

    return system_prompt, user_prompt


async def call_llm_json(system_prompt: str, user_prompt: str) -> List[Dict[str, Any]]:
    """Call the LLM with JSON fallback and parse the products list."""
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
        logger.warning("No LLM API key found for PDF extraction.")
        return []

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
        logger.warning(f"JSON mode request failed: {e}. Retrying without response_format...")
        try:
            payload.pop("response_format", None)
            async with httpx.AsyncClient(timeout=45.0) as client:
                resp = await client.post(api_url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                raw_text = data["choices"][0]["message"]["content"]
        except Exception as retry_err:
            logger.error(f"LLM extraction request failed completely: {retry_err}")
            return []

    if not raw_text:
        return []

    # Clean markdown code blocks
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"\s*```$", "", cleaned, flags=re.MULTILINE).strip()

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict) and "products" in parsed and isinstance(parsed["products"], list):
            return parsed["products"]
        elif isinstance(parsed, list):
            return parsed
        elif isinstance(parsed, dict):
            # Single product returned as dict
            for key in ("items", "offerings", "properties"):
                if key in parsed and isinstance(parsed[key], list):
                    return parsed[key]
            return [parsed]
    except Exception as parse_err:
        logger.error(f"Failed to parse LLM JSON response: {parse_err}. Raw text:\n{raw_text[:500]}")

    return []


# ── Step 3: End-to-End Orchestrator ──────────────────────────────────────────

async def process_pdf_catalog(
    pdf_bytes: bytes,
    filename: str,
    tenant_id: str,
    default_category: str = "",
    actor: dict = None,
) -> Dict[str, Any]:
    """Ingest a catalog PDF: extract text & images, call LLM, and insert into products staging."""
    vertical = _get_tenant_vertical(tenant_id)
    brochure_url, pages_data = extract_pdf_assets(pdf_bytes, tenant_id, filename)

    if not pages_data:
        return {
            "success": False,
            "error": "Failed to read pages or extract text from the PDF.",
            "extracted_count": 0,
            "staged_products": [],
        }

    staged_items = []
    seen_names = set()

    # Process page by page
    for page in pages_data:
        text = page.get("text", "")
        # Skip pages with virtually no text (less than 30 chars)
        if len(text) < 30:
            continue

        sys_prompt, usr_prompt = build_llm_prompt(vertical, text, default_category)
        extracted_prods = await call_llm_json(sys_prompt, usr_prompt)

        images = page.get("images", [])
        for idx, prod in enumerate(extracted_prods):
            name = (prod.get("name") or "").strip()
            if not name or len(name) < 2 or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())

            category = (prod.get("category") or default_category or "General").strip()
            price = str(prod.get("price") or "").strip()
            short_desc = (prod.get("short_description") or "").strip()
            desc = (prod.get("description") or short_desc).strip()
            attrs = prod.get("attrs") or {}
            if not isinstance(attrs, dict):
                attrs = {}

            # Link brochure
            attrs["brochure_url"] = brochure_url

            # Associate image: 1-to-1 or round-robin if multiple
            media_url = ""
            if images:
                img_pick = images[min(idx, len(images) - 1)]
                media_url = img_pick.get("url", "")
            else:
                # If no image was found, default to brochure PDF
                media_url = brochure_url

            media_type = "pdf" if media_url.endswith(".pdf") else "image"

            # Create unique slug
            base_slug = _slugify(name)
            slug = f"{base_slug}_{uuid.uuid4().hex[:6]}"

            # Insert into database with is_active = 0 (STAGING / DRAFT)
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
                    is_active=0,  # Draft staging!
                    actor=actor,
                )
                staged_items.append({
                    "id": prod_id,
                    "name": name,
                    "slug": slug,
                    "category": category,
                    "price": price,
                    "short_description": short_desc,
                    "media_url": media_url,
                    "media_type": media_type,
                    "brochure_url": brochure_url,
                    "attrs": attrs,
                    "is_active": 0,
                    "page_number": page.get("page_number"),
                })
            except Exception as ins_err:
                logger.error(f"Could not stage product '{name}': {ins_err}")

    logger.info(
        f"PDF_CATALOG_PROCESSED | tenant={tenant_id} | file={filename} | "
        f"pages={len(pages_data)} | staged={len(staged_items)}"
    )

    return {
        "success": True,
        "filename": filename,
        "brochure_url": brochure_url,
        "total_pages": len(pages_data),
        "extracted_count": len(staged_items),
        "staged_products": staged_items,
    }
