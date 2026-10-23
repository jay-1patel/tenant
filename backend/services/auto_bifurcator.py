"""Intelligent Document Auto-Bifurcation & Auto-Configuration Engine.

Accepts multi-format uploaded documents (PDF, DOCX, XLSX, CSV, TXT, MD), parses their
contents, semantically bifurcates the information into:
  1. Brand & Profile Data (Name, Bot persona, Tagline, Tone, Contact, Hours, Vertical)
  2. WhatsApp Interactive Navigation Menu (Buttons/Drawers <= 24 title / 72 desc chars)
  3. Conversational Intents & Flow Triggers (Keywords, Utterances, Action Mappings)
  4. Offerings & Catalog Data (Products, Services, Packages, Properties with Pricing)
  5. Knowledge Base & FAQ Documents (Markdown articles, Chunks, Vector RAG Embeddings)

Automatically configures and publishes all components into the tenant configuration,
database tables, client pack (clients/<tenant_id>/config.json), and FAISS vector index,
eliminating manual data entry and configuration work.
"""

import csv
import io
import json
import logging
import os
import re
import shutil
import string
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
from docx import Document
import openpyxl

from database import (
    get_db_context,
    list_products,
    record_admin_audit_event,
    save_admin_file,
    save_chunks,
    save_knowledge_base_chunks,
    save_product,
    update_product,
)
from shared.tenancy import cache as tenancy_cache
from shared.tenancy import loader as tenancy_loader
from shared.tenancy import schemas as tenancy_schemas
from shared.tenancy import store as tenancy_store

logger = logging.getLogger("auto_bifurcator")

# Target vertical options supported by tenancy schema
VALID_VERTICALS = set(tenancy_schemas.VERTICALS)

# Brochure modules recognized by brochure_service (destination for
# brochure/profile/menu/price-list documents)
BROCHURE_MODULES = {
    "catalogue",
    "new_arrival",
    "product_brochure",
    "service_brochure",
    "company_profile",
    "technical_brochure",
    "pricing",
    "customer_case_study",
    "industry_brochure",
    "general",
}

# Document types the LLM/heuristics may assign; brochure-ish types are
# auto-registered as sendable brochure PDFs for the tenant.
BROCHURE_DOC_TYPES = {
    "brochure": "catalogue",
    "company_profile": "company_profile",
    "menu": "pricing",
    "price_list": "pricing",
    "catalog": "catalogue",
    "technical_brochure": "technical_brochure",
    "case_study": "customer_case_study",
}

# Public file host used to expose brochure PDFs over WhatsApp
CATBOX_API_URL = os.environ.get("CATBOX_API_URL", "https://catbox.moe/user/api.php")

# ──────────────────────────────────────────────────────────────────────────
# OCR setup (scanned / image-only PDFs and image files)
# ──────────────────────────────────────────────────────────────────────────
try:
    import pytesseract
    from PIL import Image
except ImportError:  # pragma: no cover - OCR optional
    pytesseract = None
    Image = None

TESSERACT_CMD = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
if not TESSERACT_CMD:
    _default_windows_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_default_windows_path):
        TESSERACT_CMD = _default_windows_path

if TESSERACT_CMD and pytesseract:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD
    logger.info("OCR enabled | tesseract=%s", TESSERACT_CMD)
else:
    logger.warning(
        "OCR unavailable - scanned/image-only PDFs will yield little or no text. "
        "Set TESSERACT_CMD to the tesseract executable to enable OCR."
    )

IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp")
MAX_OCR_PAGES = 20


def _clean_text(text: str) -> str:
    """Normalize whitespace and strip non-printable characters."""
    if not text:
        return ""
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _slugify(text: str) -> str:
    """Produce clean lowercase slug."""
    text = (text or "").lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "item"


