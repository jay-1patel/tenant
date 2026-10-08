import os
import json
import time
import asyncio
import hashlib
import httpx
import re
import subprocess
from typing import Any, Dict, List, Tuple
from functools import lru_cache

import requests

from routing.config import (
    BUSINESS_NAME, logger, OLLAMA_API_URL, OLLAMA_MODEL,
    GROQ_API_URL, GROQ_API_KEY, GROQ_MODEL,
    MISTRAL_API_URL, MISTRAL_API_KEY, MISTRAL_MODEL,
)
from .rate_limiter import groq_rate_limiter

# Enhanced response cache to reduce repeated API calls (helps with rate limiting)
_response_cache = {}
_cache_ttl = 900  # 15 minutes (increased from 5 min)
_max_cache_size = 200  # Increased cache size

def _get_cache_key(prompt: str, context: str = "") -> str:
    """Generate cache key from prompt and context."""
    content = f"{prompt}|{context[:300]}"  # Increased context window
    return hashlib.md5(content.encode()).hexdigest()

def _get_cached_response(cache_key: str) -> str:
    """Get cached response if available and not expired."""
    if cache_key in _response_cache:
        timestamp, response = _response_cache[cache_key]
        if time.time() - timestamp < _cache_ttl:
            logger.info(f"✅ Cache HIT for key: {cache_key[:8]}")
            return response
        else:
            # Remove expired entry
            del _response_cache[cache_key]
    return None

def _cache_response(cache_key: str, response: str):
    """Cache a response with current timestamp."""
    _response_cache[cache_key] = (time.time(), response)
    # Keep cache size manageable
    if len(_response_cache) > _max_cache_size:
        # Remove oldest entries
        sorted_keys = sorted(_response_cache.keys(), key=lambda k: _response_cache[k][0])
        for key in sorted_keys[:20]:  # Remove 20 oldest at once
            del _response_cache[key]
    logger.info(f"💾 Cached response for key: {cache_key[:8]} (cache size: {len(_response_cache)})")

def _estimate_tokens(messages: list, max_tokens: int = 300) -> int:
    """Estimate token usage for a request."""
    total_chars = sum(len(str(msg.get('content', ''))) for msg in messages)
    # Rough estimation: 1 token ≈ 4 characters
    estimated_input_tokens = total_chars // 4
    return estimated_input_tokens + max_tokens
from .bot_config import (
    get_personality, get_guardrails, get_tools, get_escalation_rules,
    get_response_settings, get_fallback_message,
    get_contact_details, contact_details_available, get_domain_guardrails,
)
from .tools import registry as tool_registry, register_default_tools
from ..database import search_faq_db, search_knowledge_base_db, search_products
from .rag import search_kb_faiss

# CATEGORY_KEYWORDS moved to bot.config.json - loaded dynamically via bot_config.get_category_keywords()
# This provides domain-specific keyword mappings that are configurable per client
# The actual keywords are defined in bot.config.json under "category_keywords" key

# Unified category keywords for intent classification - now loaded from config
def _get_category_keywords() -> Dict:
    """Dynamically load category keywords from bot_config."""
    from .bot_config import get_category_keywords
    return get_category_keywords()

# API Provider Selection
API_PROVIDER = os.getenv("API_PROVIDER", "ollama").lower()  # Default to Ollama

register_default_tools()


def _get_groq_api_key() -> str:
    """Get Groq API key - backup provider"""
    key = os.getenv("GROQ_API_KEY")
    if not key:
        logger.warning("GROQ_API_KEY not set in .env")
        return None
    return key



def _get_mistral_api_key() -> str:
    """Get Mistral API key - primary provider for high-quality performance"""
    key = os.getenv("MISTRAL_API_KEY")
    if not key:
        logger.warning("MISTRAL_API_KEY not set in .env")
        return None
    return key


def _get_ollama_api_key() -> str:
    """Get Ollama API key - optional for local Ollama instances"""
    key = os.getenv("OLLAMA_API_KEY", "")
    # Ollama often doesn't require API keys for local instances
    return key or "no-key-needed"


def _get_api_config() -> tuple:
    """Get current API provider configuration - supports Ollama, Mistral, Cerebras, and Groq"""
    provider = API_PROVIDER

    # Try Ollama first if set as provider (new default)
    if provider == "ollama":
        api_key = _get_ollama_api_key()
        if api_key:
            logger.info(f"Using Ollama provider: {OLLAMA_API_URL} with model {OLLAMA_MODEL}")
            return OLLAMA_API_URL, OLLAMA_MODEL, api_key, "ollama"
        else:
            logger.warning("Ollama configuration incomplete, falling back to Mistral")
            provider = "mistral"

    # Try Mistral (secondary provider)
    if provider == "mistral":
        api_key = _get_mistral_api_key()
        if api_key:
            return MISTRAL_API_URL, MISTRAL_MODEL, api_key, "mistral"
        else:
            logger.warning("Mistral API key not found, falling back to Cerebras")
            provider = "cerebras"


    # Try Groq (backup provider)
    if provider == "groq":
        api_key = _get_groq_api_key()
        if api_key:
            return GROQ_API_URL, GROQ_MODEL, api_key, "groq"
        else:
            raise ValueError("No API key found for any provider")

    raise ValueError(f"Unknown API provider: {provider}")


def _format_contact_details(details: Dict) -> str:
    parts = []
    if details.get("phone"):
        parts.append(f"Phone: {details['phone']}")
    if details.get("email"):
        parts.append(f"Email: {details['email']}")
    if details.get("website"):
        parts.append(f"Website: {details['website']}")
    if details.get("address"):
        parts.append(f"Address: {details['address']}")
    return " | ".join(parts)


def _guess_category(query: str) -> str:
    q = query.lower()
    # Load category keywords dynamically from bot_config for per-client flexibility
    category_keywords = _get_category_keywords()
    for category, keywords in category_keywords.items():
        if any(kw in q for kw in keywords):
            return category
    return ""


def _get_tenant_profile(wa_id: str = ""):
    """Tenant profile for this user, or None when tenancy is unavailable."""
    try:
        from shared.tenancy import loader
        from shared.tenancy.resolver import resolve_tenant_for_user

        return loader.get_tenant_profile(resolve_tenant_for_user(wa_id))
    except Exception as e:
        logger.debug(f"tenant profile unavailable: {e}")
        return None


def get_brand_name(wa_id: str = "", profile=None) -> str:
    """Business name for the tenant this user belongs to.

    Falls back to the legacy global config so the pre-tenant stack keeps
    serving its own brand unchanged.
    """
    profile = profile if profile is not None else _get_tenant_profile(wa_id)
    brand = getattr(profile, "brand", None)
    name = ((getattr(brand, "name", "") or "") or getattr(profile, "display_name", "") or "").strip()
    if name:
        return name
    return BUSINESS_NAME or "Our Business"


