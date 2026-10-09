import os
import re
import json
import logging
import sqlite3
import threading
import subprocess
from functools import lru_cache

import httpx
import numpy as np
import requests
from sentence_transformers import SentenceTransformer, CrossEncoder
from rank_bm25 import BM25Okapi
import faiss

from routing.config import (
    DB_PATH, EMBEDDING_MODEL_PATH, BRAND_NAME, SUPPORT_EMAIL, SUPPORT_PHONE,
    BRAND_WEBSITE, OLLAMA_API_URL, OLLAMA_MODEL, OLLAMA_BASE_URL,
    BRAND_TAGLINE, SIGNATURE,
    GROQ_API_URL, GROQ_API_KEY, GROQ_MODEL,
    MISTRAL_API_URL, MISTRAL_API_KEY, MISTRAL_MODEL,
)
from database import save_embeddings
from services.response_formatters import WhatsAppFormatter, MessageType, smart_format

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("faq_bot")

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
EMBEDDING_MODEL     = EMBEDDING_MODEL_PATH
_local_ce_path      = os.path.join(os.path.dirname(__file__), "..", "models", "ettin-reranker-68m-v1")
CROSS_ENCODER_MODEL = _local_ce_path if os.path.exists(_local_ce_path) else "BAAI/bge-reranker-base"

_model_cfg_path = os.path.join(EMBEDDING_MODEL, "config.json")
if os.path.exists(_model_cfg_path):
    with open(_model_cfg_path) as _f:
        EMBEDDING_DIM = json.load(_f).get("hidden_size", 1024)
else:
    EMBEDDING_DIM = 1024

SIMILARITY_THRESHOLD        = 0.30
CE_SCORE_THRESHOLD          = 0.00
HIGH_CONFIDENCE_THRESHOLD   = 0.60
MEDIUM_CONFIDENCE_THRESHOLD = 0.25

SEMANTIC_CANDIDATE_K = 30
BM25_CANDIDATE_K     = 20
RERANK_TOP_K         = 20
RRF_K                = 60
RRF_WEIGHTS          = {"dense": 0.6, "sparse": 0.4}


def _resolve_tenant_id(tenant_id=None) -> str:
    """The tenant a search is scoped to. Falls back to the registered default
    tenant so legacy callers keep serving the pre-tenancy data instead of
    leaking chunks across tenants."""
    tid = str(tenant_id or "").strip()
    if tid:
        return tid
    try:
        from shared.tenancy.resolver import resolve_default_tenant
        return resolve_default_tenant()
    except Exception:
        return "default"


def _tenant_from_payload(payload: dict) -> str | None:
    """Best-effort tenant for an inbound query payload: explicit tenant_id
    first, then the user's conversation state, else None (the search then
    falls back to the default tenant)."""
    tid = str(payload.get("tenant_id") or "").strip()
    if tid:
        return tid
    wa_id = payload.get("wa_id") or payload.get("from") or payload.get("phone")
    if wa_id:
        try:
            from shared.tenancy.store import tenant_id_for_user
            tid = tenant_id_for_user(wa_id)
        except Exception:
            tid = None
        if tid:
            return tid
    return None


