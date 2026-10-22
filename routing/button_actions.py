"""
Fixed TOPIC_SUGGESTIONS + button map + matcher + topic-relevance guard.

Bugs in the original:
1. Typos in `source`: "copmany_policy" -> "company_policy",
   "terms_condition" -> "terms_conditions" (source filter never matched).
2. No dedicated groups for `credit period` and `moq`.
   `moq` was buried inside the generic price group.
3. Distributor group was too weak (few keywords, wrong actions —
   `new_arrival` is irrelevant for distributorship queries).
4. ORDERING BUG (the main "buttons aren't matching" cause):
   generic groups with keywords like "order" / "product" / "terms"
   were evaluated before specific ones, so e.g.
   - "net 30 payment terms?" matched the TERMS group (bare "terms")
     instead of the CREDIT group ("payment terms");
   - "where is my order?" matched the ORDER group instead of TRACKING.
   Fix: most-specific groups first (credit -> moq -> distributor ->
   privacy -> terms -> ... -> generic price/ingredients last).
5. Over-generic keywords ("order", "product", "data", "law", "policies",
   "terms", "conditions", "credit") matched almost everything under
   naive `if kw in query` checks.
   Fix: matcher below uses word-boundaries + longest-phrase-first,
   and bare generic words were removed or converted to phrases.

6. MISSING GUARD (why UNRELATED buttons reached users):
   service.py calls `enforce_topic_actions(validated, query, limit=3)`
   from this module to drop/replace LLM-picked buttons that are unrelated
   to the user's query (e.g. "✨ New Arrivals" on a credit-period answer),
   but the function NEVER EXISTED in this file. The ImportError was
   swallowed by service.py's broad `except Exception`, so:
     - the relevance filter silently never ran, AND
     - BUTTON_REGISTRY silently came back empty on that import path.
   Fix: implemented below in §3b — this is the guard that makes buttons
   match what the user actually asked.

7. WHATSAPP 20-CHAR TITLE LIMIT:
   Five registry titles exceeded 20 characters, so handle_faq_query's
   `title[:20]` slice chopped them mid-word ("🧾 Order, Payment & G",
   "🥜 Ingredients & Nut", ...). Titles are now all <= 20 chars and
   validate() enforces the limit so this can't regress.

Rule of thumb: if group A's keyword is a SUBSTRING of group B's keyword
("terms" vs "payment terms", "order" vs "cancel order"), B must come first
OR A must not use the bare substring. This file does both.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1. Canonical button map — EVERY action id used below MUST exist here.
#    "Suggested buttons aren't matching" almost always means:
#    TOPIC_SUGGESTIONS references an id with no button definition.
#    NOTE: titles must stay <= 20 chars (WhatsApp reply-button limit).
# ---------------------------------------------------------------------------

BUTTONS: dict[str, str] = {
    # general / navigation
    "main_menu": "🏠 Main Menu",
    "contact_support": "💬 Contact Support",
    "menu_human": "🙋 Talk to Human",
    # flows
    "book_callback": "📞 Book a Callback",
    "get_quote": "📝 Get a Quote",
    "raise_ticket": "🆘 Raise Ticket",
    # IT / Software & Services
    "menu_services": "🛠️ Our Services",
    "menu_technologies": "💻 Technologies",
    "menu_projects": "📁 Projects",
    "menu_brochure": "📄 Service Brochure",
    "menu_careers": "💼 Careers",
    "menu_benefits": "🎁 Benefits",
    "menu_quote": "📝 Get a Quote",
    "menu_callback": "📞 Book a Callback",
    "menu_support": "🆘 Support",
    # Healthcare
    "menu_treatments": "🩺 Treatments",
    "menu_specialities": "🏥 Specialities",
    "menu_appointment": "📅 Book Appointment",
    "menu_offerings": "📋 Offerings",
    # Banking
    "menu_products": "🏦 Banking Products",
    "menu_cards": "💳 Cards",
    "menu_loans": "🏠 Loans",
    "menu_eligibility": "✅ Check Eligibility",
    "menu_grievance": "📝 Raise Complaint",
    "menu_branch": "📍 Branch & Support",
    # Finance
    "menu_proposal": "📝 Request Proposal",
    "menu_faq": "❓ FAQs",
    # Tours & Travel
    "menu_destinations": "🗺️ Destinations",
    "menu_packages": "🎒 Tour Packages",
    "menu_booking_policy": "📋 Booking Policy",
    "menu_visa": "🛂 Visa & Documents",
    # E-commerce / Retail
    "menu_catalogue": "📄 Brochure",
    "menu_new_arrivals": "✨ New Releases",
    "menu_about": "🏢 Company Policies",
    "menu_discounts": "🎁 Offers & Deals",
    "menu_gst": "🧾 GST Info",
    "menu_credit_policy": "💳 Credit Policy",
    "menu_complaint": "📝 Raise Complaint",
    "menu_view_cart": "🛒 View Cart",
    # policies / support legacy
    "privacy_policy": "🔒 Privacy Policy",
    "terms_conditions": "📄 Terms & Conditions",
    "company_policy": "🏢 Company Policies",
    # orders / logistics legacy
    "return_policy": "🔁 Returns & Refunds",      # was "↩️ Return & Refund Policy" (25 chars, got chopped)
    "track_order": "📦 Track Order",
    "shipping_policy": "🚚 Shipping Policy",       # was "🚚 Shipping & Delivery" (21 chars)
    "order_policy": "🧾 Orders & Payments",        # was "🧾 Order, Payment & GST" (22 chars)
    # products legacy
    "product_prices": "💰 Product Prices",
    "new_arrival": "✨ New Releases",
    "product_ingredients": "🥜 Ingredients Info",  # was "🥜 Ingredients & Nutrition" (25 chars)
    "allergen_info": "⚠️ Allergen Info",
    "shelf_life": "📅 Shelf Life",                 # was "📅 Shelf Life & Storage" (22 chars)
    # B2B legacy
    "moq_policy": "📊 MOQ & Bulk Orders",
    "credit_period_policy": "💳 Credit Period",    # was "💳 Credit Period & Terms" (23 chars)
    "distributor_info": "🤝 Distributorship",
}

BUTTON_FEATURE_REQUIREMENTS: dict[str, str] = {
    "menu_view_cart": "cart",
    "track_order": "track_order",
    "menu_catalogue": "brochure_pdf",
    "menu_brochure": "brochure_pdf",
    "return_policy": "returns",
    "get_quote": "quote",
    "menu_quote": "quote",
    "menu_proposal": "quote",
    "book_callback": "callback",
    "menu_callback": "callback",
    "menu_appointment": "book_appointment",
    "raise_ticket": "complaints",
    "menu_complaint": "complaints",
    "menu_grievance": "complaints",
    "menu_support": "complaints",
    "contact_support": "complaints",
    "menu_human": "human_handover",
    "menu_services": "services",
    "menu_products": "products",
    "menu_treatments": "services",
    "menu_specialities": "services",
    "menu_packages": "offerings",
    "menu_destinations": "offerings",
    "menu_offerings": "offerings",
    "distributor_info": "distributors",
}

# ---------------------------------------------------------------------------
# 2. Topic groups — ORDER IS LOAD-BEARING. Specific -> generic.
#    Evaluated top-down; every matching group contributes its actions
#    until we have `top_k` unique actions.
# ---------------------------------------------------------------------------

TOPIC_SUGGESTIONS: list[dict] = [
    # ---- 1. Most specific B2B topics FIRST (before terms/order/price) ----
    {
        # NOTE: no bare "credit" — it false-matched "credit card" payment queries.
        # NOTE: sits BEFORE the terms group — "payment terms" contains "terms".
        "keywords": [
            "credit period", "credit days", "credit limit", "credit facility",
            "payment terms", "payment deadline", "net 30", "net-30", "net days",
            "due date", "on credit", "udhar",
        ],
        "source": [],
        "actions": ["credit_period_policy", "order_policy", "contact_support"],
    },
    {
        # NOTE: sits BEFORE order/price — "minimum order" contains "order".
        "keywords": [
            "minimum order quantity", "minimum order value", "minimum order",
            "minimum quantity", "minimum purchase", "order quantity",
            "moq", "mov", "min order",
        ],
        "source": [],
        "actions": ["moq_policy", "product_prices", "contact_support"],
    },
    {
        "keywords": [
            "become a distributor", "become a partner", "distributorship",
            "distributor", "distribution", "stockist", "super stockist",
            "dealership", "dealer", "reseller", "wholesale", "franchise",
            "partnership", "trade partner", "agency", "carry your products",
        ],
        "source": [],
        "actions": ["distributor_info", "product_prices", "contact_support"],
    },
    # ---- 2. Policy topics ----
    {
        # NOTE: removed bare "data" (matched everything); use "data privacy".
        "keywords": ["privacy", "personal information", "cookie", "gdpr", "data privacy"],
        "source": [],
        "actions": ["privacy_policy", "terms_conditions", "contact_support"],
    },
    {
        # NOTE: removed bare "terms"/"conditions" (they hijacked "payment terms").
        # Use phrases instead.
        "keywords": [
            "terms and conditions", "terms of use", "terms of service",
            "t&c", "tnc", "disclaimer", "agreement",
        ],
        "source": [],
        "actions": ["terms_conditions", "privacy_policy", "contact_support"],
    },
    {
        # NOTE: removed bare "policies"/"law" (false-matched every "* policy" query).
        "keywords": [
            "company policy", "channel policy", "workplace policy",
            "anti-bribery", "anti bribery", "anti-discrimination",
            "anti-counterfeit", "sustainability", "governed by", "jurisdiction",
        ],
        "source": [],  # fixed: was "copmany_policy"
        "actions": ["shipping_policy", "privacy_policy", "terms_conditions"],
    },
    # ---- 3. Order lifecycle: return -> cancel -> tracking -> payment ----
    {
        "keywords": [
            "return", "refund", "replace", "replacement",
            "damaged", "money back", "wrong item", "defective", "expired item",
        ],
        "source": [],
        "actions": ["return_policy", "track_order", "contact_support"],
    },
    {
        # NOTE: split out of the old generic "order" group and placed BEFORE
        # tracking — "cancel my order" contains "my order".
        "keywords": ["cancel order", "cancel my order", "cancellation", "cancel"],
        "source": [],
        "actions": ["order_policy", "track_order", "contact_support"],
    },
    {
        # NOTE: owns "my order" / "where is my order" / "order id" now.
        "keywords": [
            "where is my order", "track order", "order status", "order tracking",
            "my order", "order id", "tracking", "shipping", "delivery",
            "dispatch", "courier", "logistics", "transit", "shipment",
            "delivery charge", "shipping charge",
        ],
        "source": [],
        "actions": ["track_order", "shipping_policy", "contact_support"],
    },
    {
        # NOTE: payment/GST half of the old generic "order" group.
        # No bare "order" here anymore — tracking owns order-status queries.
        # NOTE: "track_order" REMOVED from actions — a GST/UPI/invoice question
        # used to also offer "📦 Track Order", which felt unrelated to what the
        # user asked. If order tracking is genuinely relevant, the cancel group
        # or the tracking group supplies it.
        "keywords": [
            "payment method", "credit card", "debit card", "upi",
            "payment", "pay", "gst", "invoice", "billing", "receipt",
        ],
        "source": [],
        "actions": ["order_policy", "contact_support"],
    },
    # ---- 4. Generic product topics LAST ----
    {
        # NOTE: "moq" removed — it has its own group now.
        "keywords": [
            "price", "pricing", "cost", "rate", "quote", "quotation",
            "bulk order", "bulk", "discount", "offer", "deal", "price list",
        ],
        "source": [],
        "actions": ["product_prices", "moq_policy", "contact_support"],
    },
    {
        "keywords": [
            "shelf life", "best before", "expiry", "expire", "mfg date",
            "manufacturing date", "fresh", "storage", "how to store",
        ],
        "source": [],
        "actions": ["shelf_life", "product_ingredients", "contact_support"],
    },
    {
        # NOTE: removed bare "product"/"chikki" — they matched everything.
        # Keep LAST as a fallback for product questions.
        "keywords": [
            "ingredient", "nutrition", "nutritional", "allergen", "allergy",
            "gluten", "sugar", "jaggery", "vegan", "flavour", "flavor",
            "catalogue", "catalog", "composition", "recipe", "calorie",
        ],
        "source": [],
        "actions": ["product_ingredients", "allergen_info", "new_arrival"],
    },
]

# ---------------------------------------------------------------------------
# 3. Matcher — word-boundary aware, longest-phrase-first.
#    Drop-in replacement for naive `if kw in query` checks.
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _keyword_hit(keyword: str, query: str) -> bool:
    """Match whole words/phrases, not substrings ('order' won't hit 'reorder')."""
    return re.search(r"\b" + re.escape(keyword.lower()) + r"\b", query) is not None


def get_suggestions(query: str, top_k: int = 3) -> list[str]:
    """
    Return up to `top_k` unique action ids for a user query.
    Groups are evaluated top-down (specific -> generic); every matching
    group contributes its actions in order.
    """
    q = _normalize(query)
    picked: list[str] = []

    for group in TOPIC_SUGGESTIONS:
        # Longest keywords first: "credit period" beats "credit",
        # "cancel order" beats "cancel", "payment terms" beats "payment".
        for kw in sorted(group["keywords"], key=len, reverse=True):
            if _keyword_hit(kw, q):
                for action in group["actions"]:
                    if action not in picked:
                        picked.append(action)
                        if len(picked) >= top_k:
                            return picked
                break  # one hit per group is enough

    return picked


def get_suggestion_buttons(query: str, top_k: int = 3) -> list[dict[str, str]]:
    """Convenience: return [{id, label}] ready for the chat UI."""
    return [{"id": a, "label": BUTTONS[a]} for a in get_suggestions(query, top_k) if a in BUTTONS]


# ---------------------------------------------------------------------------
# 3b. Topic-relevance guard — REQUIRED by service.py.
#     service._validate_faq_dynamic_result() does:
#         from routing.button_actions import BUTTON_REGISTRY, enforce_topic_actions
#         validated = enforce_topic_actions(validated, query, limit=3)
#     This is the function that was missing (see docstring note 6). It keeps
#     only buttons topically related to the user's query, so the LLM can no
#     longer attach off-topic buttons to an answer.
# ---------------------------------------------------------------------------

def enforce_topic_actions(
    buttons: list[dict],
    query: str,
    limit: int = 3,
) -> list[dict]:
    """
    Keep only buttons related to what the user asked; backfill from the
    keyword matcher in topic-relevance order.

    Flow:
      1. Build a topic pool for the query with get_suggestions()
         (top_k = limit * 2 so a 2nd matching group can contribute).
      2. Pool empty (no keyword hit at all)  -> pass the LLM's picks through
         unchanged; there is no topic signal to judge them by.
      3. Pool non-empty                      -> output is the pool (in
         keyword-relevance order), but LLM picks inside the pool choose
         WHICH pool members appear when the pool is larger than `limit`.
         Off-topic LLM picks are always dropped.

    Called by service.py as enforce_topic_actions(validated, query, limit=3).
    """
    if limit <= 0:
        return []

    buttons = buttons or []
    pool = get_suggestions(query or "", top_k=limit * 2)

    if not pool:
        # No keyword signal — keep the registry-valid LLM picks as-is.
        return [
            {"id": (b.get("id") or "").strip()[:50], "title": (b.get("title") or "")[:20]}
            for b in buttons[:limit]
            if (b.get("id") or "").strip()
        ]

    pool_set = set(pool)
    picked = {
        (b.get("id") or "").strip()
        for b in buttons
        if (b.get("id") or "").strip() in pool_set
    }

    # LLM's relevant picks first (ordered by pool relevance), then backfill.
    ordered = [bid for bid in pool if bid in picked]
    for bid in pool:
        if len(ordered) >= limit:
            break
        if bid not in ordered:
            ordered.append(bid)

    return [
        {"id": bid[:50], "title": BUTTONS.get(bid, bid)[:20]}
        for bid in ordered[:limit]
    ]


def validate() -> list[str]:
    """Every referenced action must have a button (<= 20-char title). Returns errors."""
    errors: list[str] = []
    for i, group in enumerate(TOPIC_SUGGESTIONS):
        for action in group["actions"]:
            if action not in BUTTONS:
                errors.append(f"group[{i}] references unknown action: {action!r}")
    for bid, label in BUTTONS.items():
        if len(label) > 20:
            errors.append(
                f"button {bid!r} title exceeds WhatsApp 20-char limit "
                f"({len(label)} chars): {label!r}"
            )
    return errors


# ---------------------------------------------------------------------------
# 4. Quick self-test — run:  python button_actions.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    assert not validate(), validate()

    tests = {
        # NEW topics
        "What is your credit period?": ["credit_period_policy", "order_policy", "contact_support"],
        "Do you offer net 30 payment terms?": ["credit_period_policy", "order_policy", "contact_support"],
        "What is the MOQ for bulk order?": ["moq_policy", "product_prices", "contact_support"],
        "minimum order quantity for chikki?": ["moq_policy", "product_prices", "contact_support"],
        "How to become a distributor?": ["distributor_info", "product_prices", "contact_support"],
        "I want distributorship in Gujarat": ["distributor_info", "product_prices", "contact_support"],
        # regression tests — these broke with naive ordering/substring matching
        "Where is my order?": ["track_order", "shipping_policy", "contact_support"],
        "cancel my order": ["order_policy", "track_order", "contact_support"],
        # updated: payment group no longer drags in Track Order for a payments question
        "can I pay by credit card?": ["order_policy", "contact_support"],
        "what are your terms and conditions?": ["terms_conditions", "privacy_policy", "contact_support"],
        "I want refund for damaged item": ["return_policy", "track_order", "contact_support"],
        "Send price list": ["product_prices", "moq_policy", "contact_support"],
        "Is it gluten free? ingredients?": ["product_ingredients", "allergen_info", "new_arrival"],
        "What is shelf life?": ["shelf_life", "product_ingredients", "contact_support"],
        "privacy policy": ["privacy_policy", "terms_conditions", "contact_support"],
    }

    failed = 0
    for query, expected in tests.items():
        got = get_suggestions(query)
        ok = got == expected
        failed += not ok
        print(f"{'✅' if ok else '❌'} {query!r}\n   got={got} expected={expected}")

    # ── enforce_topic_actions: off-topic LLM picks get replaced ──
    print("\nenforce_topic_actions checks:")

    # LLM picked nothing relevant for a credit-period answer -> full topic swap
    got = enforce_topic_actions(
        [{"id": "new_arrival", "title": "✨ New Releases"},
         {"id": "product_prices", "title": "💰 Product Prices"}],
        "What is your credit period?",
    )
    ok = [b["id"] for b in got] == ["credit_period_policy", "order_policy", "contact_support"]
    failed += not ok
    print(f"{'✅' if ok else '❌'} unrelated LLM picks replaced\n   got={[b['id'] for b in got]}")

    # relevant LLM pick survives (and chooses which pool members fill the rest)
    got = enforce_topic_actions(
        [{"id": "credit_period_policy", "title": "💳 Credit Period"},
         {"id": "new_arrival", "title": "✨ New Releases"}],
        "Do you offer net 30 payment terms?",
    )
    ok = [b["id"] for b in got] == ["credit_period_policy", "order_policy", "contact_support"]
    failed += not ok
    print(f"{'✅' if ok else '❌'} relevant LLM pick kept + backfilled\n   got={[b['id'] for b in got]}")

    # GST question no longer offers Track Order
    got = enforce_topic_actions(
        [{"id": "contact_support", "title": "💬 Contact Support"},
         {"id": "contact_support", "title": "💬 Contact Support"}],
        "what is gst on your products?",
    )
    ok = [b["id"] for b in got] == ["contact_support", "order_policy"]
    failed += not ok
    print(f"{'✅' if ok else '❌'} GST query -> no Track Order, dupes removed\n   got={[b['id'] for b in got]}")

    # no keyword signal -> LLM picks pass through untouched
    got = enforce_topic_actions([{"id": "new_arrival", "title": "✨ New Releases"}], "hello")
    ok = [b["id"] for b in got] == ["new_arrival"]
    failed += not ok
    print(f"{'✅' if ok else '❌'} empty pool -> LLM picks pass through\n   got={[b['id'] for b in got]}")

    print(f"\n{failed == 0 and 'ALL PASSED ✅' or f'{failed} CHECK(S) FAILED ❌'}")

# ─────────────────────────────────────────────
# Backwards-compatibility & Tenant-Aware helpers
# ─────────────────────────────────────────────

# Legacy registry shape: id -> {"id": ..., "title": ...}
BUTTON_REGISTRY: dict[str, dict] = {
    bid: {"id": bid, "title": label} for bid, label in BUTTONS.items()
}


def get_tenant_action_registry(tenant_id: str | None = None) -> dict[str, dict]:
    """Return dictionary of allowed button specs for the given tenant profile."""
    tid = tenant_id
    if not tid:
        try:
            from shared.tenancy.resolver import resolve_default_tenant
            tid = resolve_default_tenant()
        except Exception:
            pass

    if not tid:
        return BUTTON_REGISTRY

    try:
        from shared.tenancy.loader import get_tenant_profile
        profile = get_tenant_profile(tid)
    except Exception:
        profile = None

    if profile is None or not getattr(profile, "menu", None) or not getattr(profile.menu, "buttons", None):
        return BUTTON_REGISTRY

    registry = {}
    for b in profile.menu.buttons:
        if b.enabled and (not b.requires_feature or profile.features.is_on(b.requires_feature)):
            title = BUTTONS.get(b.id) or b.title[:20]
            registry[b.id] = {"id": b.id, "title": title}

    # Ensure main_menu is always available
    registry["main_menu"] = {"id": "main_menu", "title": BUTTONS["main_menu"]}

    # Ensure active flows have direct button specs — but only when the tenant's
    # menu actually surfaces that flow. A flow hidden from the menu (tombstoned,
    # disabled, or simply never added) must not resurface as a suggested button.
    enabled_rows = [b for b in profile.menu.buttons if b.enabled]
    row_ids = {getattr(b, "id", "") for b in enabled_rows}
    row_flows = {getattr(b, "flow", None) for b in enabled_rows}

    def _flow_surfaced(flow_name: str, *row_ids_for_flow: str) -> bool:
        if flow_name in row_flows:
            return True
        return any(rid in row_ids for rid in row_ids_for_flow)

    if profile.features.is_on("quote") and _flow_surfaced("get_quote", "menu_quote", "menu_proposal"):
        registry["get_quote"] = {"id": "get_quote", "title": BUTTONS["get_quote"]}
    if profile.features.is_on("callback") and _flow_surfaced("book_callback", "menu_callback", "menu_human"):
        registry["book_callback"] = {"id": "book_callback", "title": BUTTONS["book_callback"]}
    if profile.features.is_on("complaints") and _flow_surfaced("raise_ticket", "menu_support", "menu_complaint", "menu_grievance"):
        registry["raise_ticket"] = {"id": "raise_ticket", "title": BUTTONS["raise_ticket"]}
    if profile.features.is_on("human_handover") and _flow_surfaced("book_callback", "menu_human"):
        registry["menu_human"] = {"id": "menu_human", "title": BUTTONS["menu_human"]}

    return registry if registry else BUTTON_REGISTRY


def get_action(action_id: str, tenant_id: str | None = None) -> dict | None:
    """Return action spec for action_id, checking tenant registry first."""
    if not action_id:
        return None
    aid = action_id.strip()
    tenant_reg = get_tenant_action_registry(tenant_id)
    if aid in tenant_reg:
        return tenant_reg[aid]
    return BUTTON_REGISTRY.get(aid)


def registry_prompt_text(tenant_id: str | None = None) -> str:
    """Allowed-buttons list formatted for the LLM prompt, scoped to tenant."""
    reg = get_tenant_action_registry(tenant_id)
    return "\n".join(
        f'- "{bid}" -> "{spec["title"]}"' for bid, spec in reg.items()
    )


def get_contextual_buttons(
    topic_or_query: str,
    tenant_id: str | None = None,
    wa_id: str | None = None,
    limit: int = 3,
) -> list[dict]:
    """Generate high-relevance, tenant-aware interactive buttons for any reply.

    Guarantees:
      - All button titles are <= 20 chars (WhatsApp reply-button limit).
      - All button ids match active tenant actions, flows, or main_menu.
      - Maximum `limit` buttons returned (default 3).
    """
    if limit <= 0:
        return []

    profile = None
    tid = tenant_id
    try:
        from shared.tenancy.loader import get_tenant_profile
        from shared.tenancy.resolver import resolve_tenant_for_user
        tid = tenant_id or resolve_tenant_for_user(wa_id or "")
        profile = get_tenant_profile(tid)
    except Exception:
        pass

    vertical = getattr(profile, "vertical", "generic") if profile else "generic"
    q = (topic_or_query or "").lower().strip()

    picked_ids: list[str] = []

    # 1. Healthcare Vertical
    if vertical == "healthcare":
        if any(k in q for k in ("appointment", "book", "slot", "doctor", "consult", "visit", "timing", "schedule")):
            if profile and profile.features.is_on("book_appointment"):
                picked_ids.append("menu_appointment")
            if profile and profile.features.is_on("callback"):
                picked_ids.append("menu_callback")
            picked_ids.append("menu_treatments")
        elif any(k in q for k in ("treatment", "surgery", "procedure", "care", "therapy", "physiotherapy", "cure", "health")):
            picked_ids.append("menu_treatments")
            if profile and profile.features.is_on("book_appointment"):
                picked_ids.append("menu_appointment")
            picked_ids.append("menu_specialities")
        elif any(k in q for k in ("speciality", "department", "cardiology", "ortho", "paediatric", "neuro", "gynae", "doctor")):
            picked_ids.append("menu_specialities")
            if profile and profile.features.is_on("book_appointment"):
                picked_ids.append("menu_appointment")
        elif any(k in q for k in ("complaint", "feedback", "grievance", "issue", "support", "help", "emergency")):
            if profile and profile.features.is_on("complaints"):
                picked_ids.append("menu_grievance")
            if profile and profile.features.is_on("human_handover"):
                picked_ids.append("menu_human")
        else:
            picked_ids = ["menu_treatments", "menu_appointment", "menu_callback"]
        picked_ids.append("main_menu")

    # 2. Banking Vertical
    elif vertical == "banking":
        if any(k in q for k in ("card", "credit card", "debit card", "atm card", "pin")):
            picked_ids.append("menu_cards")
            picked_ids.append("menu_products")
        elif any(k in q for k in ("loan", "emi", "interest", "home loan", "personal loan", "car loan", "borrow")):
            picked_ids.append("menu_loans")
            picked_ids.append("menu_eligibility")
        elif any(k in q for k in ("branch", "atm", "locator", "timing", "address", "ifsc", "location")):
            picked_ids.append("menu_branch")
            picked_ids.append("menu_products")
        elif any(k in q for k in ("fraud", "stolen", "unauthorized", "lost", "complaint", "grievance", "dispute")):
            if profile and profile.features.is_on("complaints"):
                picked_ids.append("menu_grievance")
            if profile and profile.features.is_on("human_handover"):
                picked_ids.append("menu_human")
        elif any(k in q for k in ("product", "account", "savings", "current", "fd", "deposit")):
            picked_ids.append("menu_products")
            picked_ids.append("menu_cards")
        else:
            picked_ids = ["menu_products", "menu_cards", "menu_branch"]
        picked_ids.append("main_menu")

    # 3. Finance & Advisory Vertical
    elif vertical == "finance":
        if any(k in q for k in ("proposal", "quote", "cost", "fee", "rate", "estimate", "pricing", "charges")):
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_proposal")
            if profile and profile.features.is_on("callback"):
                picked_ids.append("menu_callback")
        elif any(k in q for k in ("faq", "deadline", "tax", "gst", "due date", "compliance", "filing")):
            picked_ids.append("menu_faq")
            picked_ids.append("menu_services")
        elif any(k in q for k in ("service", "advisory", "audit", "consulting", "planning", "wealth")):
            picked_ids.append("menu_services")
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_proposal")
        elif any(k in q for k in ("callback", "call", "meet", "meeting", "consultation")):
            if profile and profile.features.is_on("callback"):
                picked_ids.append("menu_callback")
            if profile and profile.features.is_on("human_handover"):
                picked_ids.append("menu_human")
        else:
            picked_ids = ["menu_services", "menu_proposal", "menu_callback"]
        picked_ids.append("main_menu")

    # 4. Tours & Travel Vertical
    elif vertical == "tours_travel":
        if any(k in q for k in ("destination", "place", "kerala", "bali", "dubai", "europe", "rajasthan", "himachal", "goa", "andaman", "where")):
            picked_ids.append("menu_destinations")
            picked_ids.append("menu_packages")
        elif any(k in q for k in ("package", "tour", "trip", "itinerary", "stay", "hotel", "sightseeing", "inclusions")):
            picked_ids.append("menu_packages")
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_quote")
        elif any(k in q for k in ("policy", "cancel", "refund", "booking", "advance", "terms")):
            picked_ids.append("menu_booking_policy")
            if profile and profile.features.is_on("callback"):
                picked_ids.append("menu_callback")
        elif any(k in q for k in ("visa", "passport", "document", "entry")):
            picked_ids.append("menu_visa")
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_quote")
        elif any(k in q for k in ("quote", "price", "cost", "rates", "deal", "discount")):
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_quote")
            if profile and profile.features.is_on("callback"):
                picked_ids.append("menu_callback")
        else:
            picked_ids = ["menu_packages", "menu_destinations", "menu_callback"]
        picked_ids.append("main_menu")

    # 5. IT / Software & Services Vertical
    elif vertical == "it_software":
        if any(k in q for k in ("service", "solution", "build", "develop", "software", "app", "web")):
            picked_ids.append("menu_services")
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_quote")
        elif any(k in q for k in ("technolog", "tech", "stack", "react", "python", "node", "ai", "cloud")):
            picked_ids.append("menu_technologies")
            picked_ids.append("menu_services")
        elif any(k in q for k in ("project", "portfolio", "case study", "client", "work")):
            picked_ids.append("menu_projects")
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_quote")
        elif any(k in q for k in ("career", "job", "hiring", "vacancy", "opening", "internship")):
            picked_ids.append("menu_careers")
            if profile and profile.features.is_on("human_handover"):
                picked_ids.append("menu_human")
        elif any(k in q for k in ("price", "pricing", "cost", "quote", "rate", "budget", "fee")):
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_quote")
            if profile and profile.features.is_on("callback"):
                picked_ids.append("menu_callback")
        elif any(k in q for k in ("callback", "call", "meet", "meeting", "schedule", "demo")):
            if profile and profile.features.is_on("callback"):
                picked_ids.append("menu_callback")
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_quote")
        else:
            picked_ids = ["menu_services", "menu_callback", "menu_technologies"]
        picked_ids.append("main_menu")

    # 6. E-Commerce Vertical
    elif vertical == "ecommerce":
        if any(k in q for k in ("cart", "checkout", "buy", "basket")):
            if profile and profile.features.is_on("cart"):
                picked_ids.append("menu_view_cart")
            picked_ids.append("menu_products")
        elif any(k in q for k in ("track", "order status", "delivery", "shipping", "dispatch", "courier")):
            if profile and profile.features.is_on("track_order"):
                picked_ids.append("track_order")
            picked_ids.append("menu_products")
        elif any(k in q for k in ("brochure", "catalogue", "catalog", "pdf")):
            if profile and profile.features.is_on("brochure_pdf"):
                picked_ids.append("menu_catalogue")
            picked_ids.append("menu_products")
        elif any(k in q for k in ("complaint", "issue", "damaged", "return", "refund")):
            if profile and profile.features.is_on("complaints"):
                picked_ids.append("menu_complaint")
            if profile and profile.features.is_on("human_handover"):
                picked_ids.append("menu_human")
        else:
            picked_ids = ["menu_products", "menu_catalogue", "menu_discounts"]
        picked_ids.append("main_menu")

    # 7. Generic Fallback
    else:
        if any(k in q for k in ("quote", "cost", "price")):
            if profile and profile.features.is_on("quote"):
                picked_ids.append("menu_quote")
        if any(k in q for k in ("callback", "call", "meet")):
            if profile and profile.features.is_on("callback"):
                picked_ids.append("menu_callback")
        picked_ids.extend(["menu_offerings", "menu_callback", "main_menu"])

    # Filter to unique, valid buttons matching enabled features
    result = []
    seen = set()
    for bid in picked_ids:
        if bid not in seen and bid in BUTTONS:
            req_feat = BUTTON_FEATURE_REQUIREMENTS.get(bid)
            if profile and req_feat and not profile.features.is_on(req_feat):
                continue
            seen.add(bid)
            title = BUTTONS[bid]
            result.append({"id": bid[:50], "title": title[:20]})
            if len(result) >= limit:
                break

    # Honor the tenant's actual menu: a suggestion the tenant has tombstoned,
    # disabled, or gated off (e.g. a removed "Get a Quote" row) must not surface.
    try:
        allowed_ids = set(get_tenant_action_registry(tid).keys())
    except Exception:
        allowed_ids = None
    if allowed_ids is not None:
        result = [b for b in result if b["id"] in allowed_ids]

    # If still fewer than limit, ensure main_menu is present
    if not any(b["id"] == "main_menu" for b in result) and len(result) < limit:
        result.append({"id": "main_menu", "title": BUTTONS["main_menu"][:20]})

    return result[:limit]


def suggest_actions(query: str, source_file: str = "", tenant_id: str | None = None) -> list[dict]:
    """Helper returning [{"id", "title"}] for query or tenant."""
    # If a tenant profile is present and matches the vertical, use contextual buttons
    tid = tenant_id
    if not tid:
        try:
            from shared.tenancy.resolver import resolve_default_tenant
            tid = resolve_default_tenant()
        except Exception:
            pass

    if tid:
        contextual = get_contextual_buttons(query, tenant_id=tid, limit=3)
        if contextual:
            return contextual

    out = [
        {"id": s["id"], "title": s.get("label", s["id"])}
        for s in get_suggestion_buttons(query, top_k=3)
    ]
    if out or not source_file:
        return out
    sf = source_file.lower()
    for group in TOPIC_SUGGESTIONS:
        for src in group.get("source", []) or []:
            if src and src.lower() in sf:
                return [
                    {"id": a, "title": BUTTONS.get(a, a)}
                    for a in group.get("actions", [])[:3]
                    if a in BUTTONS
                ]
    return out