def _resolve_tenant_id(wa_id: str = ""):
    """Tenant id owning this conversation, or None when tenancy is unavailable."""
    try:
        from shared.tenancy.resolver import resolve_tenant_for_user

        return resolve_tenant_for_user(wa_id)
    except Exception as e:
        logger.debug(f"tenant resolution unavailable: {e}")
        return None


def _tenant_contact_details(profile) -> Dict:
    """Contact details from the tenant profile (brand block)."""
    brand = getattr(profile, "brand", None)
    if brand is None:
        return {}
    return {
        "phone": (getattr(brand, "support_phone", "") or "").strip(),
        "email": (getattr(brand, "support_email", "") or "").strip(),
        "website": (getattr(brand, "website", "") or "").strip(),
        "address": "",
    }


def _build_system_prompt(retrieved_context: str = "", wa_id: str = "") -> str:
    profile = _get_tenant_profile(wa_id)
    business_name = get_brand_name(wa_id, profile=profile)
    personality = get_personality()
    guardrails = get_guardrails()

    # Identity first so per-tenant prompts never share a cache key prefix,
    # and so the model cannot fall back to any other company name.
    parts = [
        f"You are the WhatsApp assistant for {business_name}. "
        f"Always refer to the business by this exact name — never by any other company name.",
        personality,
    ]

    if guardrails:
        parts.append(f"\n## Rules & Guardrails\n{guardrails}")

    tenant_never_state = [
        str(x) for x in (getattr(getattr(profile, "guardrails", None), "never_state", None) or [])
    ]
    if tenant_never_state:
        parts.append(
            "\n## Tenant Rules (STRICT)\n"
            "NEVER state or promise: " + "; ".join(tenant_never_state) + "."
        )

    contact_details = get_contact_details()
    if not any(contact_details.values()):
        contact_details = _tenant_contact_details(profile)
    if any(contact_details.values()):
        parts.append("\n## Contact Details\n" + _format_contact_details(contact_details))
        parts.append(
            "If the user asks for contact information or address, answer directly with these details. "
            "If the details are not available, say you don't have them here and suggest the official website or packaging."
        )

    escalation = get_escalation_rules()
    if escalation:
        trigger_phrases = escalation.get("trigger_phrases", [])
        esc_msg = escalation.get("escalation_message", "I'll connect you with our team.")
        parts.append(f"\n## Escalation\nIf the user seems upset or uses words like: {', '.join(trigger_phrases)}, say: \"{esc_msg}\"")

    parts.append(f"\n## Business: {business_name}")
    parts.append("\n## CRITICAL: Tool Usage Requirements (MANDATORY)")
    parts.append("- You MUST use tools BEFORE answering product-related questions")
    parts.append("- For ANY question about products, ingredients, allergens, diet, or recommendations: CALL search_products OR get_product_details FIRST — they return nutritional_facts and ingredients fields with the actual data.")
    parts.append("- For calorie/nutrition-portion questions (e.g. 'I ate a millet chikki', 'how many calories in 2 peanut chikkis', 'calories before gym'): CALL get_nutrition_info FIRST — it returns exact calories per piece and per portion. Then answer directly with the number.")
    parts.append("- For health/diet/allergy questions: ALWAYS use tools to get actual product data - never answer from general knowledge")
    parts.append("- DO NOT answer product questions without calling tools - this is mandatory")
    parts.append("- Available tools: search_products, get_product_details, get_nutrition_info, get_products_by_category, get_faq_answer")
    parts.append("- Call the appropriate tool, use the results to answer, and include specific product details and prices")
    parts.append("\n## Formatting Rules (strict)")
    parts.append("- Use ONLY WhatsApp formatting: *bold*, _italic_, - bullet points")
    parts.append("- For company policy, terms, warranty, return, refund, shipping, or detailed informational questions: provide comprehensive answers with key points, bullet points, and important details (aim for 4-8 sentences or structured bullet points)")
    parts.append("- For simple product questions or casual conversation: keep responses conversational and helpful (2-4 sentences)")
    parts.append("- Match response length to question complexity - detailed questions deserve detailed answers")
    parts.append("- NEVER use markdown headers (#), tables, code blocks, or emojis like 😊")
    parts.append("- Sound like a friendly, helpful salesperson - natural and confident")
    parts.append("- NEVER say phrases like 'Based on the search results' or 'According to the database' - just give direct answers")
    parts.append("- When mentioning a product, include its price if available")
    parts.append("- For product questions, be specific and helpful with recommendations")
    parts.append("- For health/diet questions, give helpful guidance based on actual product data")
    parts.append("- If the user asks for contact details and you don't have them, say 'I don't have those details here, but you can find them on our website or packaging.'")
    parts.append("- If you don't know something after checking, say 'I'm not sure about that - let me connect you with our team.'")
    parts.append("- Use retrieved knowledge to give direct, helpful answers")
    parts.append("- When you have good information from tools or knowledge base, be confident and specific")
    parts.append("- Structure answers clearly: direct answer first, then details if helpful")
    parts.append("- NEVER mention or repeat source document names, file names, titles, or labels like [Company_Details.pdf] in your answer. The [title] prefixes in the retrieved knowledge are internal references only — never quote them, refer to them, or include them in the reply.")

    parts.append("\n## Grounding & Anti-Hallucination Rules (STRICT)")
    parts.append("- You must answer using information from: 1) Tool results (priority), 2) Retrieved knowledge base context")
    parts.append("- Tool results provide REAL product data - use them instead of general knowledge or assumptions")
    parts.append("- If tools don't provide sufficient information and the retrieved context does not contain a clear, explicit answer, respond with: \"I don't have that exact information right now. I can check with the team or you can confirm on our website — want me to connect you?\"")
    parts.append("- NEVER guess, estimate, average, or infer an answer under any circumstances, even partially.")
    parts.append("- EXCEPTION (allowed): You MAY state exact computed per-portion numbers returned by the get_nutrition_info tool (e.g. 'about 74 kcal per 15g piece'). That tool performs exact arithmetic on official nutrition data, so its numbers are real tool results, not guesses.")
    parts.append("- For product questions, ALWAYS use tools to get current data before answering")
    parts.append("- Hard-blocked categories — MUST use tools or retrieved context for these:")
    parts.append("  - Prices, discounts, or offers — use tools to get actual prices, do not estimate")
    parts.append("  - Certifications (organic, FSSAI, ISO, gluten-free, vegan, etc.) — use tools to get product details. If asked and not found in tool results, say: \"I'm not certain about that certification — please check the product packaging or our website.\"")
    parts.append("  - Medical, health, or nutrition claims — use tools to get actual product data. You may state specific facts from tool results (e.g. ingredients, nutrition facts in the nutritional_facts field — a tab-separated table with columns per variant) but not add claims not in the data.")
    parts.append("  - Stock/availability at specific locations — always defer to the website/store/human handover.")
    parts.append("  - Any personal, biographical, or company detail not explicitly retrieved.")
    parts.append("- When a user asks an evaluative or open-ended question (e.g. is it healthy?, should I buy this?), state only the specific facts from tool results and let the user draw their own conclusion.")
    parts.append("- Allergy/safety questions — HIGHEST PRIORITY:")
    parts.append("  1. This question must always receive a direct answer — use tools to get actual product allergen information")
    parts.append("  2. Use search_products or get_product_details tools to get actual ingredient and allergen data")
    parts.append("  3. If allergen data from tools is missing or unclear, say so explicitly and recommend they double check packaging or contact the brand directly — never imply a product is safe without explicit allergen data from tools.")
    parts.append("  4. If tools fail or API has issues, respond with: \"I want to make sure I get this right for you — let me connect you with our team,\"")
    parts.append("- Ambiguous questions (e.g. how much is the chikki?): Use tools to search products, then list the 2-3 most relevant options with their actual prices from tool results.")
    parts.append("- Self-check before responding: Before sending any answer containing a number, price, certification claim, or health claim, verify that this exact fact is present in tool results or retrieved context. If no — do not include it.")

    if retrieved_context:
        parts.append("\n## Retrieved Knowledge\n")
        parts.append(retrieved_context)

    return "\n".join(parts)