def _brand_context(tenant_id=None) -> dict:
    """The brand fields the FAQ prompts and closing signature speak with.

    Resolved from the tenant's effective profile (vertical defaults ->
    clients/<id>/config.json -> published DB version), so every tenant answers
    in its own voice and signs off with its own signature. The legacy env
    config (routing/.env) is only a fallback for deployments with no profile
    layer at all; when a profile exists, its values win, including an empty
    signature (a tenant that configured none gets none).
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path

        root = str(_Path(__file__).resolve().parents[2])
        if root not in _sys.path:
            _sys.path.insert(0, root)

        from shared.tenancy import loader

        profile = loader.get_tenant_profile(_resolve_tenant_id(tenant_id))
        brand = profile.brand
        return {
            "brand_name": brand.name,
            "brand_tagline": brand.tagline,
            "support_email": brand.support_email,
            "support_phone": brand.support_phone,
            "signature": brand.signature,
        }
    except Exception as exc:  # defensive: the bot must keep answering
        logger.debug("brand profile unavailable, using env config: %s", exc)
        return {
            "brand_name": BRAND_NAME or "",
            "brand_tagline": BRAND_TAGLINE or "",
            "support_email": SUPPORT_EMAIL or "",
            "support_phone": SUPPORT_PHONE or "",
            "signature": SIGNATURE or "",
        }


def _render_prompt(template: str, brand: dict) -> str:
    """Substitute the brand placeholders into a prompt template.

    Plain replacement instead of str.format so literal braces elsewhere in a
    template can never break rendering.
    """
    out = template
    for key, value in brand.items():
        out = out.replace("{" + key + "}", str(value))
    return out

# ─────────────────────────────────────────────
# Tokenizer
# ─────────────────────────────────────────────
_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did "
    "will would shall should may might can could of in to for on with "
    "at by from as into about between through during and but or nor "
    "not so yet both either neither each every all any few more most "
    "other some such no only own same than too very that this these "
    "those it its he she they them their what which who whom how when "
    "where why am does".split()
)


def simple_tokenize(text: str) -> list[str]:
    tokens = re.findall(r"\w+", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
embedding_model = SentenceTransformer(EMBEDDING_MODEL)
if hasattr(embedding_model, "get_sentence_embedding_dimension"):
    EMBEDDING_DIM = embedding_model.get_sentence_embedding_dimension()
elif hasattr(embedding_model, "get_embedding_dimension"):
    EMBEDDING_DIM = embedding_model.get_embedding_dimension()
cross_encoder   = CrossEncoder(CROSS_ENCODER_MODEL)


@lru_cache(maxsize=2048)
def _encode_query_cached(query: str) -> bytes:
    emb = embedding_model.encode([query], convert_to_numpy=True)
    emb = emb / (np.linalg.norm(emb, axis=1, keepdims=True) + 1e-10)
    return emb.astype(np.float32).tobytes()

# ─────────────────────────────────────────────
# Button registry + topic-relevance filter
# ─────────────────────────────────────────────
# Imported ONCE at module level so a missing/broken import fails LOUDLY at
# startup instead of being silently swallowed per-request.
#
# BUG THIS FIXES: the old code did, inside _validate_faq_dynamic_result():
#     try:
#         from routing.button_actions import BUTTON_REGISTRY, enforce_topic_actions
#     except Exception:
#         BUTTON_REGISTRY = {}
#         enforce_topic_actions = None
# `enforce_topic_actions` never existed in button_actions.py, so the
# ImportError was swallowed on every call — silently disabling BOTH the
# registry (every LLM-picked button was dropped) AND the topic filter
# (unrelated buttons were never filtered out).
try:
    from routing.button_actions import (
        BUTTON_REGISTRY,
        enforce_topic_actions,
        registry_prompt_text,
        suggest_actions,
    )
except Exception as exc:
    logger.warning(f"routing.button_actions import failed — dynamic buttons disabled: {exc}")
    BUTTON_REGISTRY = {}
    enforce_topic_actions = None

    def registry_prompt_text() -> str:
        return ""

    def suggest_actions(query: str, source_file: str = "") -> list[dict]:
        return []

# ─────────────────────────────────────────────
# Dynamic Button Generation
# ─────────────────────────────────────────────
async def _generate_ollama_dynamic_response(
    system_prompt: str, user_query: str, context: str = "", source_file: str = ""
) -> dict:
    allowed_buttons = registry_prompt_text()
    suggested = suggest_actions(user_query, source_file=source_file)
    suggested_text = ", ".join(f'"{s["id"]}"' for s in suggested) if suggested else "none"

    json_prompt = f"""{system_prompt}

CRITICAL: You must respond ONLY in valid JSON format using this exact schema:
{{
  "answer": "Your text answer to the user goes here.",
  "next_actions": [
    {{"id": "action_id_from_registry", "title": "Button Title"}}
  ]
}}

Rules for next_actions:
- You MUST choose ids ONLY from this approved registry (id -> button title):
{allowed_buttons}

- Pick 2-3 actions that are the most relevant follow-ups for THIS answer's topic.
- Good starting candidates for this query: {suggested_text}
- Copy the button title EXACTLY as given in the registry for the chosen id.
- If no registry action is relevant, return an empty list for next_actions.
- Maximum 3 next_actions allowed. NEVER invent new ids or titles outside the registry.

Context to use for your answer:
{context[:10000] if context else "No additional context provided."}

