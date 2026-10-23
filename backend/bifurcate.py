"""bifurcate.py
------------
LLM-driven bifurcation: splits extracted chunks into two tenant-scoped stores
using Ollama (qwen3:8b). No hardcoded industry rule sets.

  KB  -> factual/business content (products/services/prices/offers/features/contacts/brand)
  FAQ -> questions/answers/policies/terms/privacy/how-to/process/grievance/support

Uses the same DB schema as before: tenant_kb / tenant_faq in the app DB.
"""

import os
import re
import json
import sqlite3
import hashlib
import logging
from typing import List, Dict, Any, Optional, Tuple

import requests

logger = logging.getLogger("bifurcate")

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

try:
    from routing.config import (
        DB_PATH as _APP_DB_PATH,
        OLLAMA_BASE_URL as _APP_OLLAMA_BASE_URL,
        OLLAMA_MODEL as _APP_OLLAMA_MODEL,
    )
except Exception:
    _APP_DB_PATH = os.path.join(PROJECT_ROOT, "faq.db")
    _APP_OLLAMA_BASE_URL = None
    _APP_OLLAMA_MODEL = None

OLLAMA_URL = (
    os.environ.get("OLLAMA_URL")
    or os.environ.get("OLLAMA_BASE_URL")
    or _APP_OLLAMA_BASE_URL
    or "http://localhost:11434"
).rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL") or _APP_OLLAMA_MODEL or "qwen3:8b"
LLM_BATCH_SIZE = int(os.environ.get("LLM_BATCH_SIZE", 12))
LLM_TIMEOUT = int(os.environ.get("LLM_TIMEOUT", 300))
SNIPPET_CHARS = 900

DB_PATH = os.environ.get("BIFURCATE_DB") or _APP_DB_PATH

KB_CATEGORIES = [
    "brand_story", "products_services", "prices", "offers",
    "features", "contact_locations", "other_kb",
]
FAQ_CATEGORIES = [
    "faq", "policy", "terms_conditions", "privacy",
    "process_howto", "support_grievance", "other_faq",
]


def resolve_tenant_industry(tenant_id: Optional[str]) -> str:
    """Get tenant vertical for context only (LLM decides classification)."""
    if tenant_id:
        try:
            from shared.tenancy.loader import get_tenant_profile
            profile = get_tenant_profile(tenant_id)
            if profile and profile.vertical:
                return str(profile.vertical)
        except Exception:
            pass
        try:
            from shared.tenancy import store
            record = store.get_tenant(tenant_id)
            if record and record.get("vertical"):
                return str(record["vertical"])
        except Exception:
            pass
    return "generic"


# ----------------------------------------------------------------------
# LLM classifier (no hardcoded rules)
# ----------------------------------------------------------------------
_SYSTEM_PROMPT = """You are a strict document classifier for a multi-tenant chatbot knowledge system.
Tenant context (informational only): {tenant_context}

Classify EACH numbered chunk into exactly one of:
- "kb"  = Knowledge Base: factual/business info meant to be browsed (company/brand, products/services/packages, pricing/rates/fees, offers/discounts, features/benefits, locations/contacts, specs/tables with product data).
- "faq" = FAQ: questions/answers, policies, terms & conditions, privacy, cancellation/refund/exchange, grievance/complaint, how-to/process/steps, support instructions, legal/administrative rules.

Categories:
- if label "kb": choose one of {kb_cats}
- if label "faq": choose one of {faq_cats}

Rules:
- Let the content decide. Do not assume a fixed industry mapping.
- If a chunk contains Q/A pairs or explicit questions ("how do I...", "can I...") lean FAQ unless it's clearly a product spec.
- If it's a price list/table of rates/specs lean KB.
- If both exist, pick the DOMINANT purpose.
- Return ONLY valid JSON with shape: {{"results":[{{"id": <number>, "label": "kb|faq", "category": "<category>"}}]}}
/no_think"""


def _build_user_prompt(batch: List[Tuple[int, str]]) -> str:
    parts = []
    for idx, text in batch:
        snippet = re.sub(r"\s+", " ", text).strip()[:SNIPPET_CHARS]
        parts.append(f"[{idx}] {snippet}")
    return "Classify these chunks:\n\n" + "\n\n".join(parts)


def _extract_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, flags=re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


