import logging
import os
import re
import subprocess
import requests
from routing.config import OLLAMA_API_URL, OLLAMA_MODEL, BRAND_NAME, BRAND_TAGLINE

logger = logging.getLogger("router")


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

FAQ_KEYWORDS = [
    # Catalogue / brochure
    "catalogue", "catalog", "brochure", "product list", "price list",
    # New releases / launches
    "new arrival", "new arrivals", "new launch", "new launches", "new product",
    "new release", "new releases", "latest release", "latest releases",
    "fresh drops", "recent additions", "latest product", "latest launch", "latest collection",
    # Policies (company / return / refund / cancellation / terms / privacy / shipping)
    "policy", "policies", "company policy",
    "return", "refund", "exchange", "replacement", "cancellation", "cancel",
    "terms", "terms and conditions", "conditions",
    "privacy", "shipping policy",
    # Payment / GST / EMI / digital payments
    "payment", "payment terms", "payment method", "pay", "paid", "gst", "invoice", "tax","debit card",
    "emi", "gpay", "google pay", "phonepe", "paytm", "wallet", "upi", "cod", "cash on delivery","credit card",
    "credit period", "credit terms", "advance payment", "bank transfer", "neft", "rtgs","amazon pay","neft",
    # MOQ / bulk / distributor / margin
    "moq", "minimum order", "minimum order quantity", "order quantity", "bulk order", "bulk",
    "wholesale", "distributor", "dealership", "franchise", "partner", "reseller", "bulk enquiry",
    "margin", "distributor margin", "dealer margin", "profit margin", "commission",
    # Customer care / contact
    "customer care", "contact", "helpline", "support", "phone", "phone number", "email",
    "complaint", "grievance", "feedback", "escalat", "dispute", "satisfied",
    # Delivery / dispatch / tracking
    "delivery", "delivery time", "delivery charge", "delivery date", "shipping", "ship",
    "dispatch", "dispatch time", "courier", "order status", "track", "tracking", "track order",
    # Penalties / charges
    "penalty", "penalties", "late fee", "late payment", "hidden charge", "hidden charges",
    "extra charge", "extra charges", "fine",
    # Warranty / guarantee
    "warranty", "guarantee",
    # Ordering / company / general
    "how to order", "place order", "buy", "purchase", "where can i buy",
    "about company", "about us", "contact us", "location", "address", "store", "retail",
    "loyalty", "reward", "referral", "subscription", "subscribe", "notify",
    "career", "job", "internship", "vacancy",
    "social media", "instagram", "facebook", "youtube", "twitter",
    # Health / allergy related
    "health", "healthy", "health condition", "health benefit", "health issue",
    "allerg", "allergy", "allergic", "allergen", "food allergy", "intolerance",
    "reaction", "sensitive", "sensitivity",
    "gluten", "lactose", "dairy", "nut free", "sugar free", "diabetic", "diabetes",
    "cholesterol", "blood pressure", "blood sugar", "heart", "digestion", "digestive",
    "immunity", "weight loss", "weight gain", "diet", "dietary", "calorie intake",
    "medical", "doctor", "nutritionist", "pregnant", "pregnancy", "breastfeeding",
    "children", "kids", "baby", "toddler", "elderly", "senior", "old age",
    # Preference / recommendation / suggestion
    "recommend", "recommendation", "suggest", "suggestion", "suggested",
    "prefer", "preference", "preferred", "advise", "advice", "choose", "choice",
    "help me choose", "help me select", "which is good", "which is better",
    "which one", "which should", "what should i", "good for", "best for",
    "safe for", "is it good", "should i eat", "should i take", "can i eat",
    "are there any good", "what to pick",
]