Remember: You must output ONLY valid JSON. No markdown, no code blocks, no explanations outside the JSON structure."""

    providers = [
        ("ollama", OLLAMA_BASE_URL, OLLAMA_MODEL, "no-key-needed", "ollama"),
        ("groq", GROQ_API_URL, GROQ_MODEL, GROQ_API_KEY, "openai"),
        ("mistral", MISTRAL_API_URL, MISTRAL_MODEL, MISTRAL_API_KEY, "openai"),
    ]

    for name, url, model, api_key, api_type in providers:
        if not api_key:
            continue
        try:
            raw_response = await _call_llm_provider(name, url, model, api_key, api_type, json_prompt, user_query)
            parsed = _parse_faq_dynamic_json(raw_response, user_query)
            if parsed:
                logger.info(f"FAQ_DYNAMIC_SUCCESS | provider={name} | actions={len(parsed.get('next_actions', []))}")
                return parsed
            logger.warning(
                f"FAQ_DYNAMIC_PARSE_FAIL | provider={name} | raw[:300]={raw_response[:300]!r}"
            )
        except Exception as e:
            logger.warning(f"FAQ_DYNAMIC_FALLBACK | provider={name} failed: {e}")
            continue

    logger.warning("FAQ_DYNAMIC_ALL_FAILED | using keyword fallback")
    return _fallback_dynamic_buttons("", user_query)


async def _call_llm_provider(name, url, model, api_key, api_type, system_prompt, user_query) -> str:
    logger.info(f"LLM_CALL | provider={name} | model={model} | url={url}")
    if api_type == "ollama":
        try:
            if os.name == "nt":
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,name", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5, startupinfo=si,
                )
            else:
                result = subprocess.run(
                    ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,name", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=5,
                )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) == 4:
                        util, mem_used, mem_total, gpu_name = parts
                        logger.info(f"GPU_STATS | name={gpu_name} | util={util}% | mem={mem_used}/{mem_total}MB")
            else:
                logger.warning("GPU_STATS | nvidia-smi returned no GPU data")
        except FileNotFoundError:
            logger.warning("GPU_STATS | nvidia-smi not found — GPU logging unavailable")
        except Exception as e:
            logger.warning(f"GPU_STATS | failed: {e}")
    async with httpx.AsyncClient(timeout=30) as client:
        if api_type == "ollama":
            payload = {
                "model": model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                "format": "json",
                "keep_alive": "30m",
                "think": False,
                "options": {
                    "num_ctx": 8192,
                    "num_predict": 2048,
                    "num_gpu": 99,
                    "num_thread": 8,
                    "num_batch": 1024,
                    "flash_attention": True,
                    "temperature": 0.2,
                    "top_p": 0.9,
                    "repeat_penalty": 1.0,
                    "seed": 42,
                },
            }
            logger.info(
                f"LLM_CALL | provider={name} | model={model} | gpu={payload['options']['num_gpu']} | ctx={payload['options']['num_ctx']}"
            )
            response = await client.post(f"{url}/api/chat", json=payload, timeout=30)
            logger.info(f"LLM_RESPONSE | provider={name} | status={response.status_code}")
            response.raise_for_status()
            return response.json().get("message", {}).get("content", "").strip()
        else:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_query},
                ],
                "temperature": 0.2,
                "max_tokens": 1024,
            }
            response = await client.post(url, json=payload, headers=headers, timeout=30)
            logger.info(f"LLM_RESPONSE | provider={name} | status={response.status_code}")
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()


def _parse_faq_dynamic_json(raw_response: str, user_query: str) -> dict | None:
    if not raw_response:
        return None

    # Strategy 1: raw load; Strategy 2: markdown fences stripped;
    # Strategy 3: substring from first '{' to last '}'
    cleaned = re.sub(r"```(?:json)?", "", raw_response).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    candidates = [raw_response.strip(), cleaned]
    if start != -1 and end > start:
        candidates.append(cleaned[start:end + 1])

    for cand in candidates:
        try:
            parsed = json.loads(cand)
            if isinstance(parsed, dict) and "answer" in parsed:
                return _validate_faq_dynamic_result(parsed, user_query)
        except (json.JSONDecodeError, TypeError):
            continue

    # Strategy 4: legacy regex extraction
    patterns = [
        r"```(?:json)?\s*\n?(\{.*?\})\s*```?",
        r'\{[^{}]*"answer"[^{}]*"next_actions"[^{}]*\[[^\]]*\][^{}]*\}',
        r"\{.*?\}",
    ]
    for pat in patterns:
        match = re.search(pat, raw_response, re.DOTALL)
        if match:
            try:
                json_str = match.group(1) if match.groups() else match.group(0)
                parsed = json.loads(json_str)
                if isinstance(parsed, dict) and "answer" in parsed:
                    return _validate_faq_dynamic_result(parsed, user_query)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    return None


def _validate_faq_dynamic_result(parsed: dict, user_query: str = "") -> dict:
    parsed = dict(parsed)
    parsed["_query"] = user_query
    answer = parsed.get("answer", "")
    next_actions = parsed.get("next_actions", [])
    if not isinstance(next_actions, list):
        next_actions = []

    # Only keep actions that exist in the registry — invented buttons are dropped.
    # (BUTTON_REGISTRY / enforce_topic_actions are module-level imports; see the
    # "Button registry + topic-relevance filter" section near the top.)
    validated = []
    for action in next_actions:
        if isinstance(action, dict):
            aid = (action.get("id", "") or "").strip()
            spec = BUTTON_REGISTRY.get(aid)
            if not spec:
                logger.info(f"BUTTON_DROPPED | invented/unknown id: {aid!r}")
                continue
            # Prefer the registry title (canonical, <= 20 chars).
            validated.append({"id": aid[:50], "title": spec["title"][:20]})

    # Topic relevance filter: keep only buttons related to the user's query,
    # backfilling in topic relevance order. Prevents unrelated generic
    # buttons (e.g. "View Catalogue" on a payments answer).
    if enforce_topic_actions:
        try:
            validated = enforce_topic_actions(validated, parsed.get("_query", ""), limit=3)
        except Exception as exc:
            logger.warning(f"enforce_topic_actions failed ({exc}) — keeping registry-valid buttons")
    else:
        logger.warning("enforce_topic_actions unavailable — topic filter disabled")

    return {"answer": answer[:10000], "next_actions": validated[:3]}


def _fallback_dynamic_buttons(raw_text: str, user_query: str, source_file: str = "") -> dict:
    if not raw_text:
        raw_text = "I'm having trouble generating a response. Please try again or contact our support team."

    # Topic-aware suggestions from the shared registry (guaranteed-implemented actions).
    try:
        next_actions = [
            {"id": s["id"], "title": s["title"]}
            for s in suggest_actions(user_query, source_file=source_file)
        ]
    except Exception as exc:
        logger.warning(f"Registry suggestion failed, using no buttons: {exc}")
        next_actions = []

    return {"answer": raw_text[:4000], "next_actions": next_actions[:3]}


def _build_interactive(next_actions: list[dict]) -> dict | None:
    """Convert validated actions into a WhatsApp interactive-buttons payload.

    Single place for the reply-button shape so limits (id <= 256 chars,
    title <= 20 chars, max 3 buttons) are enforced consistently everywhere.
    """
    if not next_actions:
        return None
    buttons = [
        {"type": "reply", "reply": {"id": a["id"][:256], "title": a["title"][:20]}}
        for a in next_actions
        if a.get("id") and a.get("title")
    ]
    return {"type": "button", "buttons": buttons[:3]} if buttons else None


# ─────────────────────────────────────────────
# FAQ Index
# ─────────────────────────────────────────────
class FAQIndex:
    """
    Hybrid retrieval:
      1. Dense  – FAISS IndexFlatIP (cosine via L2-normed embeddings)
      2. Sparse – BM25Okapi with stopword-filtered tokenization
      3. Fusion – Weighted Reciprocal Rank Fusion (RRF)
      4. Re-rank – CrossEncoder with CE score threshold
    """

    def __init__(self):
        self.chunks: list[str]    = []
        self.metadata: list[dict] = []
        self.embeddings: np.ndarray | None = None
        self.index: faiss.Index | None     = None
        self.bm25:  BM25Okapi | None       = None
        self.tokenized_corpus: list[list[str]] = []
        self.is_built = False
        self._lock = threading.Lock()

    # ── build ─────────────────────────────────
    def build(self, force: bool = False):
        with self._lock:
            if self.is_built and not force:
                return
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM faq_dataset").fetchall()
                conn.close()
            except Exception as exc:
                logger.error(f"Failed to load chunks: {exc}")
                return

            if not rows:
                logger.warning("No chunks in database")
                return

            chunks, metadatas, all_embeddings, missing = [], [], [], []

            for row in rows:
                chunks.append(row["content"])
                metadatas.append({
                    "source":       "document",
                    "id":           row["id"],
                    "source_file":  row["source_file"],
                    "content_type": row["content_type"],
                    "page_number":  row["page_number"],
                    "tenant_id":    row["tenant_id"] if "tenant_id" in row.keys() else "default",
                    "media_url":    row["media_url"]  if "media_url"  in row.keys() else None,
                    "media_type":   row["media_type"] if "media_type" in row.keys() else None,
                })

                if row["embedding"]:
                    all_embeddings.append(
                        np.frombuffer(row["embedding"], dtype=np.float32)
                    )
                else:
                    missing.append((len(chunks) - 1, row["id"], row["content"]))

            # Compute missing embeddings
            if missing:
                to_encode = [m[2] for m in missing]
                computed  = embedding_model.encode(to_encode, convert_to_numpy=True)
                computed  = self._normalize(computed).astype(np.float32)

                save_data = []
                for i, (chunk_idx, chunk_id, _) in enumerate(missing):
                    all_embeddings.insert(chunk_idx, computed[i])
                    save_data.append((chunk_id, computed[i].tobytes()))

                save_embeddings(save_data)
                logger.info(f"Computed and saved {len(save_data)} new embeddings")

            # Build FAISS index (dense)
            emb_matrix = np.array(all_embeddings, dtype=np.float32)
            self.index = faiss.IndexFlatIP(EMBEDDING_DIM)
            self.index.add(emb_matrix)

            # Build BM25 index (sparse) with improved tokenization
            tokenized = [simple_tokenize(c) for c in chunks]
            self.bm25             = BM25Okapi(tokenized)
            self.tokenized_corpus = tokenized

            self.chunks   = chunks
            self.metadata = metadatas
            self.embeddings = emb_matrix
            self.is_built = True
            logger.info(f"FAQ index built: {len(chunks)} vectors (dense + sparse)")

    # ── helpers ───────────────────────────────
    @staticmethod
    def _normalize(vecs: np.ndarray) -> np.ndarray:
        return vecs / (np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-10)

    def _dense_search(self, query: str, k: int) -> list[tuple[int, float]]:
        """Return (chunk_index, cosine_score) pairs."""
        q_emb = np.frombuffer(_encode_query_cached(query), dtype=np.float32).reshape(1, -1)
        distances, indices = self.index.search(q_emb, k)
        return [
            (int(idx), float(dist))
            for idx, dist in zip(indices[0], distances[0])
            if idx != -1
        ]

    def _sparse_search(self, query: str, k: int) -> list[tuple[int, float]]:
        """Return (chunk_index, bm25_score) pairs with filtered tokenization."""
        tokens = simple_tokenize(query)
        scores = self.bm25.get_scores(tokens)
        top_k  = np.argsort(scores)[::-1][:k]
        return [(int(i), float(scores[i])) for i in top_k if scores[i] > 0]

    @staticmethod
    def _reciprocal_rank_fusion(
        *ranked_lists: list[tuple[int, float]],
        weights: list[float] | None = None,
        k: int = RRF_K,
    ) -> list[tuple[int, float]]:
        if weights is None:
            weights = [1.0] * len(ranked_lists)

        rrf_scores: dict[int, float] = {}
        for weight, ranked in zip(weights, ranked_lists):
            for rank, (idx, _) in enumerate(ranked, start=1):
                rrf_scores[idx] = rrf_scores.get(idx, 0.0) + weight / (k + rank)

        return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    def _rerank(
        self,
        query: str,
        candidates: list[tuple[int, float]],
        top_k: int,
    ) -> list[tuple[str, dict, float]]:
        if not candidates:
            return []

        texts = [self.chunks[idx] for idx, _ in candidates]
        pairs = [[query, t] for t in texts]
        scores = cross_encoder.predict(pairs)

        ranked = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        return [
            (self.chunks[idx], self.metadata[idx], float(ce_score))
            for (idx, _), ce_score in ranked
            if ce_score >= CE_SCORE_THRESHOLD
        ]

    # ── public search ─────────────────────────
    def search(
        self,
        query: str,
        k: int = RERANK_TOP_K,
        tenant_id: str | None = None,
    ) -> list[tuple[str, dict, float]]:
        if not self.is_built:
            return []

        tid = _resolve_tenant_id(tenant_id)

        # Step 1 — candidate retrieval. Over-fetch while filtering by tenant
        # so other tenants' chunks don't starve this tenant of candidates.
        cand_mult = 4 if tid else 1
        dense_results  = self._dense_search(query, SEMANTIC_CANDIDATE_K * cand_mult)
        sparse_results = self._sparse_search(query, BM25_CANDIDATE_K * cand_mult)

        # Step 2 — weighted RRF fusion
        fused = self._reciprocal_rank_fusion(
            dense_results, sparse_results,
            weights=[RRF_WEIGHTS["dense"], RRF_WEIGHTS["sparse"]],
        )

        # Step 2b — tenant isolation: keep only this tenant's chunks
        if tid:
            fused = [
                (idx, rrf_score)
                for idx, rrf_score in fused
                if (self.metadata[idx].get("tenant_id") or "default") == tid
            ]

        # Step 3 — hard threshold on dense score
        dense_scores = {idx: score for idx, score in dense_results}
        pre_filter_count = len(fused)
        fused = [
            (idx, rrf_score)
            for idx, rrf_score in fused
            if dense_scores.get(idx, 0.0) >= SIMILARITY_THRESHOLD
        ]

        logger.info(
            f"Search query: '{query}' | "
            f"Fused candidates: {pre_filter_count} → after threshold: {len(fused)} | "
            f"Dense top scores: {[round(s, 4) for _, s in dense_results[:5]]}"
        )

        if not fused and dense_results:
            logger.warning(
                f"All candidates rejected by threshold ({SIMILARITY_THRESHOLD}) for: '{query}' | "
                f"Closest rejected: {[(self.chunks[idx][:100], round(score, 4)) for idx, score in dense_results[:5]]}"
            )

        # Step 4 — cross-encoder re-rank with CE score threshold
        return self._rerank(query, fused, top_k=k)


# ─────────────────────────────────────────────
faq_index = FAQIndex()

SYSTEM_PROMPT_TEMPLATE = """
You are a friendly, helpful assistant for {brand_name}, {brand_tagline}.