def _build_chat_history(history: List[Dict] = None) -> List[Dict]:
    if not history:
        return []
    messages = []
    settings = get_response_settings()
    max_msgs = settings.get("memory_max_messages", 10)
    for turn in history[-max_msgs:]:
        user_msg = turn.get("user", "")
        if user_msg and "] " in user_msg:
            user_msg = user_msg.split("] ", 1)[-1]
        if user_msg:
            messages.append({"role": "user", "content": user_msg})
        assistant_msg = turn.get("assistant", "")
        if assistant_msg:
            messages.append({"role": "assistant", "content": assistant_msg})
    return messages


_STOP_WORDS = frozenset((
    "who", "what", "how", "can", "the", "for", "and", "are", "its", "not", "but",
    "all", "you", "your", "tell", "about", "some", "which", "also", "have", "does",
    "would", "could", "should", "want", "need", "like", "know", "ate", "eat", "eats",
    "if", "is", "of", "to", "in", "do", "did", "done", "am", "an", "why", "when",
    "where", "them", "their", "please", "thanks", "thank", "help", "info", "give",
    "gives", "given", "show", "shows", "looking", "look",
    "view", "see", "check", "checked", "click", "clicked", "clicking",
    "user", "users", "page", "menu", "item", "button", "option",
    "right", "back", "go", "goes", "going", "came", "come",
    "hey", "yes", "no", "use", "used", "just", "also", "says", "say",
    "make", "makes", "put", "puts", "got", "get", "reply", "replies",
    "things", "thing", "way", "ways", "let", "day", "days", "today",
    "asking", "asked", "ask", "needed", "wanted", "looking",
    "new", "old", "big", "small", "first", "last", "next",
))


def _tokenize(text: str) -> List[str]:
    import re as _re
    return [
        w.lower() for w in _re.findall(r"[a-zA-Z]{3,}", text)
        if w.lower() not in _STOP_WORDS
    ]


def _score_faq(faq: Dict, query_tokens: List[str]) -> float:
    import re as _re
    content = (faq.get("content") or "").lower()
    score = sum(2.0 for t in query_tokens if _re.search(r"(?<!\w)" + _re.escape(t) + r"(?!\w)", content))
    if "current offers" in content or "current offer" in content:
        score += 6.0
    if _re.search(r"\bdiscount\b", content) or _re.search(r"\boffers?\b", content):
        score += 4.0
    return score


def _format_kb_candidates(kb_results, faiss_results, query: str, k: int):
    import re as _re
    query_tokens = _tokenize(query)
    seen_ids = set()
    candidates = []

    for doc in (kb_results or [])[:k]:
        doc_id = doc.get("id")
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        title = doc.get("title", "")
        content = doc.get("content", "")

        if not content or not content.strip():
            continue

        chunks_json = doc.get("chunks_json")
        if chunks_json:
            try:
                chunks = json.loads(chunks_json) if isinstance(chunks_json, str) else chunks_json
                if chunks:
                    best_chunk = None
                    best_score = 0
                    for chunk in chunks:
                        chunk_lower = chunk.lower()
                        sc = sum(2 for t in query_tokens if _re.search(r"(?<!\w)" + _re.escape(t) + r"(?!\w)", chunk_lower))
                        if sc > best_score:
                            best_score = sc
                            best_chunk = chunk
                    content = best_chunk if best_chunk else chunks[0]
            except (json.JSONDecodeError, TypeError):
                pass

        if not content or not content.strip():
            continue

        if query_tokens:
            lower = content.lower()
            matched_idx = None
            for t in query_tokens:
                m = _re.search(r"(?<!\w)" + _re.escape(t) + r"(?!\w)", lower)
                if m:
                    matched_idx = m.start()
                    break
            if matched_idx is not None:
                start = max(0, matched_idx - 200)
                content = content[start:start + 2000]
            elif len(content) > 3000:
                content = content[:3000]
        elif len(content) > 3000:
            content = content[:3000]

        score = sum(2.0 for t in query_tokens if _re.search(r"(?<!\w)" + _re.escape(t) + r"(?!\w)", content.lower()))
        if "current offers" in content.lower() or "current offer" in content.lower():
            score += 6.0
        if _re.search(r"\bdiscount\b", content.lower()) or _re.search(r"\boffers?\b", content.lower()):
            score += 4.0
        candidates.append({
            "text": f"[{title}] {content}",
            "score": score,
            "metadata": doc,
        })

    for faiss_hit in (faiss_results or []):
        doc_id = faiss_hit.get("doc_id")
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        try:
            from ..database import get_db_context
            with get_db_context() as conn:
                row = conn.execute(
                    "SELECT * FROM knowledge_base WHERE id = ?", (doc_id,)
                ).fetchone()
            if not row:
                continue
            doc = dict(row)
            chunks_json = doc.get("chunks_json")
            content = doc.get("content", "")

            if chunks_json:
                try:
                    chunks = json.loads(chunks_json) if isinstance(chunks_json, str) else chunks_json
                    if chunks:
                        chunk_idx = faiss_hit.get("chunk_index", 0)
                        content = chunks[min(chunk_idx, max(len(chunks) - 1, 0))]
                except (json.JSONDecodeError, TypeError):
                    pass

            if not content or not content.strip():
                continue

            content = content[:500] if len(content) > 500 else content
            title = doc.get("title", "")
            score = faiss_hit.get("score", 0.0) * 10.0
            candidates.append({
                "text": f"[{title}] {content}",
                "score": score,
                "metadata": doc,
            })
        except Exception:
            continue

    return candidates