KB_KEYWORDS = [
    # Specification / features
    "specification", "spec", "specs", "feature", "features", "characteristic",
    "dimension", "size", "model", "variant", "variants", "flavour", "flavor",
    "detail", "description", "overview", "information about", "tell me about",
    # Ingredients / composition
    "ingredient", "ingredients", "composition", "component", "contains", "made of",
    "what is in", "consists of", "formula",
    # Nutrition
    "nutrition", "nutritional", "calorie", "calories", "protein", "carbohydrate",
    "fibre", "fiber", "fat", "vitamin", "mineral", "iron", "calcium", "magnesium",
    "sodium", "sugar content", "energy value",
    # Recipe / usage
    "recipe", "how to use", "usage", "application", "instruction", "directions",
    "how to make", "preparation", "guide",
    # Price / discount / offer
    "price", "cost", "rate", "pricing", "discount", "offer", "offers", "deal", "deals",
    "promotion", "scheme", "coupon",
    # Stock
    "stock", "availability", "in stock", "out of stock", "inventory", "restock", "restocked",
    # Pack
    "pack", "packing", "pack size", "packaging", "weight", "grams", "quantity",
    # Rating / reviews
    "rating", "ratings", "review", "reviews", "testimonial", "compare", "comparison",
    "best seller", "best",
    # Shelf life / storage / certifications
    "shelf life", "expiry", "expire", "expiration", "best before", "storage",
    "certified", "certification", "fssai", "gmp", "iso", "halal", "approval", "test report",
    #products
    "view products","show products","product list",
    "about company","about troogood","about us",
]


def keyword_classify(text):
    lower = text.lower()
    faq_matches = sum(1 for kw in FAQ_KEYWORDS if kw in lower)
    kb_matches = sum(1 for kw in KB_KEYWORDS if kw in lower)
    if faq_matches > kb_matches and faq_matches >= 1:
        return "faq"
    if kb_matches > faq_matches and kb_matches >= 1:
        return "kb"
    return ""