Your job is to answer the user's question using ONLY the information provided in the context.

🚨 STRICT FORMATTING RULES (MANDATORY):
- DO NOT WRITE PARAGRAPHS. PARAGRAPHS ARE STRICTLY FORBIDDEN.
- EVERY SINGLE LINE of your answer MUST start with a bullet point (`• `).
- Do NOT write an introductory sentence before the bullets.
- Do NOT write a closing paragraph after the bullets.
- Format the entire response strictly as a list of bullet points.

POLICIES, GST, TERMS OF USE & DETAILED QUERIES:
- When the user asks about Policies, GST, Terms of Use, Shipping, Replacements, Pricing, or Product Specifications, provide COMPREHENSIVE and DETAILED information.
- Break down every policy condition, percentage, rule, deadline, exemption, and requirement into individual bullet points.
- Do not over-summarize; ensure critical facts, figures, and legal/policy limits from the context are fully stated.
- Never include URLs unless explicitly provided in the context.
- Never tell the user to visit the website if the information is available in the context.
- Use 100-160 words.
- Cover important amount, days, period, conditions etc


RESPONSE STRUCTURE (WhatsApp/Dunzo style: warm, helpful, simple):
• [Direct, friendly answer to the main question + key emoji]
• [Detailed fact / policy condition / key number in *bold*]
• [Additional terms, GST rules, pricing details, or process steps]
• [Any extra conditions, limits, timelines, or exceptions]
• [Friendly closing line inviting the next step / question]
• Always start new bullet point from new line.