def _format_product_context(prod: Dict) -> str:
    parts = [
        f"Product: {prod.get('name', '')}",
        f"Price: {prod.get('price', 'N/A')}",
        f"Category: {prod.get('category', '')}",
    ]
    desc = prod.get("description") or prod.get("short_description") or ""
    if desc:
        parts.append(f"Description: {desc[:500]}")
    ingredients = prod.get("ingredients")
    if isinstance(ingredients, list) and ingredients:
        parts.append(f"Ingredients: {', '.join(ingredients)}")
    elif isinstance(ingredients, str) and ingredients:
        parts.append(f"Ingredients: {ingredients}")
    nutritional = prod.get("nutritional_facts") or ""
    if nutritional:
        parts.append(f"Nutritional Facts:\n{nutritional[:600]}")
    return "\n".join(parts)


def _score_product(prod: Dict, query_tokens: List[str]) -> float:
    import re as _re
    searchable = " ".join([
        (prod.get("name") or "").lower(),
        (prod.get("description") or "").lower(),
        (prod.get("short_description") or "").lower(),
        (prod.get("category") or "").lower(),
    ])
    ingredients = prod.get("ingredients")
    if isinstance(ingredients, list):
        searchable += " " + " ".join(i.lower() for i in ingredients)
    elif isinstance(ingredients, str):
        searchable += " " + ingredients.lower()
    nutritional = (prod.get("nutritional_facts") or "").lower()
    searchable += " " + nutritional

    score = sum(2.0 for t in query_tokens if _re.search(r"(?<!\w)" + _re.escape(t) + r"(?!\w)", searchable))

    name_lower = (prod.get("name") or "").lower()
    name_words = set(name_lower.split())
    matched_in_name = sum(1 for t in query_tokens if t in name_words or _re.search(r"(?<!\w)" + _re.escape(t) + r"(?!\w)", name_lower))
    if matched_in_name >= 2:
        score += 3.0

    if nutritional and any(_re.search(r"(?<!\w)" + _re.escape(t) + r"(?!\w)", nutritional) for t in query_tokens):
        score += 2.0

    if _re.search(r"\bdiscount\b", searchable) or _re.search(r"\boffers?\b", searchable):
        score += 4.0

    return score


def _retrieve_context(query: str, k: int = None, wa_id: str = "") -> Tuple[str, List[Dict]]:
    settings = get_response_settings()
    if k is None:
        k = settings.get("context_window", 3)

    tenant_id = _resolve_tenant_id(wa_id)
    query_tokens = _tokenize(query)
    candidates: List[Dict] = []

    # ---- Source 1: FAQ ----
    faq_results = search_faq_db(query, limit=k, tenant_id=tenant_id)
    for faq in faq_results:
        candidates.append({
            "text": faq["content"],
            "score": _score_faq(faq, query_tokens),
            "source": "faq",
            "metadata": faq,
        })

    # ---- Source 2: Knowledge base ----
    kb_results = search_knowledge_base_db(query, limit=k, tenant_id=tenant_id)
    faiss_results = search_kb_faiss(query, limit=k, tenant_id=tenant_id)
    for doc in _format_kb_candidates(kb_results, faiss_results, query, k):
        candidates.append({
            "text": doc["text"],
            "score": doc["score"],
            "source": "knowledge_base",
            "metadata": doc["metadata"],
        })

    # ---- Source 3: Products ----
    product_results = search_products(query, limit=k, tenant_id=tenant_id)
    for prod in product_results:
        candidates.append({
            "text": _format_product_context(prod),
            "score": _score_product(prod, query_tokens),
            "source": "product",
            "metadata": prod,
        })

    if not candidates:
        return "", []

    candidates.sort(key=lambda c: c["score"], reverse=True)
    top = candidates[:k]

    logger.info(
        f"RETRIEVED_CHUNKS | count={len(top)} | "
        f"sources={[c['source'] for c in top]} | scores={[round(c['score'], 3) for c in top]}"
    )
    for i, c in enumerate(top):
        logger.info(f"CHUNK[{i}] source={c['source']} score={c['score']:.3f}:\n{c['text'][:300]}")

    context_parts = [c["text"] for c in top]
    sources = [{"source": c["source"], "score": c["score"], "metadata": c["metadata"]} for c in top]
    return "\n\n---\n\n".join(context_parts), sources


def _requires_tool_call(user_message: str) -> bool:
    """Detect if a message requires mandatory tool usage."""
    # Only force tools for high-value questions to avoid rate limiting
    critical_keywords = [
        # Product recommendations (high value)
        "recommend", "suggest", "best", "prefer",
        # Health/safety critical (must use tools)
        "allerg", "allergic", "safe", "baby", "child", "kid",
    ]
    msg_lower = user_message.lower()
    return any(keyword in msg_lower for keyword in critical_keywords)

def _get_required_tool_for_message(user_message: str) -> str:
    """Determine which tool should be required for a given message."""
    msg_lower = user_message.lower()
    if any(kw in msg_lower for kw in ["calorie", "calories", "kcal", "nutrition", "protein", "carbs", "ate", "eat", "eaten"]):
        return "get_nutrition_info"
    elif any(kw in msg_lower for kw in ["category", "list", "browse", "show"]):
        return "list_categories"
    elif any(kw in msg_lower for kw in ["allerg", "diet", "health", "ingredient", "safe", "baby", "child", "kid"]):
        return "search_products"
    else:
        return "search_products"  # Default to search_products

def _normalize_llm_result(result: dict) -> dict:
    """Convert any provider response to OpenAI-compatible format.

    Ollama's native /api/chat endpoint returns {"message": {...}, "done": ...},
    while OpenAI-compatible providers return {"choices": [{"message": {...}}]}.
    """
    if not isinstance(result, dict):
        return result
    if "choices" in result:
        return result
    if "message" in result:
        return {"choices": [{"message": result["message"]}]}
    return result