def llm_classify_batch(batch: List[Tuple[int, str]], tenant_context: str = "") -> Dict[int, Tuple[str, str]]:
    """batch = [(global_index, text)]. Returns {global_index: (label, category)}."""
    system = _SYSTEM_PROMPT.format(
        tenant_context=tenant_context or "unknown",
        kb_cats=", ".join(KB_CATEGORIES),
        faq_cats=", ".join(FAQ_CATEGORIES),
    )
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": 0, "num_ctx": 8192},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": _build_user_prompt(batch)},
        ],
    }
    resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=LLM_TIMEOUT)
    resp.raise_for_status()
    content = resp.json().get("message", {}).get("content", "")
    data = _extract_json(content)
    if not data:
        raise ValueError(f"Could not parse JSON from model output: {content[:200]!r}")

    out: Dict[int, Tuple[str, str]] = {}
    valid_ids = {i for i, _ in batch}
    for item in data.get("results", []):
        try:
            idx = int(item["id"])
        except Exception:
            continue
        if idx not in valid_ids:
            continue
        label = str(item.get("label", "")).lower().strip()
        cat = str(item.get("category", "")).lower().strip()
        if label not in ("kb", "faq"):
            continue
        allowed = KB_CATEGORIES if label == "kb" else FAQ_CATEGORIES
        if cat not in allowed:
            cat = "other_kb" if label == "kb" else "other_faq"
        out[idx] = (label, cat)
    return out