GENERAL RULES:
- Read ALL context carefully before responding.
- Never invent, assume, or calculate information not found in the context.
- Use simple, jargon-free words (e.g., "update policies" instead of "revise policies").
- If information is missing, state it honestly in a single bullet point.

HUMAN SUPPORT TRIGGER:
If the user is frustrated, confused, asks for human support, or asks about delays, complaints, billing issues, distributor partnerships, or missing information, include these bullets:
• 🙋 **Need further assistance?** Our support team is happy to help!
• 📧 Email us at: {support_email}
• 📞 Call us at: {support_phone}
• 💬 We'll assist you and get back to you as soon as possible!

End EVERY response with this signature on its own line:
---
{signature}
"""

STRICT_SYSTEM_PROMPT_TEMPLATE = """
You are a friendly, helpful assistant for {brand_name}, {brand_tagline}.

The retrieved context is a PARTIAL match to the user's question. Extract and combine ALL available relevant details.

🚨 STRICT FORMATTING RULES (MANDATORY):
- DO NOT WRITE PARAGRAPHS. PARAGRAPHS ARE STRICTLY FORBIDDEN.
- EVERY SINGLE LINE of your answer MUST start with a bullet point (`• `).
- Do NOT write an introductory sentence before the bullets.
- Do NOT write a closing paragraph after the bullets.
- Format the entire response strictly as a list of bullet points.