def _call_groq_with_tools(messages: List[Dict], tools_schemas: List[Dict], user_message: str = "") -> Dict:
    """Call LLM API with tools (supports Ollama, Groq, Cerebras, and Mistral)"""
    api_url, model, api_key, provider = _get_api_config()

    headers = {
        "Content-Type": "application/json",
        "ngrok-skip-browser-warning": "true",
    }

    # Only add Authorization header if we have a proper API key (not the placeholder)
    if api_key and api_key != "no-key-needed":
        headers["Authorization"] = f"Bearer {api_key}"
    settings = get_response_settings()
    max_tokens = settings.get("max_tokens", 300)  # Reduced from 1024 to 300
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": settings.get("temperature", 0.7),
    }
    if provider == "ollama":
        # Ollama defaults to streaming and (on thinking models like qwen3) to
        # emitting "thinking" tokens — both break the single-JSON response
        # parsing below and cause retry loops. Disable both explicitly.
        payload["stream"] = False
        payload["think"] = False
    if tools_schemas:
        payload["tools"] = tools_schemas
        # Force tool usage only for critical questions to avoid rate limiting
        if _requires_tool_call(user_message):
            # Use "auto" with strong prompting instead of "required" to avoid compatibility issues
            payload["tool_choice"] = "auto"
            logger.info(f"🔍 Critical question detected, tool usage encouraged: {user_message[:100]}")
        else:
            payload["tool_choice"] = "auto"

    logger.info(f"🚀 Sending to {provider.upper()}: model={model}, has_tools={bool(tools_schemas)}, tools_count={len(tools_schemas) if tools_schemas else 0}")
    logger.info(f"📦 Payload (first 500 chars): {str(payload)[:500]}")

    # Apply rate limiting with better token estimation (skip for Ollama, Cerebras and Mistral as they have better rate limits)
    if provider == "groq":
        estimated_tokens = _estimate_tokens(messages, max_tokens) + len(str(tools_schemas)) // 4  # Add tool schema tokens
        wait_time = groq_rate_limiter.acquire(estimated_tokens)
        if wait_time > 0:
            logger.info(f"⏳ Rate limiting: waiting {wait_time:.2f}s before tool API call")
            time.sleep(wait_time)
    elif provider == "ollama":
        logger.info(f"⚡ {provider.upper()} - No rate limiting for local Ollama instance")
    else:
        logger.info(f"⚡ {provider.upper()} - No rate limiting needed (ultra-fast inference)")

    last_err = None
    for attempt in range(10):  # Increased retries to 10 for better reliability
        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            logger.info(f"📊 {provider.upper()} response status: {response.status_code}, content preview: {response.text[:500]}")
            if response.status_code == 429:
                wait = 2 ** attempt + 6  # Optimized delay calculation
                logger.warning(f"⚠️ {provider.upper()} rate limited (429), waiting {wait}s (attempt {attempt + 1}/10)")
                last_err = requests.exceptions.RequestException(f"Rate limited (429) after {attempt + 1} attempts")
                if attempt < 9:
                    time.sleep(wait)
                    continue
                break
            if response.status_code == 400:
                # Handle tool choice errors
                try:
                    error_data = response.json()
                    if "Tool choice is required" in str(error_data):
                        logger.warning(f"🔧 Tool choice error, retrying with auto mode (attempt {attempt + 1}/10)")
                        payload["tool_choice"] = "auto"
                        if attempt < 9:
                            time.sleep(2)
                            continue
                except:
                    pass
            response.raise_for_status()
            if provider == "groq":
                groq_rate_limiter.record_request(estimated_tokens)  # Record successful request with actual tokens
                logger.info(f"✅ Tool API call successful, tokens estimated: {estimated_tokens}")

            # Handle Ollama streaming response format (multiple JSON objects separated by newlines)
            if provider == "ollama":
                response_text = response.text.strip()
                # Check if this is a streaming response (multiple JSON objects)
                if '\n' in response_text and response_text.count('{') > 1:
                    logger.info(f"🔄 Detected Ollama streaming response, parsing {response_text.count(chr(10)) + 1} chunks...")
                    # Parse streaming response - combine all content chunks
                    full_content = ""
                    full_thinking = ""
                    tool_calls = None
                    final_message = None

                    for line in response_text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            # Accumulate content from ALL chunks (including final one)
                            msg = chunk.get("message", {})
                            if msg.get("content"):
                                full_content += msg["content"]
                            if msg.get("thinking"):
                                full_thinking += msg["thinking"]
                            if msg.get("tool_calls"):
                                tool_calls = msg["tool_calls"]

                            if chunk.get("done"):
                                # Final chunk - we've accumulated all content
                                break
                        except json.JSONDecodeError:
                            continue

                    # Construct the final message with accumulated content
                    final_message = {
                        "role": "assistant",
                        "content": full_content,
                    }
                    if tool_calls:
                        final_message["tool_calls"] = tool_calls

                    result = {
                        "choices": [{
                            "message": final_message
                        }]
                    }
                    logger.info(f"✅ Parsed Ollama streaming response: content_length={len(full_content)}, has_tool_calls={bool(tool_calls)}")
                    return result
                else:
                    # Single JSON response (non-streaming)
                    return _normalize_llm_result(response.json())
            else:
                return response.json()
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < 9:
                time.sleep(3 * (attempt + 1))  # Better backoff strategy

    # Ensure we always have a proper exception to raise
    if last_err is None:
        last_err = requests.exceptions.RequestException("Groq API call failed with unknown error")
    raise last_err