def _call_ollama(prompt: str, max_tokens: int, temperature: float, timeout: float = 30) -> str:
    _log_gpu_stats()
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "keep_alive": "30m",
            "think": False,
            "options": {
                "num_ctx": 256,
                "num_predict": max_tokens,
                "num_gpu": 99,
                "num_thread": 8,
                "num_batch": 256,
                "flash_attention": True,
                "temperature": temperature,
                "top_p": 0.9,
                "repeat_penalty": 1.0,
                "seed": 42,
            },
        }
        logger.info(
            f"LLM_CALL | model={OLLAMA_MODEL} | max_tokens={max_tokens} | temp={temperature} | "
            f"gpu={payload['options']['num_gpu']} | ctx={payload['options']['num_ctx']}"
        )
        resp = requests.post(
            OLLAMA_API_URL,
            json=payload,
            headers={"Content-Type": "application/json", "ngrok-skip-browser-warning": "true"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "").strip()
    except Exception as e:
        logger.error(f"Ollama API call failed: {e}")
        return ""
    
# ─────────────────────────────────────────────────────────────
# 2. LLM-POWERED GREETING GENERATOR
# ─────────────────────────────────────────────────────────────
def generate_greeting(user_message: str) -> str:
    """
    Uses Ollama (qwen3:8b) locally to generate a warm, context-aware greeting response
    on behalf of {BRAND_NAME}'s virtual assistant.
    Falls back to a safe default string if the API call fails.
    """
    prompt = (
        f"You are the official WhatsApp assistant for {BRAND_NAME}, {BRAND_TAGLINE}.\n\n"
        "A customer just sent this opening message:\n"
        f'"{user_message}"\n\n'
        "Write a short, warm, engaging reply (2-3 sentences max) in the style of top "
        "consumer brands on WhatsApp (Zomato/Dunzo tone):\n"
        "- Greet them personally and enthusiastically (1 emoji max).\n"
        f"- Tease what they can do: discover products, check offers, track orders, "
        f"or ask anything about {BRAND_NAME}.\n"
        "- End with an inviting question so they reply (e.g. 'What are you in the mood "
        "for today?' or 'Curious about our latest treats? 😉').\n"
        "- No bullet points, no lists, no links. Just natural chat."
    )
    result = _call_ollama(prompt, max_tokens=256, temperature=0.2)
    if result:
        logger.info(f"LLM greeting generated: {result}")
        return result

    # Graceful fallback so the bot never goes silent — still engaging
    logger.warning("Using fallback greeting.")
    return (
        f"Hey there! 👋 Welcome to {BRAND_NAME} — {BRAND_TAGLINE.lower()}. "
        "Ask me anything: products, offers, orders, policies… "
        "What would you like to explore today? 😊"
    )


EXACT_MATCHES = {
    # Greetings / small talk
    "hi": "greeting",
    "hello": "greeting",
    "hey": "greeting",
    "hii": "greeting",
    "hiii": "greeting",
    "good morning": "greeting",
    "good afternoon": "greeting",
    "good evening": "greeting",
    "bye": "greeting",
    "thanks": "greeting",
    "thank you": "greeting",
    "okay": "greeting",
    "sure": "greeting",
    "yes": "greeting",
    "no": "greeting",
    "tysm": "greeting",
    "thx": "greeting",
    "howdy": "greeting",
    "take care": "greeting",
    "talk later": "greeting",
    "see you": "greeting",
    # FAQ — brochure & new releases
    "catalogue": "faq",
    "catalog": "faq",
    "brochure": "faq",
    "new arrival": "faq",
    "new arrivals": "faq",
    "new release": "faq",
    "new releases": "faq",
    "new launch": "faq",
    "new launches": "faq",
    # FAQ — policies
    "company policy": "faq",
    "return policy": "faq",
    "what is the return policy": "faq",
    "refund policy": "faq",
    "cancellation policy": "faq",
    "exchange policy": "faq",
    "replacement policy": "faq",
    "terms and conditions": "faq",
    "terms & conditions": "faq",
    "privacy policy": "faq",
    "shipping policy": "faq",
    "refund": "faq",
    "return": "faq",
    "cancellation": "faq",
    # FAQ — payment / GST / EMI
    "payment terms": "faq",
    "what are the payment terms": "faq",
    "how to pay": "faq",
    "gst details": "faq",
    "gst": "faq",
    "invoice": "faq",
    "emi": "faq",
    "credit period": "faq",
    # FAQ — MOQ / bulk / distributor / margin
    "moq": "faq",
    "what is the moq": "faq",
    "what is moq": "faq",
    "minimum order quantity": "faq",
    "minimum quantity": "faq",
    "bulk order": "faq",
    "distributor margin": "faq",
    "margin": "faq",
    "how to become a distributor": "faq",
    "become a distributor": "faq",
    # FAQ — customer care / delivery / penalties
    "customer care": "faq",
    "contact": "faq",
    "phone number": "faq",
    "give me contact": "faq",
    "delivery time": "faq",
    "what is the delivery time": "faq",
    "dispatch time": "faq",
    "where can i buy": "faq",
    "how to order": "faq",
    "penalty": "faq",
    "penalties": "faq",
    "late fee": "faq",
    # KB — product details
    "menu": "kb",
    "ingredients": "kb",
    "what are the ingredients": "kb",
    "ingredient": "kb",
    "specifications": "kb",
    "specification": "kb",
    "product specification": "kb",
    "feature": "kb",
    "features": "kb",
    "recipe": "kb",
    "how to use": "kb",
    "nutrition": "kb",
    "nutrition facts": "kb",
    "protein": "kb",
    "calories": "kb",
    "price": "kb",
    "cost": "kb",
    "pricing": "kb",
    "discount": "kb",
    "do you have discount": "kb",
    "offer": "kb",
    "deals": "kb",
    "stock": "kb",
    "in stock": "kb",
    "availability": "kb",
    "pack": "kb",
    "pack size": "kb",
    "packing": "kb",
    "rating": "kb",
    "ratings": "kb",
    "review": "kb",
    "reviews": "kb",
    "shelf life": "kb",
    "how to store": "kb",
    "brand story": "kb",
    "about company": "kb",
    "view products": "kb",
    "tell me about": "kb",
    "explain": "kb",
    "about troogood": "kb",
    "about company": "kb",
}


def classify_and_route(text: str) -> str:
    prompt = (
        f'Classify this WhatsApp message into ONE word: greeting, faq, or kb.\n'
        f'greeting = hi/hello/thanks/bye/small talk (no real question)\n'
        f'faq = policies, payment, MOQ, delivery, contact, recommendations, health/allergy\n'
        f'kb = specific product specs, ingredients, price, stock, reviews\n\n'
        f'Message: "{text}"\n\nReply with ONE word.'
    )
    result = _call_ollama(prompt, max_tokens=3, temperature=0, timeout=15)
    result = result.lower().strip().strip(".")
    return result if result in ("greeting", "faq", "kb") else "kb"


def profile_for(tenant_id=None, wa_id: str = ""):
    """The tenant profile guiding classification, or None.

    Never raises: classification must keep working on an unmigrated database or
    a missing package, in which case the legacy behaviour applies unchanged.
    """
    try:
        import sys as _sys
        from pathlib import Path as _Path

        root = str(_Path(__file__).resolve().parents[1])
        if root not in _sys.path:
            _sys.path.insert(0, root)

        from shared.tenancy import loader
        from shared.tenancy.resolver import resolve_tenant_for_user

        return loader.get_tenant_profile(tenant_id or resolve_tenant_for_user(wa_id))
    except Exception as exc:  # pragma: no cover - defensive by design
        logger.debug("classifier: profile unavailable (%s)", exc)
        return None


# Which feature flag each routing target needs. 'kb' answers from the tenant's
# own indexed documents, so routing there without the feature is how one tenant
# ends up quoting another's catalogue.
ROUTE_GATES = {"kb": "kb", "faq": "faq"}


def apply_route_gates(intent: str, profile) -> str:
    """Constrain a routing decision to what this tenant actually supports.

    The return vocabulary stays exactly ``greeting | faq | kb`` because the FSM
    dispatches on those literals. Gating maps a target the tenant has switched
    off onto one it can serve, rather than introducing a new label that no
    downstream branch handles.
    """
    if profile is None:
        return intent

    if intent == "greeting":
        return intent

    needed = ROUTE_GATES.get(intent)
    if not needed or profile.feature_on(needed):
        return intent

    # Preferred fallback is faq; if even that is off, kb may still be on.
    if profile.feature_on("faq"):
        logger.info("routing %s->faq: %s feature off for %s",
                    intent, needed, profile.tenant_id)
        return "faq"
    if profile.feature_on("kb"):
        logger.info("routing %s->kb: %s feature off for %s",
                    intent, needed, profile.tenant_id)
        return "kb"

    # Nothing is on. Hand off rather than answer from an arbitrary corpus.
    logger.info("routing %s->greeting: no faq/kb for %s", intent, profile.tenant_id)
    return "greeting"


GREETING_TOKENS = {
    "hi", "hey", "hello", "helo", "hlo", "hallo", "hullo", "hiya", "hie", "hy",
    "hai", "yo", "howdy", "hola", "namaste", "gm", "morning", "evening",
    "good morning", "good afternoon", "good evening", "good night",
    "bye", "goodbye", "thanks", "thank you", "thankyou", "tysm", "thx", "ty",
    "ok", "okay", "okey", "k", "sure", "yes", "no", "cool", "nice", "great",
}


def _collapse_repeats(text: str) -> str:
    return re.sub(r"(.)\1{2,}", r"\1", text)


def is_meaningless_or_greeting(text) -> bool:
    """True when a message carries no answerable query and should show the menu.

    Covers greetings — including typos and letter-spam like ``hie``/``hyyyy`` —
    and keyboard-mash noise like ``jsdbkop``. Real queries are claimed by the
    exact/keyword maps *before* this runs, so anything reaching here that reads
    as social noise is best answered by presenting the menu.
    """
    if not text:
        return True
    lower = text.strip().lower()
    if not lower:
        return True

    cleaned = _collapse_repeats(re.sub(r"[^a-z\s]", "", lower)).strip()
    if not cleaned:
        # Emoji / punctuation / digits only.
        return True
    if cleaned in GREETING_TOKENS:
        return True

    words = cleaned.split()
    # Single greeting-ish spelling: hi, hie, hy, heyy->hey, helo, hii...
    if len(words) == 1 and re.fullmatch(r"h[ieya]+(llo|lo|e|y)?", words[0]):
        return True

    for w in words:
        # No vowel at all ('hmm', 'brb') or a long consonant run ('jsdbkop').
        if len(w) >= 3 and not re.search(r"[aeiouy]", w):
            return True
        if re.search(r"[bcdfghjklmnpqrstvwxyz]{5,}", w):
            return True
    return False


def classify_query(text, tenant_id=None, wa_id: str = ""):
    if not text or not text.strip():
        return "greeting"
    text = text.strip().rstrip("?").strip()
    lower = text.lower().strip()
    exact = EXACT_MATCHES.get(lower)
    if exact:
        return exact
    kw = keyword_classify(text)
    if kw:
        return apply_route_gates(kw, profile_for(tenant_id, wa_id))
    if is_meaningless_or_greeting(text):
        return "greeting"
    return apply_route_gates(classify_and_route(text), profile_for(tenant_id, wa_id))