EXPANDED POLICY & TERMS RULE:
- For questions on GST, Policies, Terms of Use, Shipping, Replacements, or Pricing, extract and present ALL available conditions, rules, timelines, and numbers in thorough bullet points.
- Keep all specific numbers, percentages, fees, and conditions intact without skipping details.
- Add relevant emojis to points for readability.
- Use 100-160 words.
- Cover important amount, days, period, conditions etc

RESPONSE STRUCTURE:
• [Direct answer based on the available context + emoji]
• [Specific policy rule, GST detail, condition, or partial answer with *bold* highlights]
• [Additional relevant context facts / timelines / steps]
• [Honest note about missing details or offer to connect with human support]
• Always start new bullet point from new line.

HUMAN SUPPORT TRIGGER:
If the query cannot be fully resolved, or involves sensitive topics (billing, complaints, disputes, refunds), include these bullets:
• 🙋 **Need further assistance?** Our support team is happy to help!
• 📧 Email us at: {support_email}
• 📞 Call us at: {support_phone}
• 💬 We're available to help and will get back to you as quickly as possible!

End EVERY response with this signature on its own line:
---
{signature}
"""
# ─────────────────────────────────────────────
# Dynamic catalogue / new-arrivals listing
# ─────────────────────────────────────────────
# Listing requests ("✨ New Releases", "show new releases", "brochure", etc.)
# are answered from the COMPLETE module content in faq_dataset instead of the
# top-k RAG chunks. The generic SYSTEM_PROMPT_TEMPLATE caps answers at 100-160 words,
# which makes the LLM summarise a product table down to a few items; this
# prompt instead mandates enumerating EVERY product found in the context.

_LISTING_KEYWORDS = {
    "new_arrival": (
        "new arrival", "new arrivals", "new launch", "new launches",
        "latest product", "latest launch", "fresh drops", "recent additions",
        "new product", "new products", "show latest", "new items",
        "new release", "new releases", "latest release", "latest releases",
        "what is new", "whats new", "what's new",
    ),
    "catalogue": (
        "catalogue", "catalog", "brochure", "product list", "price list",
        "product lineup", "product range", "full catalogue", "full catalog",
        "our products", "show products", "products available",
    ),
}

_LISTING_GUARD_MARKERS = (
    "what is the", "what are the", "how do", "how to", "how can", "is there",
    "are there", "tell me", "detail", "ingredient", "contain", "inside",
    "spec", "nutrition", "flavour", "flavor", "policy", "terms", "gst",
    "shipping", "replace", "return", "offer", "discount on", "price of",
)

def _resolve_listing_module(message: str) -> str | None:
    """Return the faq_dataset module ('new_arrival' / 'catalogue') that a
    listing request refers to, or None when the message is a normal content
    question that must go through RAG retrieval instead."""
    lower = " ".join((message or "").lower().split())
    if not lower:
        return None

    # Never hijack content / policy questions that merely mention the words.
    if any(m in lower for m in _LISTING_GUARD_MARKERS):
        return None

    hits: set[str] = set()
    for mod, kws in _LISTING_KEYWORDS.items():
        if any(kw in lower for kw in kws):
            hits.add(mod)

    if not hits:
        for w, mod in (("arrival", "new_arrival"), ("launch", "new_arrival"),
                       ("latest", "new_arrival"), ("release", "new_arrival"),
                       ("catalogue", "catalogue"), ("catalog", "catalogue"), ("brochure", "catalogue")):
            if re.search(rf"\b{w}s?\b", lower):
                hits.add(mod)

    if not hits:
        return None
    if "new_arrival" in hits:
        return "new_arrival"
    return "catalogue"

def _fetch_module_full_content(modules: tuple[str, ...], tenant_id: str | None = None) -> str | None:
    """Fetch the COMPLETE stored content for one (or more) modules from
    faq_dataset. Prefers clean `table` chunks when present (they hold the full
    product rows); otherwise concatenates all paragraph chunks in document
    order. Fully dynamic — reads the database on every request."""
    marks = ",".join("?" * len(modules))
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"SELECT content, content_type FROM faq_dataset "
            f"WHERE module IN ({marks}) AND tenant_id = ? ORDER BY page_number, id",
            tuple(modules) + (_resolve_tenant_id(tenant_id),),
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.warning(f"Listing content fetch failed: {exc}")
        return None

    if not rows:
        return None

    tables = [r["content"] for r in rows if str(r["content_type"] or "").strip().lower() == "table"]
    if tables:
        return "\n\n".join(tables)
    return "\n\n".join(r["content"] for r in rows)

LISTING_SYSTEM_PROMPT_TEMPLATE = """
You are a friendly, helpful assistant for {brand_name}, {brand_tagline}.

The user asked to see the product list (new releases or brochure). The context is the COMPLETE product data extracted from the company's PDF.

🚨 STRICT RULES (MANDATORY):
- List EVERY single product in the context. DO NOT omit any product, even Sold Out / Out of Stock items.
- ONE bullet point (`• `) per product, each starting on a new line.
- For each product include: product name, category, pack size / weight, regular price and sale price if both are present, discount %, and stock status.
- Never invent, guess, or calculate products, names, prices, or specs that are not in the context.
- If the context contains no products, say so honestly in a single bullet.
- DO NOT write paragraphs. DO NOT write an introductory sentence or closing paragraph.
- This is a request for the full list: completeness matters MORE than word count. Ignore any generic 100-160 word guidance.