def _call_groq_simple(messages: List[Dict]) -> str:
    """Call LLM API without tools (supports Ollama, Groq, Cerebras, and Mistral)"""
    api_url, model, api_key, provider = _get_api_config()

    headers = {
        "Content-Type": "application/json",
        "ngrok-skip-browser-warning": "true",
    }

    # Only add Authorization header if we have a proper API key (not the placeholder)
    if api_key and api_key != "no-key-needed":
        headers["Authorization"] = f"Bearer {api_key}"
    settings = get_response_settings()
    max_tokens = settings.get("max_tokens", 300)  # Reduced from 1024 to 300
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": settings.get("temperature", 0.7),
    }
    if provider == "ollama":
        # Same fix as the tools path: disable streaming/thinking so the
        # response is one complete JSON object with real content.
        payload["stream"] = False
        payload["think"] = False

    # Check cache for similar requests (helps with rate limiting)
    user_content = messages[-1].get("content", "") if messages else ""
    system_content = messages[0].get("content", "") if messages else ""
    cache_key = _get_cache_key(user_content, system_content[:300])
    cached_response = _get_cached_response(cache_key)
    if cached_response:
        return cached_response

    # Apply rate limiting with better token estimation (skip for Ollama, Cerebras and Mistral as they have better rate limits)
    if provider == "groq":
        estimated_tokens = _estimate_tokens(messages, max_tokens)
        wait_time = groq_rate_limiter.acquire(estimated_tokens)
        if wait_time > 0:
            logger.info(f"⏳ Rate limiting: waiting {wait_time:.2f}s before API call")
            time.sleep(wait_time)
    elif provider == "ollama":
        logger.info(f"⚡ {provider.upper()} - No rate limiting for local Ollama instance")
    else:
        logger.info(f"⚡ {provider.upper()} - No rate limiting needed (ultra-fast inference)")

    last_err = None
    for attempt in range(6):  # Increased retries to 6
        try:
            response = requests.post(api_url, json=payload, headers=headers, timeout=30)
            if response.status_code == 429:
                wait = 2 ** attempt + 4  # Optimized wait time
                logger.warning(f"⚠️ {provider.upper()} rate limited (429), waiting {wait}s (attempt {attempt + 1}/6)")
                last_err = requests.exceptions.RequestException(f"Rate limited (429) after {attempt + 1} attempts")
                if attempt < 5:
                    time.sleep(wait)
                    continue
                break
            response.raise_for_status()

            # Handle Ollama streaming response format (multiple JSON objects separated by newlines)
            if provider == "ollama":
                response_text = response.text.strip()
                # Check if this is a streaming response (multiple JSON objects)
                if '\n' in response_text and response_text.count('{') > 1:
                    logger.info(f"🔄 Detected Ollama streaming response in simple call, parsing chunks...")
                    # Parse streaming response - combine all content chunks
                    full_content = ""

                    for line in response_text.split('\n'):
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            # Accumulate content from ALL chunks (including final one)
                            msg = chunk.get("message", {})
                            if msg.get("content"):
                                full_content += msg["content"]

                            if chunk.get("done"):
                                # Final chunk - we've accumulated all content
                                break
                        except json.JSONDecodeError:
                            continue

                    content = full_content
                else:
                    # Single JSON response (non-streaming)
                    result = _normalize_llm_result(response.json())
                    content = result["choices"][0]["message"]["content"]
            else:
                result = _normalize_llm_result(response.json())
                content = result["choices"][0]["message"]["content"]

            # Cache successful responses and record request
            _cache_response(cache_key, content)
            if provider == "groq":
                groq_rate_limiter.record_request(estimated_tokens)
                logger.info(f"✅ API call successful, tokens estimated: {estimated_tokens}")
            return content
        except requests.exceptions.RequestException as e:
            last_err = e
            if attempt < 5:
                time.sleep(2.5 * (attempt + 1))  # Better backoff strategy

    # Ensure we always have a proper exception to raise
    if last_err is None:
        last_err = requests.exceptions.RequestException("Groq API call failed with unknown error")
    raise last_err


def process_with_brain(
    user_message: str,
    wa_id: str = "",
    history: List[Dict] = None,
) -> Dict:
    enabled_tools = get_tools()
    tool_schemas = tool_registry.get_openai_schemas(enabled_tools)

    retrieved_context, sources = _retrieve_context(user_message, wa_id=wa_id)

    escalation = get_escalation_rules()
    is_escalation = False
    if escalation:
        trigger_phrases = escalation.get("trigger_phrases", [])
        msg_lower = user_message.lower()
        for phrase in trigger_phrases:
            if phrase.lower() in msg_lower:
                is_escalation = True
                break

    system_prompt = _build_system_prompt(retrieved_context, wa_id=wa_id)

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(_build_chat_history(history))
    messages.append({"role": "user", "content": user_message})

    logger.info(f"Tool schemas count: {len(tool_schemas)}, tool_schemas: {tool_schemas[:2] if tool_schemas else 'None'}")

    tool_media_url = None
    answer = None
    max_tool_rounds = 2
    for round_num in range(max_tool_rounds):
        if not tool_schemas:
            try:
                answer = _call_groq_simple(messages)
            except Exception as e:
                logger.error(f"Groq simple call failed: {e}")
                answer = get_fallback_message()
            break

        try:
            result = _call_groq_with_tools(messages, tool_schemas, user_message)
            logger.info(f"Groq API result keys: {result.keys()}")
            logger.info(f"Grox API result: {result}")
        except Exception as e:
            logger.error(f"Groq tool call failed: {e}")
            answer = get_fallback_message()
            break

        choice = result["choices"][0]["message"]
        logger.info(f"Choice keys: {choice.keys()}")
        logger.info(f"Choice content: {choice.get('content', '')[:500]}")
        logger.info(f"Choice tool_calls: {choice.get('tool_calls')}")

        if choice.get("tool_calls"):
            # Proper structured tool calls (OpenAI format)
            messages.append(choice)
            seen_tool_calls = set()
            tool_call_count = 0
            for tool_call in choice["tool_calls"]:
                func_name = tool_call["function"]["name"]
                try:
                    func_args = json.loads(tool_call["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    func_args = {}

                call_key = (func_name, json.dumps(func_args, sort_keys=True))
                if call_key in seen_tool_calls:
                    logger.info(f"Skipping duplicate tool call: {func_name}({func_args})")
                    continue
                seen_tool_calls.add(call_key)

                tool_call_count += 1
                if tool_call_count > 10:
                    logger.info(f"Max tool calls (10) reached in round {round_num}")
                    break

                logger.info(f"Tool call: {func_name}({func_args})")
                tool_result = tool_registry.execute_tool(func_name, func_args)
                tool_result_str = str(tool_result)

                if not tool_media_url:
                    try:
                        result_data = json.loads(tool_result_str) if isinstance(tool_result_str, str) else tool_result
                        if isinstance(result_data, dict):
                            if result_data.get("found") and result_data.get("product", {}).get("media_url"):
                                tool_media_url = result_data["product"]["media_url"]
                            elif result_data.get("found") and result_data.get("products"):
                                for prod in result_data["products"]:
                                    if prod.get("media_url"):
                                        tool_media_url = prod["media_url"]
                                        break
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "content": tool_result_str,
                })
            continue
        elif choice.get("content"):
            # Check if content contains XML-style tool calls (fallback for models that don't support proper tool calling)
            content = choice.get("content", "")
            import re as _re
            # Pattern: <tool_name>{"arg": "value"}</tool_name>
            xml_tool_pattern = r'<(\w+)>(.*?)</\1>'
            matches = _re.findall(xml_tool_pattern, content, _re.DOTALL)
            if matches:
                logger.info(f"Found {len(matches)} XML-style tool calls in content, parsing...")
                tool_results = []
                for func_name, func_args_str in matches:
                    try:
                        func_args = json.loads(func_args_str) if func_args_str.strip() else {}
                        logger.info(f"Parsed XML tool call: {func_name}({func_args})")
                        tool_result = tool_registry.execute_tool(func_name, func_args)
                        tool_result_str = str(tool_result)
                        tool_results.append(f"{func_name} result: {tool_result_str}")

                        # Extract media_url from tool results
                        if not tool_media_url:
                            try:
                                result_data = json.loads(tool_result_str) if isinstance(tool_result_str, str) else tool_result
                                if isinstance(result_data, dict):
                                    if result_data.get("found") and result_data.get("product", {}).get("media_url"):
                                        tool_media_url = result_data["product"]["media_url"]
                                    elif result_data.get("found") and result_data.get("products"):
                                        for prod in result_data["products"]:
                                            if prod.get("media_url"):
                                                tool_media_url = prod["media_url"]
                                                break
                            except (json.JSONDecodeError, TypeError, AttributeError):
                                pass
                    except (json.JSONDecodeError, TypeError) as e:
                        logger.warning(f"Failed to parse XML tool call {func_name}: {e}")

                # Build a new prompt with tool results to get final answer
                if tool_results:
                    messages.append({"role": "assistant", "content": content})
                    tool_context = "\n\n".join(tool_results)
                    messages.append({
                        "role": "user",
                        "content": f"Based on these tool results, please answer the user's question in a friendly, conversational way. Include product details and prices when available.\n\nTool results:\n{tool_context}"
                    })
                    # Continue to next round to get final answer
                    continue

            # No tool calls found, treat as regular response
            answer = content
            break
        else:
            answer = choice.get("content", "")
            break
    else:
        # Loop exhausted after tool rounds. If the last response only requested
        # tools (no final text), make one more call so we return an actual answer.
        if not answer:
            try:
                logger.info("Tool rounds exhausted with no final text, requesting final answer...")
                final = _call_groq_with_tools(messages, tool_schemas, user_message)
                final_content = final["choices"][0]["message"].get("content")
                if final_content:
                    answer = final_content
                else:
                    logger.warning("Final answer call returned no content")
                    answer = get_fallback_message()
            except Exception as e:
                logger.error(f"Groq final answer call failed: {e}")
                answer = get_fallback_message()
        else:
            answer = choice.get("content", get_fallback_message())

    if not tool_media_url:
        logger.info(f"tool_media_url is None, checking sources. Sources count: {len(sources)}")
        for i, src in enumerate(sources):
            meta = src.get("metadata") or {}
            logger.info(f"Source {i}: source={src.get('source')}, has_metadata={bool(meta)}, metadata_media_url={meta.get('media_url', 'MISSING')}")
            if meta.get("media_url"):
                tool_media_url = meta["media_url"]
                logger.info(f"Found media_url from source {i}: {tool_media_url}")
                break
    else:
        logger.info(f"Using tool_media_url: {tool_media_url}")

    logger.info(f"Final media_url being returned: {tool_media_url}")

    return {
        "success": True,
        "answer": answer,
        "sources": sources,
        "confidence": "high" if sources else "low",
        "is_escalation": is_escalation,
        "tools_used": [],
        "media_url": tool_media_url,
    }