class AutoBifurcator:
    """Core auto-bifurcation and auto-configuration pipeline."""

    def __init__(self, tenant_id: str, actor: Optional[dict] = None):
        self.tenant_id = tenant_id.strip().lower()
        self.actor = actor or {
            "username": "auto_bifurcator",
            "role": "super_admin",
            "tenant_id": self.tenant_id,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Multi-Format Text & Table Extraction
    # ──────────────────────────────────────────────────────────────────────────

    def extract_file_content(self, filename: str, content: bytes) -> Dict[str, Any]:
        """Extract text and tables from PDF, DOCX, XLSX, CSV, TXT, MD."""
        ext = Path(filename).suffix.lower()
        extracted_text = ""
        tables_found: List[List[List[str]]] = []

        try:
            if ext == ".pdf":
                doc = fitz.open(stream=content, filetype="pdf")
                pages_text = []
                for pno in range(len(doc)):
                    page = doc[pno]
                    txt = page.get_text("text") or ""
                    if txt.strip():
                        pages_text.append(f"--- Page {pno + 1} ---\n{txt}")
                extracted_text = "\n\n".join(pages_text)

            elif ext in (".docx", ".doc"):
                doc_file = io.BytesIO(content)
                doc = Document(doc_file)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                # Extract tables
                table_texts = []
                for table in doc.tables:
                    t_rows = []
                    for row in table.rows:
                        row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                        t_rows.append(row_cells)
                    if t_rows:
                        tables_found.append(t_rows)
                        table_texts.append("\n".join([" | ".join(r) for r in t_rows]))
                extracted_text = "\n\n".join(paragraphs + table_texts)

            elif ext in (".xlsx", ".xls"):
                wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
                sheet_texts = []
                for sheetname in wb.sheetnames:
                    sheet = wb[sheetname]
                    rows = []
                    for row in sheet.iter_rows(values_only=True):
                        cells = [str(c).strip() if c is not None else "" for c in row]
                        if any(cells):
                            rows.append(" | ".join(cells))
                    if rows:
                        sheet_texts.append(f"=== Sheet: {sheetname} ===\n" + "\n".join(rows))
                extracted_text = "\n\n".join(sheet_texts)

            elif ext == ".csv":
                text_stream = io.StringIO(content.decode("utf-8", errors="ignore"))
                reader = csv.reader(text_stream)
                rows = [" | ".join(row) for row in reader if any(row)]
                extracted_text = "\n".join(rows)

            else:
                # Text or Markdown fallback
                try:
                    extracted_text = content.decode("utf-8")
                except UnicodeDecodeError:
                    extracted_text = content.decode("latin-1", errors="ignore")

        except Exception as exc:
            logger.error("Failed extracting %s: %s", filename, exc)
            extracted_text = f"[Text extraction error: {exc}]"

        extracted_text = _clean_text(extracted_text)
        return {
            "filename": filename,
            "ext": ext,
            "size": len(content),
            "char_count": len(extracted_text),
            "text": extracted_text,
            "has_tables": len(tables_found) > 0,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 2. LLM Semantic Bifurcation & Synthesis
    # ──────────────────────────────────────────────────────────────────────────

    def bifurcate_with_llm(self, doc_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send aggregated document contents to LLM to bifurcate into components."""
        # Concatenate text from all uploaded documents up to ~30,000 chars
        combined_chunks = []
        for doc in doc_summaries:
            txt = doc["text"]
            # Keep up to 12,000 chars per doc to give balanced coverage
            sample = txt[:12000]
            combined_chunks.append(f"================ DOCUMENT: {doc['filename']} ================\n{sample}")

        full_corpus = "\n\n".join(combined_chunks)
        if len(full_corpus) > 40000:
            full_corpus = full_corpus[:40000] + "\n...[Additional document content truncated]..."

        system_prompt = f"""You are an elite enterprise AI data architect and WhatsApp chatbot configurator.
Your mission is to read raw client documents (brochures, catalogs, FAQ sheets, company profiles) and automatically BIFURCATE and CONFIGURE the entire tenant chatbot system for tenant ID '{self.tenant_id}'.

You must output a strictly valid JSON object adhering to this structure:
{{
  "vertical": "real_estate" | "tours_travel" | "ecommerce" | "it_software" | "banking" | "finance" | "healthcare" | "generic",
  "brand": {{
    "name": "Official Company / Entity Name",
    "bot_name": "Friendly AI Assistant Name (e.g. Skyline Assistant, DLF Concierge)",
    "tagline": "1-2 sentence compelling value proposition",
    "website": "Valid URL (e.g. https://company.com or www.company.com)",
    "support_email": "Official support email address",
    "support_phone": "Official phone number with country code (e.g. +91 9876543210)",
    "signature": "Brand closing sign-off line"
  }},
  "business_hours": {{
    "timezone": "Asia/Kolkata",
    "open": "09:30",
    "close": "18:30",
    "open_days": [0, 1, 2, 3, 4, 5]
  }},
  "menu_items": [
    // 3 to 6 interactive WhatsApp menu options
    // CRITICAL META API CONSTRAINTS:
    // - "title" MUST BE <= 24 CHARACTERS (e.g. "Explore Properties", "Book Site Visit", "Pricing Plans", "Customer Support")
    // - "description" MUST BE <= 72 CHARACTERS
    // - "section" MUST BE <= 24 CHARACTERS (e.g. "Main Menu", "Explore", "Assistance")
    // - "action" should map to one of: "offerings", "get_quote", "book_callback", "raise_ticket", "faq"
    {{
      "id": "browse_offerings",
      "title": "Explore Offerings",
      "description": "Browse catalog, projects, or service offerings",
      "section": "Explore",
      "action": "offerings"
    }}
  ],
  "intents": [
    // 5 to 10 top customer conversational intents
    {{
      "name": "intent_slug_name",
      "description": "Brief description of customer purpose",
      "keywords": ["keyword1", "keyword2", "keyword3"],
      "examples": [
        "Example user question 1",
        "Example user question 2",
        "Example user question 3"
      ],
      "flow": "book_callback" | "get_quote" | "raise_ticket" | null
    }}
  ],
  "offerings": [
    // All individual products, services, properties, or packages extracted from documents
    {{
      "name": "Item or Package Name",
      "category": "Category or Segment",
      "price": "Price, starting rate, or range (e.g. '₹85 Lakhs' or '$499/mo' or 'Starting ₹25,000')",
      "short_description": "1 sentence punchy summary",
      "description": "Detailed features, inclusions, and specifications",
      "unit": "unit / package / license / flat / person",
      "attrs": {{
        "highlights": "Key bullet points",
        "specifications": "Extra details"
      }}
    }}
  ],
  "knowledge_articles": [
    // Structured knowledge base documents formatted in Clean Markdown
    {{
      "title": "Company Overview & Profile",
      "category": "Company",
      "markdown_content": "# Company Overview\\n\\nDetailed background, history, certifications..."
    }},
    {{
      "title": "Booking Process, Policies & FAQs",
      "category": "FAQ",
      "markdown_content": "# Frequently Asked Questions\\n\\n### Q: ...\\nA: ..."
    }}
  ]
}}

CRITICAL INSTRUCTIONS:
1. Extract ALL tangible products/services/properties you find into the 'offerings' array.
2. Ensure 'menu_items' titles are UNDER 24 CHARACTERS (strictly enforced by WhatsApp API).
3. If phone or email is missing in the text, provide a sensible default based on the tenant name (e.g. 'support@{self.tenant_id}.com' and '+91 9800000000').
4. Respond ONLY with the JSON object. Do not enclose in backticks or markdown if possible.
"""

        user_prompt = f"Please bifurcate and configure the chatbot system based on the following uploaded client collateral:\n\n{full_corpus}"

        response_json = self._call_llm_json(system_prompt, user_prompt)
        if not response_json:
            logger.warning("LLM bifurcation returned empty or invalid JSON; applying heuristic fallback")
            response_json = self._heuristic_bifurcation(doc_summaries)

        return response_json

    def _call_llm_json(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        """Call Groq (openai/gpt-oss-120b) or Mistral with JSON output."""
        # 1. Try Groq
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                import requests
                headers = {"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"}
                # Try gpt-oss-120b, then gpt-oss-20b
                for model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b"):
                    payload = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2,
                        "max_tokens": 4096,
                    }
                    resp = requests.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=45,
                    )
                    if resp.status_code == 200:
                        content = resp.json()["choices"][0]["message"]["content"]
                        parsed = self._extract_json_block(content)
                        if parsed:
                            logger.info("GROQ_BIFURCATION_SUCCESS | model=%s", model)
                            return parsed
            except Exception as e:
                logger.warning("Groq bifurcation failed: %s", e)

        # 2. Try Mistral
        mistral_key = os.getenv("MISTRAL_API_KEY")
        if mistral_key:
            try:
                import requests
                headers = {"Authorization": f"Bearer {mistral_key}", "Content-Type": "application/json"}
                payload = {
                    "model": os.getenv("MISTRAL_MODEL", "open-mistral-7b"),
                    "messages": [
                        {"role": "system", "content": system_prompt + "\nOUTPUT ONLY RAW JSON."},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                }
                resp = requests.post(
                    "https://api.mistral.ai/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=45,
                )
                if resp.status_code == 200:
                    content = resp.json()["choices"][0]["message"]["content"]
                    parsed = self._extract_json_block(content)
                    if parsed:
                        logger.info("MISTRAL_BIFURCATION_SUCCESS")
                        return parsed
            except Exception as e:
                logger.warning("Mistral bifurcation failed: %s", e)

        # 3. Try Local Ollama if available
        try:
            import requests
            ollama_url = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/chat")
            ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
            payload = {
                "model": ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "format": "json",
                "stream": False,
            }
            resp = requests.post(ollama_url, json=payload, timeout=60)
            if resp.status_code == 200:
                content = resp.json().get("message", {}).get("content", "")
                parsed = self._extract_json_block(content)
                if parsed:
                    logger.info("OLLAMA_BIFURCATION_SUCCESS")
                    return parsed
        except Exception as e:
            logger.debug("Ollama bifurcation check skipped or failed: %s", e)

        return None

    def _extract_json_block(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse JSON safely from LLM output."""
        if not text:
            return None
        text = text.strip()
        # Direct parse
        try:
            return json.loads(text)
        except Exception:
            pass

        # Regex search for ```json ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except Exception:
                pass

        # Search for first { to last }
        first = text.find("{")
        last = text.rfind("}")
        if first != -1 and last != -1 and last > first:
            try:
                return json.loads(text[first : last + 1])
            except Exception:
                pass

        return None

    def _heuristic_bifurcation(self, doc_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Deterministic rule-based fallback when LLM is unavailable."""
        combined_text = "\n\n".join(d["text"] for d in doc_summaries)
        display_name = self.tenant_id.replace("-", " ").replace("_", " ").title()

        # Detect email and phone
        emails = re.findall(r"[\w\.-]+@[\w\.-]+\.\w+", combined_text)
        phones = re.findall(r"\+?\d[\d -]{8,14}\d", combined_text)
        support_email = emails[0] if emails else f"support@{self.tenant_id}.com"
        support_phone = phones[0] if phones else "+91 9800000000"

        # Detect vertical keywords
        lower_txt = combined_text.lower()
        vertical = "generic"
        if any(w in lower_txt for w in ("property", "residence", "bhk", "villa", "floor", "real estate", "rera")):
            vertical = "real_estate"
        elif any(w in lower_txt for w in ("tour", "travel", "flight", "destination", "itinerary", "package")):
            vertical = "tours_travel"
        elif any(w in lower_txt for w in ("software", "cloud", "saas", "tech", "api", "developer")):
            vertical = "it_software"
        elif any(w in lower_txt for w in ("shop", "product", "sku", "delivery", "cart", "discount")):
            vertical = "ecommerce"
        elif any(w in lower_txt for w in ("loan", "interest", "finance", "tax", "wealth", "advisory")):
            vertical = "finance"
        elif any(w in lower_txt for w in ("clinic", "doctor", "health", "hospital", "patient")):
            vertical = "healthcare"

        # Extract headings or bullet items as offerings
        lines = [line.strip() for line in combined_text.splitlines() if line.strip()]
        offerings = []
        for i, line in enumerate(lines[:100]):
            if (line.startswith("#") or line.startswith("*") or line.startswith("-")) and len(line) < 60:
                clean_name = line.lstrip("#*- ").strip()
                if len(clean_name) > 3 and not clean_name.lower().startswith("page"):
                    offerings.append({
                        "name": clean_name[:60],
                        "category": "General",
                        "price": "Contact for pricing",
                        "short_description": clean_name,
                        "description": clean_name,
                        "unit": "unit",
                        "attrs": {},
                    })
            if len(offerings) >= 10:
                break

        return {
            "vertical": vertical,
            "brand": {
                "name": display_name,
                "bot_name": f"{display_name} Assistant",
                "tagline": f"Official WhatsApp Assistant for {display_name}",
                "website": f"https://www.{self.tenant_id}.com",
                "support_email": support_email,
                "support_phone": support_phone,
                "signature": f"{display_name} — At your service.",
            },
            "business_hours": {
                "timezone": "Asia/Kolkata",
                "open": "09:30",
                "close": "18:30",
                "open_days": [0, 1, 2, 3, 4, 5],
            },
            "menu_items": [
                {
                    "id": "browse_offerings",
                    "title": "Explore Offerings"[:24],
                    "description": "Browse our catalog and products"[:72],
                    "section": "Explore"[:24],
                    "action": "offerings",
                },
                {
                    "id": "book_callback",
                    "title": "Book Consultation"[:24],
                    "description": "Schedule a phone call with our specialists"[:72],
                    "section": "Actions"[:24],
                    "action": "book_callback",
                },
                {
                    "id": "get_quote",
                    "title": "Pricing & Quotes"[:24],
                    "description": "Request customized cost estimate"[:72],
                    "section": "Actions"[:24],
                    "action": "get_quote",
                },
                {
                    "id": "support",
                    "title": "Customer Support"[:24],
                    "description": "Ask questions or get help"[:72],
                    "section": "Support"[:24],
                    "action": "faq",
                },
            ],
            "intents": [
                {
                    "name": "explore_offerings",
                    "description": "Browse catalog",
                    "keywords": ["catalog", "offerings", "products", "services", "list"],
                    "examples": ["Show me your catalog", "What do you offer?", "Browse offerings"],
                    "flow": None,
                },
                {
                    "name": "pricing_inquiry",
                    "description": "Pricing questions",
                    "keywords": ["price", "cost", "rates", "quote", "charges"],
                    "examples": ["How much does it cost?", "Can I get a quote?", "What are the rates?"],
                    "flow": "get_quote",
                },
                {
                    "name": "book_appointment",
                    "description": "Book consultation or callback",
                    "keywords": ["callback", "consultation", "appointment", "schedule", "call me"],
                    "examples": ["Can you call me back?", "Schedule an appointment", "Book a call"],
                    "flow": "book_callback",
                },
            ],
            "offerings": offerings or [
                {
                    "name": f"{display_name} Standard Service",
                    "category": "General",
                    "price": "On Request",
                    "short_description": "Comprehensive customer offering",
                    "description": "Full specifications provided upon consultation.",
                    "unit": "package",
                    "attrs": {},
                }
            ],
            "knowledge_articles": [
                {
                    "title": "Company Profile & Information",
                    "category": "About",
                    "markdown_content": f"# {display_name}\\n\\n" + combined_text[:3000],
                }
            ],
        }

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Auto-Configuration & Application Engine
    # ──────────────────────────────────────────────────────────────────────────

    def apply_bifurcation(
        self,
        bifurcation: Dict[str, Any],
        raw_files: List[Dict[str, Any]],
        auto_publish: bool = True,
    ) -> Dict[str, Any]:
        """Apply extracted data across database tables, profile draft, and knowledge base."""
        tenant_id = self.tenant_id
        summary: Dict[str, Any] = {
            "tenant_id": tenant_id,
            "vertical": bifurcation.get("vertical", "generic"),
            "brand": {},
            "menu_buttons_count": 0,
            "intents_count": 0,
            "offerings_created": 0,
            "offerings_sample": [],
            "kb_chunks_indexed": 0,
            "version": 0,
            "status": "configured",
        }

        # 3.1 Sanitize vertical
        vertical = bifurcation.get("vertical", "generic")
        if vertical not in VALID_VERTICALS:
            vertical = "generic"

        # 3.2 Sanitize Brand
        brand_raw = bifurcation.get("brand", {})
        clean_brand = {
            "name": brand_raw.get("name") or tenant_id.replace("-", " ").title(),
            "bot_name": brand_raw.get("bot_name") or f"{tenant_id.title()} Assistant",
            "tagline": brand_raw.get("tagline") or "",
            "website": brand_raw.get("website") or f"https://www.{tenant_id}.com",
            "support_email": brand_raw.get("support_email") or f"support@{tenant_id}.com",
            "support_phone": brand_raw.get("support_phone") or "+91 9800000000",
            "signature": brand_raw.get("signature") or f"{tenant_id.title()} — At your service.",
        }
        # Validate format
        if clean_brand["website"] and not clean_brand["website"].startswith("http"):
            clean_brand["website"] = "https://" + clean_brand["website"].lstrip("/")
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", clean_brand["support_email"]):
            clean_brand["support_email"] = f"support@{tenant_id}.com"

        summary["brand"] = clean_brand

        # 3.3 Sanitize WhatsApp Menu Buttons (Meta Character Limitations)
        menu_items_raw = bifurcation.get("menu_items", [])
        menu_buttons = []
        for i, item in enumerate(menu_items_raw):
            b_id = _slugify(item.get("id") or item.get("title") or f"opt_{i}")
            # STRICT LIMITS: Title <= 24 chars, Desc <= 72 chars, Section <= 24 chars
            title = (item.get("title") or f"Option {i+1}").strip()[:24]
            desc = (item.get("description") or "").strip()[:72]
            sec = (item.get("section") or "Explore").strip()[:24]
            action = item.get("action") or "faq"

            button_dict = {
                "id": b_id,
                "title": title,
                "description": desc,
                "section": sec,
                "sort_order": i + 1,
                "enabled": True,
            }
            if action in ("offerings", "catalog"):
                button_dict["intent"] = "offerings"
            elif action in ("book_callback", "get_quote", "raise_ticket"):
                button_dict["flow"] = action
            else:
                button_dict["intent"] = b_id

            menu_buttons.append(button_dict)

        if not menu_buttons:
            # Fallback 3 default buttons
            menu_buttons = [
                {"id": "offerings", "title": "Explore Offerings"[:24], "description": "Browse catalog"[:72], "section": "Main"[:24], "intent": "offerings", "sort_order": 1, "enabled": True},
                {"id": "callback", "title": "Book Consultation"[:24], "description": "Request a callback"[:72], "section": "Main"[:24], "flow": "book_callback", "sort_order": 2, "enabled": True},
                {"id": "support", "title": "Customer Help"[:24], "description": "Ask questions"[:72], "section": "Main"[:24], "flow": "raise_ticket", "sort_order": 3, "enabled": True},
            ]
        summary["menu_buttons_count"] = len(menu_buttons)

        # 3.4 Sanitize Intents
        intents_raw = bifurcation.get("intents", [])
        clean_intents = []
        for intent in intents_raw:
            i_name = _slugify(intent.get("name") or "custom_intent")
            examples = [ex.strip() for ex in intent.get("examples", []) if ex.strip()][:5]
            keywords = [kw.strip() for kw in intent.get("keywords", []) if kw.strip()][:10]
            clean_intents.append({
                "name": i_name,
                "examples": examples,
                "keywords": keywords,
                "flow": intent.get("flow") or None,
                "enabled": True,
            })
        summary["intents_count"] = len(clean_intents)

        # 3.5 Update Tenant Profile Draft in Database
        draft = tenancy_store.get_draft(tenant_id) or {}
        draft["tenant_id"] = tenant_id
        draft["vertical"] = vertical
        draft["display_name"] = clean_brand["name"]
        draft["brand"] = clean_brand
        draft["menu"] = {
            "key": "kb_main",
            "header": clean_brand["name"],
            "body": "Welcome! How can we assist you today?",
            "footer": "Select an option or type your query directly",
            "button_text": "Select Option",
            "buttons": menu_buttons,
        }
        if clean_intents:
            # Merge existing and new intents
            existing_intents = {i["name"]: i for i in draft.get("intents", [])}
            for ci in clean_intents:
                existing_intents[ci["name"]] = ci
            draft["intents"] = list(existing_intents.values())

        if "business_hours" in bifurcation:
            draft["business_hours"] = bifurcation["business_hours"]

        # Ensure flows exist
        if "flows" not in draft or not draft["flows"]:
            draft["flows"] = [
                {"name": "book_callback", "success_message": f"Thank you! Your consultation request has been scheduled with {clean_brand['bot_name']}."},
                {"name": "get_quote", "success_message": f"Thank you! Our specialist will prepare a customized quote and follow up promptly."},
                {"name": "raise_ticket", "success_message": f"Your request has been logged. A support ticket has been created and an executive will assist you."}
            ]

        with get_db_context() as conn:
            tenancy_store.save_draft(tenant_id, draft, updated_by=self.actor.get("username", "admin"), conn=conn)

            # Auto-publish if requested
            if auto_publish:
                try:
                    version = tenancy_store.publish_version(
                        tenant_id, draft, published_by=self.actor.get("username", "admin"), conn=conn
                    )
                    summary["version"] = version
                    tenancy_cache.purge(tenant_id)
                    logger.info("AUTO_BIFURCATION_PUBLISHED | tenant=%s | v=%s", tenant_id, version)
                except Exception as pub_exc:
                    logger.warning("Could not auto-publish version directly: %s", pub_exc)

        # Sync client config file clients/<tenant_id>/config.json
        try:
            tenancy_loader.write_client_config_file(tenant_id, draft)
        except Exception as file_exc:
            logger.warning("Could not sync client config file: %s", file_exc)

        # 3.6 Insert Offerings into Catalog (products table)
        offerings_raw = bifurcation.get("offerings", [])
        existing_products = {p.get("name", "").lower(): p for p in list_products(tenant_id=tenant_id, active_only=False)}
        inserted_count = 0

        for off in offerings_raw:
            name = (off.get("name") or "").strip()
            if not name:
                continue
            cat = (off.get("category") or "General").strip()
            price = (str(off.get("price") or "")).strip() or None
            short_desc = (off.get("short_description") or name).strip()
            desc = (off.get("description") or short_desc).strip()
            attrs = off.get("attrs") or {}
            slug = _slugify(name)

            if name.lower() in existing_products:
                prod_id = existing_products[name.lower()]["id"]
                update_product(
                    prod_id,
                    tenant_id=tenant_id,
                    price=price,
                    description=desc,
                    short_description=short_desc,
                    category=cat,
                    attrs_json=attrs,
                )
            else:
                save_product(
                    name=name,
                    slug=slug,
                    category=cat,
                    price=price,
                    short_description=short_desc,
                    description=desc,
                    attrs_json=attrs,
                    tenant_id=tenant_id,
                    actor=self.actor,
                )
                inserted_count += 1
                if len(summary["offerings_sample"]) < 5:
                    summary["offerings_sample"].append(name)

        summary["offerings_created"] = inserted_count

        # 3.7 Write Knowledge Base Markdown Files & Build Vector Embeddings
        knowledge_dir = Path("clients") / tenant_id / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)

        articles = bifurcation.get("knowledge_articles", [])
        all_chunks_to_index: List[str] = []

        for idx, art in enumerate(articles):
            title = art.get("title", f"Knowledge Article {idx+1}")
            md_content = art.get("markdown_content", "")
            file_slug = f"{idx+1:02d}_{_slugify(title)}.md"
            target_path = knowledge_dir / file_slug
            try:
                target_path.write_text(md_content, encoding="utf-8")
            except Exception as e:
                logger.warning("Could not write knowledge file %s: %s", target_path, e)

            # Chunk markdown content
            sections = md_content.split("\n## ")
            for sec in sections:
                if sec.strip():
                    all_chunks_to_index.append(sec.strip())

        # Also chunk raw text from uploaded files
        for rf in raw_files:
            txt = rf.get("text", "")
            if txt:
                paragraphs = [p.strip() for p in txt.split("\n\n") if len(p.strip()) > 80]
                all_chunks_to_index.extend(paragraphs[:50])

        if all_chunks_to_index:
            try:
                # Format chunks as dicts for save_knowledge_base_chunks
                formatted_chunks = [
                    {"content": ch, "source_file": "auto_bifurcated_docs.md"}
                    for ch in all_chunks_to_index
                ]
                save_knowledge_base_chunks(
                    chunks=formatted_chunks,
                    source_file="auto_bifurcated_docs.md",
                    tenant_id=tenant_id,
                )
                # Rebuild FAISS & missing embeddings
                try:
                    from kb.services.rag import (
                        build_chunks_for_kb,
                        generate_missing_embeddings,
                        rebuild_faiss_index,
                    )
                    build_chunks_for_kb()
                    generate_missing_embeddings()
                    rebuild_faiss_index()
                    logger.info("VECTOR_RAG_INDEX_REBUILT | tenant=%s | chunks=%d", tenant_id, len(all_chunks_to_index))
                except Exception as rag_err:
                    logger.warning("RAG vector rebuild error: %s", rag_err)

                summary["kb_chunks_indexed"] = len(all_chunks_to_index)
            except Exception as chunk_err:
                logger.error("Failed storing knowledge base chunks: %s", chunk_err)

        # Audit Event
        try:
            with get_db_context() as conn:
                record_admin_audit_event(
                    conn,
                    action="tenant_auto_bifurcated",
                    actor=self.actor,
                    resource_type="tenant",
                    resource_id=tenant_id,
                    tenant_id=tenant_id,
                    details={
                        "vertical": vertical,
                        "brand": clean_brand["name"],
                        "offerings_count": inserted_count,
                        "menu_buttons_count": len(menu_buttons),
                        "intents_count": len(clean_intents),
                        "chunks_count": summary["kb_chunks_indexed"],
                    },
                )
        except Exception:
            pass

        return summary

    # ──────────────────────────────────────────────────────────────────────────
    # 4. High-Level Coordinator
    # ──────────────────────────────────────────────────────────────────────────

    def process_files(
        self,
        files_data: List[Dict[str, Any]],
        auto_publish: bool = True,
    ) -> Dict[str, Any]:
        """End-to-end extraction, bifurcation, and system configuration."""
        extracted_docs = []

        # Ensure upload directory exists
        upload_dir = os.path.join("backend", "uploaded_files", "kb")
        os.makedirs(upload_dir, exist_ok=True)

        for f in files_data:
            filename = f.get("filename") or "document.pdf"
            content = f.get("content") or b""
            if isinstance(content, str):
                import base64
                content = base64.b64decode(content)

            # Save uploaded raw file to disk
            filepath = os.path.join(upload_dir, filename)
            try:
                with open(filepath, "wb") as disk_file:
                    disk_file.write(content)
                ext = Path(filename).suffix.lstrip(".")
                save_admin_file(
                    filename,
                    ext,
                    "kb",
                    len(content),
                    file_path=filepath,
                    tenant_id=self.tenant_id,
                    actor=self.actor,
                )
            except Exception as write_err:
                logger.warning("Could not save admin file %s: %s", filename, write_err)

            # Extract content
            doc_data = self.extract_file_content(filename, content)
            extracted_docs.append(doc_data)

        # Run LLM semantic bifurcation
        bifurcation = self.bifurcate_with_llm(extracted_docs)

        # Apply bifurcation across all components
        result_summary = self.apply_bifurcation(
            bifurcation=bifurcation,
            raw_files=extracted_docs,
            auto_publish=auto_publish,
        )

        result_summary["files_processed"] = [d["filename"] for d in extracted_docs]
        return result_summary