def ollama_alive() -> bool:
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ----------------------------------------------------------------------
# Main bifurcation (LLM-only)
# ----------------------------------------------------------------------
def bifurcate_chunks(
    chunks: List[Dict[str, Any]],
    industry: str = "generic",
    tenant_id: Optional[str] = None,
    use_llm: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Classify all chunks with Ollama. Falls back to a single-pass if needed."""
    if not chunks:
        return {"kb": [], "faq": []}

    tenant_context = industry
    if tenant_id and industry in ("", "generic", None):
        tenant_context = resolve_tenant_industry(tenant_id)
    elif industry:
        tenant_context = industry

    labelled: List[Optional[Dict[str, Any]]] = [None] * len(chunks)

    if not use_llm or not ollama_alive():
        if use_llm:
            logger.warning("Ollama not reachable at %s - attempting direct call anyway.", OLLAMA_URL)

    # Classify all chunks via LLM in batches
    all_indices = [i for i, ch in enumerate(chunks) if (ch.get("content") or "").strip()]
    for start in range(0, len(all_indices), LLM_BATCH_SIZE):
        idxs = all_indices[start:start + LLM_BATCH_SIZE]
        batch = [(i, chunks[i]["content"]) for i in idxs]
        try:
            res = llm_classify_batch(batch, tenant_context)
        except Exception as e:
            logger.warning("LLM batch failed (%s). Retrying one-by-one.", e)
            res = {}
            for single in batch:
                try:
                    res.update(llm_classify_batch([single], tenant_context))
                except Exception as e2:
                    logger.warning("LLM single failed for chunk %s: %s", single[0], e2)
        for i in idxs:
            if i in res:
                label, cat = res[i]
                labelled[i] = dict(chunks[i], label=label, category=cat, confidence=95, method="llm")
            else:
                # No keyword heuristics: keep the chunk but flag it for review.
                labelled[i] = dict(
                    chunks[i], label="kb", category="other_kb", confidence=0, method="unclassified"
                )

    kb, faq = [], []
    for item in labelled:
        if not item:
            continue
        (faq if item["label"] == "faq" else kb).append(item)

    logger.info("LLM-bifurcated %d chunks -> KB: %d | FAQ: %d (tenant_context=%s)",
                len(chunks), len(kb), len(faq), tenant_context)
    return {"kb": kb, "faq": faq}


# ----------------------------------------------------------------------
# Storage (SQLite)
# ----------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenant_kb (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     TEXT NOT NULL,
    industry      TEXT,
    source_file   TEXT,
    category      TEXT,
    content_type  TEXT,
    page_number   INTEGER,
    content       TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    confidence    INTEGER,
    method        TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_kb_tenant  ON tenant_kb(tenant_id, category);

CREATE TABLE IF NOT EXISTS tenant_faq (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id     TEXT NOT NULL,
    industry      TEXT,
    source_file   TEXT,
    category      TEXT,
    content_type  TEXT,
    page_number   INTEGER,
    content       TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    confidence    INTEGER,
    method        TEXT,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tenant_id, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_faq_tenant ON tenant_faq(tenant_id, category);
"""


def init_bifurcation_tables(db_path: str = DB_PATH) -> None:
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.executescript(_SCHEMA)


def _hash(text: str) -> str:
    return hashlib.sha256(re.sub(r"\s+", " ", text).strip().lower().encode("utf-8")).hexdigest()


def save_bifurcated(
    tenant_id: str,
    industry: str,
    result: Dict[str, List[Dict[str, Any]]],
    replace_source: bool = True,
    db_path: str = DB_PATH,
) -> Dict[str, int]:
    init_bifurcation_tables(db_path)
    counts = {"kb": 0, "faq": 0}
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        for store, table in (("kb", "tenant_kb"), ("faq", "tenant_faq")):
            rows = result.get(store, [])
            if replace_source:
                for src in {r["source_file"] for r in rows}:
                    conn.execute(f"DELETE FROM {table} WHERE tenant_id=? AND source_file=?", (tenant_id, src))
            for r in rows:
                cur = conn.execute(
                    f"""INSERT OR IGNORE INTO {table}
                        (tenant_id, industry, source_file, category, content_type, page_number,
                         content, content_hash, confidence, method)
                        VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (tenant_id, industry or "generic", r.get("source_file"), r.get("category"),
                     r.get("content_type"), r.get("page_number"), r["content"], _hash(r["content"]),
                     r.get("confidence"), r.get("method")),
                )
                counts[store] += cur.rowcount
        conn.commit()
    return counts


# ----------------------------------------------------------------------
# Pipelines
# ----------------------------------------------------------------------
def process_and_bifurcate(filepath: str, tenant_id: str, industry: str = "", use_llm: bool = True,
                          db_path: str = DB_PATH) -> Dict[str, Any]:
    try:
        import extract
    except ImportError:
        from backend import extract

    filename = os.path.basename(filepath)
    results = extract.process_file(filepath)
    if not results:
        return {"success": False, "file": filename, "error": "Extraction returned no results."}

    chunks = extract.results_to_chunks(results)
    if not chunks:
        return {"success": False, "file": filename, "error": "No text could be extracted from the file."}

    split = bifurcate_chunks(chunks, industry=industry or "", tenant_id=tenant_id, use_llm=use_llm)
    saved = save_bifurcated(tenant_id, industry or resolve_tenant_industry(tenant_id), split, db_path=db_path)

    return {
        "success": True,
        "file": filename,
        "tenant_id": tenant_id,
        "industry": industry or resolve_tenant_industry(tenant_id),
        "total_chunks": len(chunks),
        "kb_chunks": len(split["kb"]),
        "faq_chunks": len(split["faq"]),
        "saved": saved,
        "llm_used": sum(1 for c in split["kb"] + split["faq"] if c["method"] == "llm"),
    }


def bifurcate_and_save_chunks(
    chunks: List[Dict[str, Any]],
    tenant_id: str,
    industry: Optional[str] = None,
    use_llm: bool = True,
    db_path: str = DB_PATH,
) -> Dict[str, Any]:
    ind = industry or resolve_tenant_industry(tenant_id)
    split = bifurcate_chunks(chunks, industry=ind, tenant_id=tenant_id, use_llm=use_llm)
    saved = save_bifurcated(tenant_id, ind, split, db_path=db_path)
    return {
        "industry": ind,
        "kb_chunks": len(split["kb"]),
        "faq_chunks": len(split["faq"]),
        "saved": saved,
        "llm_used": sum(1 for c in split["kb"] + split["faq"] if c["method"] == "llm"),
    }


def fetch_store(tenant_id: str, store: str, category: Optional[str] = None,
                db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    init_bifurcation_tables(db_path)
    table = "tenant_kb" if store == "kb" else "tenant_faq"
    sql = f"SELECT * FROM {table} WHERE tenant_id=?"
    params: List[Any] = [tenant_id]
    if category:
        sql += " AND category=?"
        params.append(category)
    with sqlite3.connect(db_path, timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if len(sys.argv) < 3:
        print("Usage: python bifurcate.py <file> <tenant_id> [industry]")
        sys.exit(1)
    print(json.dumps(process_and_bifurcate(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else ""), indent=2))