async def process_with_brain_async(
    user_message: str,
    wa_id: str = "",
    history: List[Dict] = None,
) -> Dict:
    return await asyncio.to_thread(process_with_brain, user_message, wa_id, history)


def extract_products_from_response(response_text: str, product_names: List[str]) -> List[str]:
    """Use LLM to identify which products from the list are mentioned in the response."""
    if not response_text or not product_names:
        return []

    # Get API configuration
    api_url, model, api_key, provider = _get_api_config()

    product_list = "\n".join(f"- {name}" for name in product_names)
    prompt = f"""You are a product matcher. Your job is to find EVERY product from the list that is mentioned, referenced, or discussed in the chatbot response.

RULES:
- Look for EXACT product names OR partial matches (e.g. "Peanut Millet Chikki" matches "Millet Chikki -15g & Peanut Millet Chikki")
- If a product name (or most of its words) appears in the response, include it
- Return the exact product names from the list, one per line
- If NO product from the list is mentioned at all, return "NONE"
- Do NOT add explanations

AVAILABLE PRODUCTS:
{product_list}

CHATBOT RESPONSE:
{response_text[:1500]}

PRODUCT NAMES FROM THE LIST THAT APPEAR IN THE RESPONSE (one per line, or "NONE"):"""

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "ngrok-skip-browser-warning": "true",
        }
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200,
            "temperature": 0.1,
        }
        response = requests.post(api_url, json=payload, headers=headers, timeout=15)
        response.raise_for_status()
        content = _normalize_llm_result(response.json())["choices"][0]["message"]["content"].strip()

        if content.upper() == "NONE" or not content:
            return []

        extracted = []
        for line in content.split("\n"):
            name = line.strip().lstrip("- ").strip("*").strip()
            if name and name.upper() != "NONE":
                extracted.append(name)
        return extracted[:3]
    except Exception as e:
        logger.debug(f"LLM product extraction failed: {e}")
        return []


def get_brain_stats() -> Dict:
    api_url, model, api_key, provider = _get_api_config()
    return {
        "provider": provider,
        "model": model,
        "api_url": api_url,
        "tools_registered": tool_registry.list_tools(),
        "tools_enabled": get_tools(),
        "response_settings": get_response_settings(),
    }


# ============================================
# OLLAMA DYNAMIC BUTTON PREDICTION
# ============================================

async def generate_ollama_dynamic_response(
    system_prompt: str,
    user_query: str,
    context: str = ""
) -> Dict:
    """
    Generate response with dynamic next-action buttons.
    Falls back through: Ollama → Groq → Mistral → keyword fallback.
    """

    json_prompt = f"""{system_prompt}

CRITICAL: You must respond ONLY in valid JSON format using this exact schema:
{{
  "answer": "Your text answer to the user goes here.",
  "next_actions": [
    {{"id": "short_snake_case_id", "title": "📍 Button Title 1"}},
    {{"id": "another_id", "title": "📍 Button Title 2"}}
  ]
}}

Rules for next_actions:
- Do NOT suggest generic actions like "Main Menu", "Help", or "Back".
- Suggest logical follow-ups based strictly on the topic.
- Keep button titles very short (max 20 chars) and start with 1 emoji.
- Use snake_case for IDs (e.g., "view_margins", "check_allergens").
- If no logical next action exists, return an empty list for next_actions.
- Maximum 3 next_actions allowed.

Context to use for your answer:
{context[:2000] if context else "No additional context provided."}

Remember: You must output ONLY valid JSON. No markdown, no code blocks, no explanations outside the JSON structure."""

    providers = [
        ("ollama", OLLAMA_API_URL, OLLAMA_MODEL, "no-key-needed", "ollama"),
        ("groq", GROQ_API_URL, GROQ_MODEL, GROQ_API_KEY, "openai"),
        ("mistral", MISTRAL_API_URL, MISTRAL_MODEL, MISTRAL_API_KEY, "openai"),
    ]

    for name, url, model, api_key, api_type in providers:
        if not api_key:
            continue
        try:
            raw_response = await _call_llm_provider(name, url, model, api_key, api_type, json_prompt, user_query)
            parsed = _parse_dynamic_json(raw_response, user_query)
            if parsed:
                logger.info(f"DYNAMIC_SUCCESS | provider={name} | answer_length={len(parsed.get('answer', ''))} | actions={len(parsed.get('next_actions', []))}")
                return parsed
        except Exception as e:
            logger.warning(f"DYNAMIC_FALLBACK | provider={name} failed: {e}")
            continue

    logger.warning("DYNAMIC_ALL_FAILED | all providers failed, using keyword fallback")
    return _fallback_ollama_response("", user_query)