RESPONSE STRUCTURE:
• [Product 1 – name | pack size | ₹price | stock status]
• [Product 2 – name | pack size | ₹price | stock status]
... and so on for EVERY product ...
• [Friendly closing line inviting the next step]

End EVERY response with this signature on its own line:
---
{signature}
"""

async def _handle_listing_query(message: str, tenant_id: str | None = None) -> dict | None:
    """Answer a new-arrivals / catalogue listing request from the FULL module
    content in faq_dataset so every stored product is shown. Returns None when
    the message is not a listing request or the module has no data (the caller
    then falls through to the normal RAG path)."""
    module = _resolve_listing_module(message)
    if not module:
        return None
    modules = ("new_arrival",) if module == "new_arrival" else ("catalogue",)

    content = _fetch_module_full_content(modules, tenant_id)
    if not content:
        logger.warning(f"LISTING_QUERY | module={module} | no stored content")
        return None

    logger.info(f"LISTING_QUERY | module={module} | context_chars={len(content)}")

    brand = _brand_context(tenant_id)
    try:
        response = await _generate_ollama_dynamic_response(
            _render_prompt(LISTING_SYSTEM_PROMPT_TEMPLATE, brand),
            message, content, source_file=module,
        )
        answer = response.get("answer", "")
        if not answer:
            logger.warning(f"LISTING_QUERY | module={module} | empty LLM answer")
            return None

        result = {"answer": _append_signature(answer, tenant_id)}
        interactive = _build_interactive(response.get("next_actions", []))
        if interactive:
            result["interactive"] = interactive
        logger.info(f"LISTING_QUERY | module={module} | answered from full module content")
        return result
    except Exception as exc:
        logger.error(f"LISTING_QUERY | module={module} | generation error: {exc}", exc_info=True)
        return None


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────
def build_index() -> dict:
    faq_index.build(force=True)
    return {
        "status": "ok",
        "vectors": faq_index.index.ntotal if faq_index.is_built else 0,
    }


async def handle_faq_query(payload: dict) -> dict:
    message = payload.get("message", "").strip()
    tenant_id = _tenant_from_payload(payload)

    if not message:
        return {"answer": _append_signature("Please provide a question.", tenant_id)}

    # ── Dynamic catalogue / new-arrivals listing ──
    # Listing requests ("✨ New Arrivals", "show new arrivals", "catalogue")
    # are answered from the COMPLETE module content in faq_dataset instead of
    # the top-k RAG chunks, so the LLM enumerates every stored product instead
    # of summarising down to a few items. This runs before the FAQ index build
    # because it does not depend on RAG retrieval.
    listing_result = await _handle_listing_query(message, tenant_id)
    if listing_result:
        return listing_result

    if not faq_index.is_built:
        logger.warning("FAQ index not built on query — attempting on-demand build")
        try:
            faq_index.build()
        except Exception as exc:
            logger.error(f"On-demand FAQ index build failed: {exc}")

    if not faq_index.is_built:
        logger.warning("FAQ index still not built — returning fallback with buttons")
        fallback = _fallback_dynamic_buttons(
            "I'm still learning. Please try again shortly or contact our support team.", message
        )
        result = {"answer": _append_signature(fallback.get("answer", ""), tenant_id)}
        interactive = _build_interactive(fallback.get("next_actions", []))
        if interactive:
            result["interactive"] = interactive
        return result

    # ── Retrieve & re-rank ────────────────────
    results = faq_index.search(message, k=RERANK_TOP_K, tenant_id=tenant_id)

    if not results:
        logger.warning(
            f"Dissimilar question (no FAQ match): '{message}' | "
            f"Query returned 0 results after similarity threshold ({SIMILARITY_THRESHOLD})"
        )
        return {"answer": _append_signature("", tenant_id)}

    logger.info(f"Top 20 QA matches for user question: '{message}'")
    for rank, (chunk_text, metadata, score) in enumerate(results, start=1):
        logger.info(
            f"  Match #{rank} | Score: {score:.3f} | "
            f"Source: {metadata.get('source_file', 'N/A')} | "
            f"Content: {chunk_text[:200]}"
        )

    best_ce_score = results[0][2]

    # ── Build context (filter by CE score) ────
    context_parts = []

    for chunk_text, metadata, score in results:
        if score < CE_SCORE_THRESHOLD:
            continue
        context_parts.append(f"[relevance={score:.3f}]\n{chunk_text}")

    # Fallback: use best result even if below threshold
    if not context_parts:
        best_text, best_meta, best_score = results[0]
        context_parts = [f"[relevance={best_score:.3f}]\n{best_text}"]

    # Media: only from the top result
    best_meta = results[0][1]
    media_url  = best_meta.get("media_url")  or None
    media_type = best_meta.get("media_type") or None

    context = "\n\n---\n\n".join(context_parts)

    if media_url:
        media_label = "document" if media_type == "document" else "image"
        context += (
            f"\n\n[An attached {media_label} accompanies this reply and is sent "
            f"separately to the customer. Do NOT include its file link or any URL "
            f"in your text, and do NOT tell the customer to view products, "
            f"lineups, or images on the website — the attached {media_label} "
            f"already shows them.]"
        )

    # ── Two-tier: pick system prompt by confidence ──
    brand = _brand_context(tenant_id)
    if best_ce_score >= HIGH_CONFIDENCE_THRESHOLD:
        system_prompt = _render_prompt(SYSTEM_PROMPT_TEMPLATE, brand)
        logger.info(f"High confidence ({best_ce_score:.3f}) for: '{message}'")
    elif best_ce_score >= MEDIUM_CONFIDENCE_THRESHOLD:
        system_prompt = _render_prompt(STRICT_SYSTEM_PROMPT_TEMPLATE, brand)
        logger.info(f"Medium confidence ({best_ce_score:.3f}) for: '{message}' — strict prompt")
    else:
        logger.info(f"Low confidence ({best_ce_score:.3f}) for: '{message}' — using raw chunk with keyword buttons")
        best_chunk = results[0][0]
        fallback = _fallback_dynamic_buttons(best_chunk, message, source_file=best_meta.get("source_file", "") or "")
        result = {"answer": _append_signature(fallback.get("answer", best_chunk), tenant_id)}
        if media_url:
            result["media_url"]  = media_url
            result["media_type"] = media_type
        interactive = _build_interactive(fallback.get("next_actions", []))
        if interactive:
            result["interactive"] = interactive
        return result

    # ── Call Ollama LLM (with dynamic buttons) ──
    try:
        response = await _generate_ollama_dynamic_response(
            system_prompt, message, context,
            source_file=best_meta.get("source_file", "") or "",
        )

        answer = response.get("answer", "")
        next_actions = response.get("next_actions", [])

        result = {"answer": _append_signature(answer, tenant_id)}
        if media_url:
            result["media_url"]  = media_url
            result["media_type"] = media_type

        interactive = _build_interactive(next_actions)
        if interactive:
            result["interactive"] = interactive
        return result

    except Exception as exc:
        logger.error(f"Dynamic button generation error: {exc}", exc_info=True)
        best_chunk, best_meta_fb, _ = results[0]
        fallback = _fallback_dynamic_buttons(best_chunk, message, source_file=best_meta_fb.get("source_file", "") or "")
        result = {"answer": _append_signature(fallback.get("answer", best_chunk), tenant_id)}
        if media_url:
            result["media_url"]  = media_url
            result["media_type"] = media_type
        interactive = _build_interactive(fallback.get("next_actions", []))
        if interactive:
            result["interactive"] = interactive
        return result


def _format_answer_lines(text: str) -> str:
    """Force each bullet point onto its own line.

    The LLM sometimes returns multiple bullet points on a single line even
    though the prompts require one bullet per line. WhatsApp renders that
    as one unreadable wall of text, so we re-break the bullets here as a
    deterministic post-processing step.
    """
    if not text:
        return text or ""
    bullet = "•"
    # Insert a newline before any bullet that is not already at line start.
    text = re.sub(r"(?<!^)(?<!\n)[ \t]*" + bullet + r"[ \t]*", "\n" + bullet + " ", text, flags=re.MULTILINE)
    # Collapse excessive blank lines.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Trim trailing whitespace on each line.
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


def _enhanced_format_answer(text: str, message_type: MessageType = MessageType.FAQ_ANSWER, 
                           tenant_id: str = None) -> str:
    """
    Apply enhanced formatting with emojis, markdown, and proper structure.
    
    This enhances the basic formatting with:
    - Context-aware emojis
    - WhatsApp-compatible markdown
    - Better line breaks and spacing
    - Professional structure
    """
    if not text or text.strip() == "":
        return text or ""
    
    # Initialize formatter
    options = _get_formatter_options(tenant_id)
    formatter = WhatsAppFormatter(options)
    
    try:
        # Apply enhanced formatting
        formatted = formatter.format(text, message_type=message_type, 
                                      context={"tenant_id": tenant_id})
        
        # Also apply bullet fixing from existing function
        formatted = _format_answer_lines(formatted)
        
        return formatted
    except Exception as e:
        logger.debug(f"Enhanced formatting failed, falling back to basic: {e}")
        return _format_answer_lines(text)


def _get_formatter_options(tenant_id: str = None):
    """Get formatting options based on tenant or global configuration."""
    from services.response_formatters import FormattingOptions
    
    # For now, use standard options with rich formatting
    # Can be extended to load tenant-specific preferences later
    return FormattingOptions(
        use_emojis=True,
        use_markdown=True,
        use_hyperlinks=True,
        use_line_breaks=True,
        emoji_frequency="moderate",
        signature=_brand_context(tenant_id).get("signature", ""),
        brand_name=_brand_context(tenant_id).get("name", BRAND_NAME),
        max_line_length=400
    )


def _append_signature(text: str, tenant_id: str | None = None) -> str:
    """Sign off with the tenant's own closing signature, resolved from
    the profile layer (env config only as the no-profile fallback). The
    separator stays a plain dash: decoration belongs to the signature
    text a tenant configures.
    
    Also applies enhanced formatting to make responses more engaging.
    """
    # Apply enhanced formatting first
    if text and text.strip():
        text = _enhanced_format_answer(text, MessageType.FAQ_ANSWER, tenant_id)
    else:
        text = text or ""
    
    signature = _brand_context(tenant_id)["signature"]
    if not signature:
        return text
    
    text = text or ""
    if signature in text:
        return text
    return text.rstrip() + f"\n\n--- {signature}"