def _log_gpu_stats():
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
            lines = result.stdout.strip().splitlines()
            for line in lines:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) == 4:
                    util, mem_used, mem_total, gpu_name = parts
                    logger.info(
                        f"GPU_STATS | name={gpu_name} | util={util}% | mem={mem_used}/{mem_total}MB"
                    )
                    return
        logger.warning("GPU_STATS | nvidia-smi returned no GPU data")
    except FileNotFoundError:
        logger.warning("GPU_STATS | nvidia-smi not found — GPU logging unavailable")
    except Exception as e:
        logger.warning(f"GPU_STATS | failed: {e}")


async def _call_llm_provider(name, url, model, api_key, api_type, system_prompt, user_query) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        if api_type == "ollama":
            _log_gpu_stats()
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
                    "num_ctx": 4096,
                    "num_predict": 1024,
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
            response = await client.post(url, json=payload, headers={"ngrok-skip-browser-warning": "true"}, timeout=30)
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
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()


def _parse_dynamic_json(raw_response: str, user_query: str) -> Dict | None:
    if not raw_response:
        return None

    try:
        parsed = json.loads(raw_response)
        if isinstance(parsed, dict) and "answer" in parsed:
            return _validate_dynamic_result(parsed, user_query)
    except json.JSONDecodeError:
        pass

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
                    return _validate_dynamic_result(parsed, user_query)
            except (json.JSONDecodeError, KeyError, TypeError):
                continue

    return None


def _validate_dynamic_result(parsed: dict, user_query: str) -> Dict:
    answer = parsed.get("answer", "")
    next_actions = parsed.get("next_actions", [])
    if not isinstance(next_actions, list):
        next_actions = []

    validated = []
    for action in next_actions:
        if isinstance(action, dict):
            aid = action.get("id", "")
            title = action.get("title", "")
            if aid and title:
                validated.append({"id": aid[:50], "title": title[:20]})

    return {"answer": answer[:4000], "next_actions": validated[:3]}


def _extract_json_with_regex(raw_response: str, user_query: str) -> Dict:
    """
    Try to extract JSON from response using regex patterns.

    This handles cases where Ollama wraps JSON in markdown code blocks or
    adds extra text around the JSON.
    """
    if not raw_response:
        return _fallback_ollama_response("", user_query)

    # Pattern 1: JSON in markdown code blocks
    json_pattern = r'```(?:json)?\s*\n?(\{.*?\})\s*```?'
    match = re.search(json_pattern, raw_response, re.DOTALL)

    # Pattern 2: Direct JSON object
    if not match:
        json_pattern = r'\{[^{}]*"answer"[^{}]*"next_actions"[^{}]*\[[^\]]*\][^{}]*\}'
        match = re.search(json_pattern, raw_response, re.DOTALL)

    # Pattern 3: Any JSON-like structure
    if not match:
        json_pattern = r'\{.*?\}'
        matches = re.findall(json_pattern, raw_response, re.DOTALL)
        if matches:
            # Try the largest match (most likely to be complete)
            match = max(matches, key=len, default=None)

    if match:
        try:
            json_str = match if isinstance(match, str) else match.group(1) if match.groups() else match.group(0)
            parsed = json.loads(json_str)

            answer = parsed.get("answer", "")
            next_actions = parsed.get("next_actions", [])

            validated_actions = []
            for action in next_actions if isinstance(next_actions, list) else []:
                if isinstance(action, dict) and action.get("id") and action.get("title"):
                    validated_actions.append({
                        "id": action.get("id", "")[:50],
                        "title": action.get("title", "")[:20]
                    })

            logger.info(f"OLLAMA_REGEX_SUCCESS | extracted from response with {len(validated_actions)} actions")
            return {
                "answer": answer[:4000] if answer else raw_response[:4000],
                "next_actions": validated_actions[:3]
            }
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"OLLAMA regex extraction failed: {e}")

    # If all extraction attempts fail, use fallback
    logger.warning("OLLAMA all JSON extraction methods failed, using fallback")
    return _fallback_ollama_response(raw_response, user_query)


def _fallback_ollama_response(raw_text: str, user_query: str) -> Dict:
    """
    Fallback response when Ollama JSON parsing fails.

    Returns the raw text as answer and empty next_actions.
    If no raw_text available, returns a generic helpful message.
    """
    if not raw_text:
        raw_text = "I apologize, but I'm having trouble generating a response right now. Please try again or contact our team for assistance."

    # Try to generate some basic next actions based on query keywords
    next_actions = []
    query_lower = user_query.lower()

    # FIX: Changed from "View Products" to better fallback options to prevent loops
    # When Ollama fails, users should get helpful navigation, not circular "View Products" buttons

    # Check if user is asking for help/assistance
    if any(word in query_lower for word in ["help", "assistance", "support", "can't", "unable", "problem"]):
        next_actions.append({"id": "talk_to_team", "title": "👥 Talk to Team"})

    # For product-related queries, offer main menu instead of view products
    if any(word in query_lower for word in ["product", "chikki", "item"]):
        next_actions.append({"id": "main_menu", "title": "🏠 Main Menu"})

    # For pricing queries, offer main menu
    if any(word in query_lower for word in ["price", "cost", "rate", "mrp"]):
        next_actions.append({"id": "main_menu", "title": "🏠 Main Menu"})

    # Default fallback option - always provide Main Menu
    if not next_actions:
        next_actions.append({"id": "main_menu", "title": "🏠 Main Menu"})
    if any(word in query_lower for word in ["allerg", "ingredient", "safe"]):
        next_actions.append({"id": "check_allergens", "title": "⚠️ Allergen Info"})
    if any(word in query_lower for word in ["order", "buy", "purchase"]):
        next_actions.append({"id": "place_order", "title": "🛒 Place Order"})

    logger.info(f"OLLAMA_FALLBACK | actions_generated={len(next_actions)}")

    return {
        "answer": raw_text[:4000],
        "next_actions": next_actions[:3]  # Max 3 actions
    }





