"""Per-vertical default profiles.

These are the *lowest* precedence layer: a tenant only writes what differs.
Data, not code — adding a vertical means adding an entry here, not a branch.

Prompt-facing hints (domain queries, support triggers, tone) live in
``routing/prompts.py::COMPANY_TYPE_CONFIGS`` and are fallback data only; the
runtime reads ``profile.vertical`` and looks the hints up there.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

# vertical -> key in routing/prompts.py::COMPANY_TYPE_CONFIGS
VERTICAL_TO_COMPANY_TYPE = {
    "ecommerce": "ecommerce",
    "it_software": "it",
    "tours_travel": "travel",
    "banking": "banking",
    "finance": "finance",
    "healthcare": "healthcare",
    "generic": "generic",
}

DEFAULT_TENANT_ID = "default"


# ── shared intent fragments ────────────────────────────────────────────────

def _intents(*specs: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(s) for s in specs]


_GREETING = {
    "name": "greeting",
    "examples": ["hi", "hello", "hey there", "good morning"],
    "keywords": ["hi", "hello", "hey", "good morning", "good evening"],
}

_CONTACT_HUMAN = {
    "name": "contact_human",
    "examples": ["talk to a human", "connect me to an agent", "is a person available?"],
    # No bare "someone" — it matched "someone used my card" (fraud!) and any
    # sentence containing the word. Phrases only.
    "keywords": ["human", "agent", "person", "executive", "manager", "speak to someone"],
    "requires_feature": "human_handover",
    "flow": "book_callback",
}

_COMPLAINT = {
    "name": "complaint",
    "examples": ["I have a complaint", "this is unacceptable", "I want to escalate"],
    "keywords": ["complaint", "unacceptable", "terrible", "escalate", "bad experience"],
    "requires_feature": "complaints",
    "flow": "raise_ticket",
}

_PRICING = {
    "name": "pricing_enquiry",
    "examples": ["how much does it cost", "what is the price", "share your rates"],
    "keywords": ["price", "pricing", "cost", "rate", "rates", "charges", "budget",
                 "fees", "fee", "interest rate"],
}

_SUPPORT = {
    "name": "support_request",
    "examples": ["I need help", "something is not working", "support please"],
    "keywords": ["help", "support", "issue", "problem", "not working", "stuck",
                 "wrong with", "not right", "broken"],
}


# ── ecommerce (TrooGood) ───────────────────────────────────────────────────

_ECOMMERCE = {
    "vertical": "ecommerce",
    "display_name": "TrooGood",
    "prompt": {
        # Faithful to the legacy COMPANY_TYPE_CONFIGS['ecommerce'] entry so
        # TrooGood's classifier behaviour is unchanged by this migration.
        "name": "E-commerce Brand",
        "tone": "customer-friendly",
        "industry": "retail",
        "domain_specific_queries": "products, pricing, availability, shipping, or return policies",
        "domain_specific_topics": "products, pricing, availability, shipping, delivery times, return policies",
        "support_trigger_topics": "order tracking, product complaints, return requests, refund issues",
        "complex_topics": "bulk orders, custom products, enterprise pricing, distribution inquiries",
        "listing_type": "products or catalog items",
        "keywords": [
            "product", "price", "order", "shipping", "delivery", "cart", "checkout",
            "catalog", "catalogue", "stock", "refund", "return", "pack size", "snack",
        ],
    },
    "features": {
        "cart": True,
        "buy_now": True,
        "orders": True,
        "track_order": True,
        "returns": True,
        "brochure_pdf": True,
        "distributors": True,
        "offerings": True,
        "offering_details": True,
        "lead_capture": True,
        "quote": False,
        "callback": False,
        "book_appointment": False,
        "handoff": True,
        "faq": True,
        "kb": True,
        "complaints": True,
        "campaigns": True,
        "human_handover": True,
    },
    "vocabulary": {
        "item_noun": "products",
        "item_noun_singular": "product",
        "browse_label": "View Products",
        "catalog_label": "Brochure",
        "catalog_noun": "brochure",
        "order_noun": "order",
        "order_noun_plural": "orders",
        "cart_noun": "cart",
        "checkout_label": "Checkout",
        "brochure_label": "Brochure",
        "brochure_noun": "brochure",
        "offer_noun": "offer",
        "offer_noun_plural": "offers",
        "lead_noun": "enquiry",
        "enquiry_label": "Enquire",
        "quote_label": "Request a Quote",
        "callback_label": "Request a Callback",
        "support_label": "Raise Complaint",
        "track_label": "Track Order",
    },
    "menu": {
        "key": "kb_main",
        # TrooGood keeps the exact greeting copy the live bot used before the
        # profile system, so migrating the menu changes nothing a shopper sees.
        "body": "What would you like to explore today?",
        "footer": "Or type your question directly",
        "button_text": "Show Options",
        "buttons": [
            {"id": "menu_products", "title": "View Products", "description": "Browse all products",
             "section": "🛍️ Products", "icon": "🛍️", "sort_order": 0, "requires_feature": "offerings"},
            {"id": "menu_catalogue", "title": "Brochure", "description": "Download the brochure PDF",
             "section": "🛍️ Products", "icon": "📄", "sort_order": 1, "requires_feature": "brochure_pdf"},
            {"id": "menu_new_arrivals", "title": "New Releases", "description": "Fresh releases this month",
             "section": "🛍️ Products", "icon": "✨", "sort_order": 2},
            {"id": "menu_about", "title": "Company Policies", "description": "About us & company policies",
             "section": "ℹ️ Info", "icon": "🏢", "sort_order": 3},
            {"id": "menu_discounts", "title": "Discounts & Offers", "description": "Current deals & bulk discounts",
             "section": "ℹ️ Info", "icon": "🎁", "sort_order": 4},
            {"id": "menu_gst", "title": "GST Info", "description": "GST number & tax invoice details",
             "section": "ℹ️ Info", "icon": "🧾", "sort_order": 5},
            {"id": "menu_credit_policy", "title": "Credit Policy", "description": "Credit period & payment terms",
             "section": "ℹ️ Info", "icon": "💳", "sort_order": 6},
            {"id": "menu_complaint", "title": "Raise Complaint", "description": "Report a problem with your order",
             "section": "🆘 Support", "icon": "📝", "sort_order": 7, "requires_feature": "complaints",
             "flow": "raise_ticket"},
            {"id": "menu_view_cart", "title": "View Cart", "description": "See items in your cart",
             "section": "🆘 Support", "icon": "🛒", "sort_order": 8, "requires_feature": "cart"},
            {"id": "menu_human", "title": "Talk to Human", "description": "Chat with our support team",
             "section": "🆘 Support", "icon": "🙋", "sort_order": 9, "requires_feature": "human_handover", "flow": "book_callback"},
        ],
    },
    "intents": _intents(
        _GREETING,
        {"name": "catalogue_request", "examples": ["send me the brochure", "download the price list"],
         "keywords": ["catalogue", "catalog", "brochure", "price list"], "requires_feature": "brochure_pdf"},
        {"name": "new_arrivals", "examples": ["what is new", "latest releases"],
         "keywords": ["new arrival", "new arrivals", "new launch", "new release", "new releases", "latest product", "fresh drops"]},
        {"name": "offer_discount", "examples": ["any discounts?", "current offers"],
         "keywords": ["offer", "offers", "discount", "deal", "coupon", "promotion", "scheme"]},
        {"name": "policy_query", "examples": ["what is your return policy", "shipping charges?"],
         "keywords": ["policy", "policies", "return", "refund", "exchange", "cancellation", "terms", "privacy",
                      "shipping policy", "payment terms", "gst", "credit period"]},
        {"name": "product_details", "examples": ["what is in the peanut chikki", "ingredients?"],
         "keywords": ["ingredients", "nutrition", "protein", "shelf life", "specification", "flavour",
                      "pack size", "tell me about", "recipe", "how to use"], "requires_feature": "offering_details"},
        {"name": "pricing_enquiry", "examples": ["price of the jaggery chikki", "how much is it?",
                                                  "what are your bulk rates"],
         "keywords": ["price", "cost", "rate", "mrp", "bulk rate", "pricing"], "requires_feature": "offering_details"},
        {"name": "place_order", "examples": ["I want to order", "place an order", "buy now"],
         "keywords": ["place order", "order now", "buy now", "purchase", "i want to buy", "checkout"],
         "requires_feature": "buy_now", "flow": "place_order"},
        {"name": "order_status", "examples": ["where is my order", "track my order"],
         "keywords": ["track order", "order status", "where is my order", "delivery status"],
         "requires_feature": "track_order", "flow": "track_order"},
        {"name": "return_refund", "examples": ["I want a refund", "return this product"],
         "keywords": ["refund", "return", "exchange", "replacement"], "requires_feature": "returns"},
        _COMPLAINT,
        {"name": "bulk_enquiry", "examples": ["I want to become a distributor", "bulk rates?"],
         "keywords": ["distributor", "dealer", "wholesale", "bulk", "moq", "franchise", "reseller",
                      "margin", "credit terms"], "requires_feature": "distributors", "flow": "enquire"},
        _CONTACT_HUMAN,
        _SUPPORT,
        {"name": "careers", "examples": ["are you hiring", "job openings"],
         "keywords": ["career", "job", "hiring", "vacancy", "internship"]},
        {"name": "company_about", "examples": ["about troogood", "who are you"],
         "keywords": ["about company", "about us", "about troogood", "brand story"]},
    ),
}


# ── it_software ───────────────────────────────────────────────────────────

_IT_SOFTWARE = {
    "vertical": "it_software",
    "display_name": "Leeway Softech",
    "prompt": {
        "name": "IT/Software Company",
        "tone": "professional",
        "industry": "software and IT services",
        "domain_specific_queries": (
            "services, technologies, packages, pricing, implementation timelines, "
            "or ongoing support"
        ),
        "domain_specific_topics": (
            "services, technologies, pricing, timelines, implementation, or support"
        ),
        "support_trigger_topics": (
            "project quotes, enterprise solutions, urgent production issues, "
            "project timelines, pricing negotiations"
        ),
        "complex_topics": (
            "custom development requirements, enterprise architecture, complex "
            "integrations, project management"
        ),
        "listing_type": "services or solutions",
        "keywords": [
            "software", "development", "technical", "it", "technology", "solution",
            "service", "website", "mobile app", "cloud", "support", "maintenance",
        ],
    },
    "features": {
        "cart": False,
        "buy_now": False,
        "orders": False,
        "track_order": False,
        "returns": False,
        "brochure_pdf": True,
        "distributors": False,
        "offerings": True,
        "offering_details": True,
        "lead_capture": True,
        "quote": True,
        "callback": True,
        "book_appointment": True,
        "handoff": True,
        "faq": True,
        "kb": True,
        "complaints": True,
        "campaigns": False,
        "human_handover": True,
    },
    "vocabulary": {
        "item_noun": "services",
        "item_noun_singular": "service",
        "browse_label": "Our Services",
        "catalog_label": "Service Brochure",
        "catalog_noun": "service brochure",
        "order_noun": "engagement",
        "order_noun_plural": "engagements",
        "cart_noun": "shortlist",
        "checkout_label": "Request a Quote",
        "brochure_label": "Service Brochure",
        "brochure_noun": "service brochure",
        "offer_noun": "offering",
        "offer_noun_plural": "offerings",
        "lead_noun": "enquiry",
        "enquiry_label": "Enquire",
        "quote_label": "Get a Quote",
        "callback_label": "Book a Callback",
        "support_label": "Support",
        "track_label": "Track Request",
    },
    "menu": {
        "key": "kb_main",
        "body": "How can we help you today?",
        "footer": "Or type your question",
        "button_text": "Show Options",
        "buttons": [
            {"id": "menu_services", "title": "Our Services", "description": "What we build and deliver",
             "section": "🛠️ Services", "icon": "🛠️", "sort_order": 0, "requires_feature": "offerings"},
            {"id": "menu_technologies", "title": "Technologies", "description": "Our tech stack & expertise",
             "section": "🛠️ Services", "icon": "💻", "sort_order": 1, "requires_feature": "offering_details",
             "intent": "technologies"},
            {"id": "menu_projects", "title": "Projects", "description": "Work we have delivered",
             "section": "🏢 Company", "icon": "📁", "sort_order": 2, "intent": "projects"},
            {"id": "menu_brochure", "title": "Service Brochure", "description": "Download our brochure",
             "section": "🏢 Company", "icon": "📄", "sort_order": 3, "requires_feature": "brochure_pdf"},
            {"id": "menu_careers", "title": "Careers", "description": "Open roles & hiring process",
             "section": "🏢 Company", "icon": "💼", "sort_order": 4, "intent": "careers"},
            {"id": "menu_benefits", "title": "Benefits", "description": "Why work with us",
             "section": "🏢 Company", "icon": "🎁", "sort_order": 5, "intent": "benefits"},
            {"id": "menu_quote", "title": "Get a Quote", "description": "Tell us about your project",
             "section": "📞 Talk To Us", "icon": "📝", "sort_order": 6, "requires_feature": "quote",
             "flow": "get_quote"},
            {"id": "menu_callback", "title": "Book a Callback", "description": "Have us call you back",
             "section": "📞 Talk To Us", "icon": "📞", "sort_order": 7, "requires_feature": "callback",
             "flow": "book_callback"},
            {"id": "menu_support", "title": "Support", "description": "Existing client support",
             "section": "📞 Talk To Us", "icon": "🆘", "sort_order": 8, "flow": "raise_ticket"},
            {"id": "menu_human", "title": "Talk to Human", "description": "Chat with our team",
             "section": "📞 Talk To Us", "icon": "🙋", "sort_order": 9, "requires_feature": "human_handover", "flow": "book_callback"},
        ],
    },
    "intents": _intents(
        _GREETING,
        {"name": "service_enquiry", "examples": ["what services do you offer", "do you build mobile apps"],
         "keywords": ["service", "services", "what do you do", "capability", "capabilities",
                      "offerings", "solution", "expertise"], "requires_feature": "offerings"},
        {"name": "technologies", "examples": ["what technologies do you work with", "what is your tech stack"],
         "keywords": ["technologies", "technology", "tech stack", "stack", "framework", "tools",
                      "programming languages"],
         "answer": ("• Here's the stack we build with:\n"
                    "• *Frontend:* modern JavaScript frameworks and UI systems\n"
                    "• *Backend:* Node.js, Python, PHP and .NET services\n"
                    "• *Mobile:* cross-platform and native iOS / Android\n"
                    "• *Cloud & DevOps:* AWS, Azure, Docker and CI/CD pipelines\n"
                    "• *Databases:* SQL and NoSQL stores chosen per project\n"
                    "• Tell us what you're building and we'll match the right stack for it.")},
        {"name": "package_details", "examples": ["tell me about website development", "what is in the mobile app package"],
         "keywords": ["package", "mobile app", "ecommerce website", "detail", "details"],
         "requires_feature": "offering_details"},
        _PRICING,
        {"name": "demo_request", "examples": ["can I see a demo", "book a demo call"],
         "keywords": ["demo", "demonstration", "walkthrough", "live demo", "sample", "trial"],
         "requires_feature": "book_appointment", "flow": "get_quote"},
        {"name": "projects", "examples": ["show me your work", "who have you built for"],
         "keywords": ["projects", "project", "portfolio", "your work", "case study", "case studies", "clients", "experience"],
         "answer": ("• A snapshot of the work we deliver:\n"
                    "• *Web platforms:* e-commerce, portals and internal systems\n"
                    "• *Mobile apps:* customer and field-force apps on iOS and Android\n"
                    "• *Enterprise:* CRM, ERP integrations and workflow automation\n"
                    "• *Industries:* retail, healthcare, finance, logistics and education\n"
                    "• We share client names and detailed case studies only with their permission — our team can walk you through relevant examples on a call.")},
        {"name": "engagement_model", "examples": ["how do you work with clients", "what are your engagement models"],
         "keywords": ["engagement model", "process", "workflow", "milestone", "retainer", "onboarding",
                      "how do you work", "methodology"]},
        {"name": "quote_request", "examples": ["I need a quote", "how much for a website"],
         "keywords": ["quote", "quotation", "estimate", "proposal", "pricing", "get a quote"],
         "requires_feature": "quote", "flow": "get_quote"},
        {"name": "callback_request", "examples": ["call me back", "arrange a call"],
         "keywords": ["call back", "callback", "phone call", "speak to someone", "arrange a call"],
         "requires_feature": "callback", "flow": "book_callback"},
        {"name": "brochure_request", "examples": ["send me your brochure", "company profile pdf"],
         "keywords": ["brochure", "company profile", "pdf", "capability statement"],
         "requires_feature": "brochure_pdf"},
        {"name": "careers", "examples": ["are you hiring", "job openings at your company"],
         "keywords": ["career", "careers", "job", "hiring", "vacancy", "internship", "open role"],
         "answer": ("• We're always glad to hear from good people:\n"
                    "• *Roles we hire for:* frontend, backend and mobile developers, QA, DevOps and designers\n"
                    "• *Internships:* available for final-year students and fresh graduates\n"
                    "• *How to apply:* send your CV to our team with the role in the subject line\n"
                    "• Shortlisted candidates hear from us within a few days.")},
        {"name": "benefits", "examples": ["why should we work with you", "what are the benefits"],
         "keywords": ["benefits", "why choose you", "why work with you", "advantages", "perks",
                      "what makes you different"],
         "answer": ("• Why teams choose to work with us:\n"
                    "• *Dedicated point of contact* for every engagement\n"
                    "• *Agile delivery* in short, transparent sprints\n"
                    "• *Regular demos and reports* — you always know where things stand\n"
                    "• *Post-launch support and maintenance* options\n"
                    "• *Your IP stays yours* — code and assets are handed over\n"
                    "• NDA and clear contracts on request.")},
        _COMPLAINT,
        _SUPPORT,
        _CONTACT_HUMAN,
    ),
    "guardrails": {
        "never_state": ["prices", "costs", "delivery dates", "deadlines", "client names",
                        "project start dates", "discounts"],
        "never_state_notes": {
            "prices": "Prices are confirmed by the team after scoping. Never quote a number.",
            "delivery dates": "Timelines are agreed in the proposal, never stated by the bot.",
            "client names": "Never name clients without explicit written consent.",
        },
        "escalate_keywords": ["urgent", "production down", "site is down", "outage", "data loss",
                              "security breach", "critical bug", "not working", "blocked"],
        "escalation_message": "This needs a human — I'm connecting you with our support team now.",
        "forbidden_terms": ["cart", "checkout", "add to cart", "buy now", "place order",
                            "track order", "shipping", "delivery charge", "mrp"],
    },
}


# ── tours_travel ───────────────────────────────────────────────────────────

_TOURS_TRAVEL = {
    "vertical": "tours_travel",
    "display_name": "Wanderly Travel",
    "prompt": {
        "name": "Travel Agency",
        "tone": "friendly and reassuring",
        "industry": "travel and tourism",
        "domain_specific_queries": "destinations, packages, pricing, dates, visa requirements, or booking policies",
        "domain_specific_topics": "destinations, packages, pricing, itineraries, visa documents, booking policy",
        "support_trigger_topics": "group bookings, custom itineraries, visa issues, cancellations, urgent travel changes",
        "complex_topics": "multi-country itineraries, group travel, corporate travel, visa complications",
        "listing_type": "destinations or packages",
        "keywords": [
            "travel", "trip", "tour", "package", "destination", "itinerary", "visa",
            "flight", "hotel", "booking", "holiday", "vacation", "passport",
        ],
    },
    "features": {
        "cart": False,
        "buy_now": False,
        "orders": False,
        "track_order": False,
        "returns": False,
        "brochure_pdf": True,
        "distributors": False,
        "offerings": True,
        "offering_details": True,
        "lead_capture": True,
        "quote": True,
        "callback": True,
        "book_appointment": True,
        "handoff": True,
        "faq": True,
        "kb": True,
        "complaints": True,
        "campaigns": False,
        "human_handover": True,
    },
    "vocabulary": {
        "item_noun": "packages",
        "item_noun_singular": "package",
        "browse_label": "Our Packages",
        "catalog_label": "Travel Brochure",
        "catalog_noun": "travel brochure",
        "order_noun": "booking",
        "order_noun_plural": "bookings",
        "cart_noun": "shortlist",
        "checkout_label": "Start Booking",
        "brochure_label": "Travel Brochure",
        "brochure_noun": "travel brochure",
        "offer_noun": "offer",
        "offer_noun_plural": "offers",
        "lead_noun": "enquiry",
        "enquiry_label": "Enquire",
        "quote_label": "Get a Quote",
        "callback_label": "Book a Callback",
        "support_label": "Support",
        "track_label": "Track Booking",
    },
    "menu": {
        "key": "kb_main",
        "body": "Where would you like to go?",
        "footer": "Or type your question directly",
        "button_text": "Show Options",
        "buttons": [
            {"id": "menu_destinations", "title": "Destinations", "description": "Places we take you to",
             "section": "✈️ Travel", "icon": "🗺️", "sort_order": 0, "requires_feature": "offerings"},
            {"id": "menu_packages", "title": "Packages", "description": "Holidays & tour packages",
             "section": "✈️ Travel", "icon": "🎒", "sort_order": 1, "requires_feature": "offerings"},
            {"id": "menu_brochure", "title": "Travel Brochure", "description": "Download our brochure",
             "section": "✈️ Travel", "icon": "📄", "sort_order": 2, "requires_feature": "brochure_pdf"},
            {"id": "menu_booking_policy", "title": "Booking Policy", "description": "Cancellations & payments",
             "section": "ℹ️ Info", "icon": "📋", "sort_order": 3},
            {"id": "menu_visa", "title": "Visa & Documents", "description": "What you need to travel",
             "section": "ℹ️ Info", "icon": "🛂", "sort_order": 4},
            {"id": "menu_quote", "title": "Enquire", "description": "Plan a trip with us",
             "section": "📞 Talk To Us", "icon": "📝", "sort_order": 5, "requires_feature": "lead_capture",
             "flow": "enquire"},
            {"id": "menu_callback", "title": "Book a Callback", "description": "Have us call you back",
             "section": "📞 Talk To Us", "icon": "📞", "sort_order": 6, "requires_feature": "callback",
             "flow": "book_callback"},
            {"id": "menu_support", "title": "Support", "description": "Existing booking support",
             "section": "📞 Talk To Us", "icon": "🆘", "sort_order": 7, "flow": "raise_ticket"},
            {"id": "menu_human", "title": "Talk to Human", "description": "Chat with our team",
             "section": "📞 Talk To Us", "icon": "🙋", "sort_order": 8, "requires_feature": "human_handover", "flow": "book_callback"},
        ],
    },
    "intents": _intents(
        _GREETING,
        {"name": "destination_details", "examples": ["tell me about Bali", "which places do you cover"],
         "keywords": ["destination", "destinations", "places", "city", "country", "where", "location",
                      "attraction", "attractions"], "requires_feature": "offerings"},
        {"name": "package_details", "examples": ["what is included in the Bali package", "5 day itinerary"],
         "keywords": ["package", "packages", "tour", "tours", "itinerary", "days", "nights", "included",
                      "excluded", "hotel", "flight"], "requires_feature": "offering_details"},
        _PRICING,
        {"name": "booking_inquiry", "examples": ["I want to book a trip", "availability for December"],
         "keywords": ["want to book", "book a trip", "book a tour", "availability", "reserve",
                      "reservation", "group booking", "family tour", "honeymoon"],
         "requires_feature": "book_appointment", "flow": "enquire"},
        {"name": "visa_documents", "examples": ["do you help with visa", "what documents are needed"],
         "keywords": ["visa", "passport", "documents", "paperwork", "visa assistance", "travel insurance",
                      "permits"], "requires_feature": "faq"},
        {"name": "booking_policy", "examples": ["cancellation policy", "how far in advance should I book"],
         "keywords": ["cancellation", "cancel", "refund", "policy", "policies", "payment terms",
                      "advance booking", "reschedule"], "requires_feature": "faq"},
        {"name": "quote_request", "examples": ["I need a quote for a trip", "get me a package price"],
         "keywords": ["quote", "quotation", "estimate", "proposal"], "requires_feature": "quote",
         "flow": "get_quote"},
        {"name": "callback_request", "examples": ["call me back", "arrange a call"],
         "keywords": ["call back", "callback", "phone call", "speak to someone"],
         "requires_feature": "callback", "flow": "book_callback"},
        {"name": "brochure_request", "examples": ["send me the travel brochure"],
         "keywords": ["brochure", "pdf", "itinerary pdf"], "requires_feature": "brochure_pdf"},
        _COMPLAINT,
        _SUPPORT,
        _CONTACT_HUMAN,
    ),
    "guardrails": {
        "never_state": ["package prices", "availability without confirmation", "visa guarantees",
                        "flight schedules", "hotel names without confirmation"],
        "never_state_notes": {
            "package prices": "Package pricing varies by date and group size. Share details and let the team quote.",
        },
        "escalate_keywords": ["urgent", "cancelled", "lost luggage", "missed flight", "emergency",
                              "visa denied", "no-show"],
        "escalation_message": "Let me get you to a travel specialist right away.",
        "forbidden_terms": ["add to cart", "buy now", "checkout", "product price", "mrp", "place order"],
    },
}


# ── banking ───────────────────────────────────────────────────────────────

_BANKING = {
    "vertical": "banking",
    "display_name": "Meridian Bank",
    "prompt": {
        "name": "Bank",
        "tone": "formal, reassuring, and precise",
        "industry": "banking and financial services",
        "domain_specific_queries": "accounts, cards, loans, eligibility, fees, or branch information",
        "domain_specific_topics": "accounts, cards, loans, interest rates, eligibility, fees, branches",
        "support_trigger_topics": "fraud reports, lost cards, disputed transactions, account locks, grievances",
        "complex_topics": "loan applications, account closures, fraud investigations, regulatory queries",
        "listing_type": "banking products",
        "keywords": [
            "account", "card", "loan", "branch", "atm", "deposit", "interest rate",
            "emi", "kyc", "net banking", "upi", "fraud",
        ],
    },
    "features": {
        "cart": False, "buy_now": False, "orders": False, "track_order": False,
        "returns": False, "brochure_pdf": False, "distributors": False,
        "offerings": True, "offering_details": True,
        "lead_capture": True, "quote": False, "callback": True, "book_appointment": True,
        "handoff": True, "faq": True, "kb": True, "complaints": True, "campaigns": True,
        "human_handover": True,
    },
    "vocabulary": {
        "item_noun": "products", "item_noun_singular": "product",
        "browse_label": "Banking Products", "catalog_label": "Product Brochure",
        "catalog_noun": "product brochure",
        "order_noun": "request", "order_noun_plural": "requests",
        "cart_noun": "shortlist", "checkout_label": "Apply",
        "brochure_label": "Product Brochure", "brochure_noun": "product brochure",
        "offer_noun": "offer", "offer_noun_plural": "offers",
        "lead_noun": "enquiry", "enquiry_label": "Enquire",
        "quote_label": "Check Eligibility", "callback_label": "Request a Callback",
        "support_label": "Raise a Complaint", "track_label": "Track Request",
    },
    "menu": {
        "key": "kb_main",
        "body": "How can we help you today?",
        "footer": "Or type your question",
        "button_text": "Show Options",
        "buttons": [
            {"id": "menu_products", "title": "Banking Products", "description": "Accounts, cards & loans",
             "section": "🏦 Products", "icon": "🏦", "sort_order": 0, "requires_feature": "offerings"},
            {"id": "menu_cards", "title": "Cards", "description": "Credit & debit card help",
             "section": "🏦 Products", "icon": "💳", "sort_order": 1, "requires_feature": "offering_details"},
            {"id": "menu_loans", "title": "Loans", "description": "Personal, home & business loans",
             "section": "🏦 Products", "icon": "🏠", "sort_order": 2, "requires_feature": "offering_details"},
            {"id": "menu_eligibility", "title": "Check Eligibility", "description": "Get a quick check",
             "section": "📞 Talk To Us", "icon": "✅", "sort_order": 3, "requires_feature": "lead_capture",
             "flow": "enquire"},
            {"id": "menu_callback", "title": "Request a Callback", "description": "Have us call you back",
             "section": "📞 Talk To Us", "icon": "📞", "sort_order": 4, "requires_feature": "callback",
             "flow": "book_callback"},
            {"id": "menu_grievance", "title": "Raise a Complaint", "description": "Register a grievance",
             "section": "🆘 Support", "icon": "📝", "sort_order": 5, "requires_feature": "complaints",
             "flow": "raise_ticket"},
            {"id": "menu_branch", "title": "Branch & Support", "description": "Find us / contact support",
             "section": "🆘 Support", "icon": "📍", "sort_order": 6},
            {"id": "menu_human", "title": "Talk to Human", "description": "Chat with our team",
             "section": "🆘 Support", "icon": "🙋", "sort_order": 7, "requires_feature": "human_handover", "flow": "book_callback"},
        ],
    },
    "intents": _intents(
        _GREETING,
        # Operational intents come FIRST: on keyword ties, a lost card must
        # outrank a product question. Informational intents sit last.
        {"name": "service_request", "examples": ["how do I activate my card", "net banking is not working"],
         "keywords": ["activate", "block", "unblock", "card pin", "reset pin", "net banking", "mobile banking",
                      "upi", "transfer", "statement", "not working", "failed"],
         "requires_feature": "faq", "flow": "raise_ticket"},
        {"name": "grievance", "examples": ["I want to file a complaint", "my issue is not resolved"],
         "keywords": ["complaint", "grievance", "unhappy", "escalate", "not resolved"],
         "requires_feature": "complaints", "flow": "raise_ticket"},
        {"name": "fraud_report", "examples": ["someone used my card", "report fraud"],
         "keywords": ["fraud", "fraud transaction", "fraudulent", "used my card", "without permission",
                      "stolen", "unauthorised", "unauthorized", "suspicious", "scam", "lost card"],
         "requires_feature": "handoff", "flow": "raise_ticket"},
        {"name": "eligibility_check", "examples": ["am I eligible for a loan", "check my eligibility"],
         "keywords": ["eligible", "eligibility", "pre-approved", "apply", "application"],
         "requires_feature": "lead_capture", "flow": "enquire"},
        {"name": "callback_request", "examples": ["call me back", "arrange a call"],
         "keywords": ["call back", "callback", "phone call", "speak to someone"],
         "requires_feature": "callback", "flow": "book_callback"},
        {"name": "branch_locator", "examples": ["find my nearest branch", "branch timings"],
         "keywords": ["branch", "atm", "nearest", "timings", "hours", "location", "ifsc"]},
        _PRICING,
        _SUPPORT,
        _CONTACT_HUMAN,
        # Informational last — owns the product nouns but NOT the words the
        # operational intents above need (interest rate / fees / charges belong
        # to pricing, eligibility to eligibility_check).
        {"name": "product_details", "examples": ["what are the fees on a savings account", "tell me about home loans"],
         "keywords": ["account", "savings", "current account", "fd", "card", "loan", "emi", "documents"],
         "requires_feature": "offering_details"},
    ),
    "guardrails": {
        "never_state": ["interest rate offers", "account balances", "loan approvals", "OTP or PIN values",
                        "Aadhaar/PAN numbers", "guaranteed approval"],
        "never_state_notes": {
            "interest rate offers": "Rates change. Never state a rate; point to the current product page or offer a callback.",
            "account balances": "The bot can never see or state an account balance.",
        },
        "escalate_keywords": ["fraud", "unauthorised", "unauthorized", "stolen", "lost card", "account frozen",
                              "complaint not resolved", "urgent", "harassment"],
        "escalation_message": "This needs a banking specialist — connecting you now.",
        "forbidden_terms": ["add to cart", "buy now", "checkout", "place order", "track order", "shipping"],
    },
    "business_hours": {
        "timezone": "Asia/Kolkata", "always_open": False,
        "open": "09:00", "close": "18:00", "open_days": [0, 1, 2, 3, 4, 5],
    },
}


# ── finance ───────────────────────────────────────────────────────────────

_FINANCE = {
    "vertical": "finance",
    "display_name": "Northwind Capital",
    "prompt": {
        "name": "Financial Advisory",
        "tone": "professional and measured",
        "industry": "finance and investment advisory",
        "domain_specific_queries": "services, fees, returns, compliance, risk, or proposal requests",
        "domain_specific_topics": "services, fees, expected returns, risk, compliance, portfolio review",
        "support_trigger_topics": "large allocations, compliance questions, disputes, account issues, withdrawal requests",
        "complex_topics": "portfolio restructuring, tax planning, multi-jurisdiction holdings, compliance reviews",
        "listing_type": "services or advisory offerings",
        "keywords": [
            "investment", "advisory", "portfolio", "returns", "fee", "compliance",
            "risk", "wealth", "capital", "proposal", "roi",
        ],
    },
    "features": {
        "cart": False, "buy_now": False, "orders": False, "track_order": False,
        "returns": False, "brochure_pdf": True, "distributors": False,
        "offerings": True, "offering_details": True,
        "lead_capture": True, "quote": True, "callback": True, "book_appointment": True,
        "handoff": True, "faq": True, "kb": True, "complaints": True, "campaigns": False,
        "human_handover": True,
    },
    "vocabulary": {
        "item_noun": "services", "item_noun_singular": "service",
        "browse_label": "Our Services", "catalog_label": "Services Brochure",
        "catalog_noun": "services brochure",
        "order_noun": "mandate", "order_noun_plural": "mandates",
        "cart_noun": "shortlist", "checkout_label": "Start Enquiry",
        "brochure_label": "Services Brochure", "brochure_noun": "services brochure",
        "offer_noun": "product", "offer_noun_plural": "products",
        "lead_noun": "enquiry", "enquiry_label": "Enquire",
        "quote_label": "Request a Proposal", "callback_label": "Book a Callback",
        "support_label": "Support", "track_label": "Track Enquiry",
    },
    "menu": {
        "key": "kb_main",
        "body": "How can we help you today?",
        "footer": "Or type your question",
        "button_text": "Show Options",
        "buttons": [
            {"id": "menu_services", "title": "Our Services", "description": "What we offer",
             "section": "💼 Services", "icon": "💼", "sort_order": 0, "requires_feature": "offerings"},
            {"id": "menu_brochure", "title": "Services Brochure", "description": "Download our brochure",
             "section": "💼 Services", "icon": "📄", "sort_order": 1, "requires_feature": "brochure_pdf"},
            {"id": "menu_faq", "title": "FAQs", "description": "Common questions answered",
             "section": "ℹ️ Info", "icon": "❓", "sort_order": 2, "requires_feature": "faq"},
            {"id": "menu_proposal", "title": "Request a Proposal", "description": "Tell us about your goals",
             "section": "📞 Talk To Us", "icon": "📝", "sort_order": 3, "requires_feature": "quote",
             "flow": "get_quote"},
            {"id": "menu_callback", "title": "Book a Callback", "description": "Have us call you back",
             "section": "📞 Talk To Us", "icon": "📞", "sort_order": 4, "requires_feature": "callback",
             "flow": "book_callback"},
            {"id": "menu_support", "title": "Support", "description": "Existing client support",
             "section": "📞 Talk To Us", "icon": "🆘", "sort_order": 5, "flow": "raise_ticket"},
            {"id": "menu_human", "title": "Talk to Human", "description": "Chat with our team",
             "section": "📞 Talk To Us", "icon": "🙋", "sort_order": 6, "requires_feature": "human_handover", "flow": "book_callback"},
        ],
    },
    "intents": _intents(
        _GREETING,
        # package_details before service_enquiry: "scope of your compliance
        # service" is a package question, and on the "service" keyword tie the
        # earlier intent wins.
        {"name": "package_details", "examples": ["tell me about your tax planning package", "what is in the audit service"],
         "keywords": ["package", "detail", "details", "scope of", "deliverable", "deliverables", "included"],
         "requires_feature": "offering_details"},
        {"name": "service_enquiry", "examples": ["what do you do", "do you do tax planning"],
         # No bare "tax"/"compliance" — those belong to compliance_query; a
         # service question mentioning them still routes there, correctly.
         "keywords": ["service", "services", "what do you do", "advisory", "consulting", "planning",
                      "wealth", "audit"], "requires_feature": "offerings"},
        _PRICING,
        {"name": "roi_query", "examples": ["what returns do you typically see", "how much can I save on tax"],
         "keywords": ["roi", "return", "returns", "save", "saving", "benefit", "impact", "growth",
                      "portfolio", "market"], "requires_feature": "offering_details"},
        {"name": "quote_request", "examples": ["I need a proposal", "get me a quote"],
         "keywords": ["proposal", "quote", "quotation", "estimate", "engagement letter"],
         "requires_feature": "quote", "flow": "get_quote"},
        {"name": "callback_request", "examples": ["call me back", "arrange a consultation"],
         "keywords": ["call back", "callback", "phone call", "consultation", "speak to advisor"],
         "requires_feature": "callback", "flow": "book_callback"},
        # "compliance" appears only in phrases — the bare word scored 0.9 and
        # swallowed package/quote questions that happened to mention it.
        {"name": "compliance_query", "examples": ["what are the GST deadlines", "do you handle TDS"],
         "keywords": ["compliance calendar", "compliance query", "deadline",
                      "gst", "tds", "filing", "return filing", "notice", "tax", "advance tax"],
         "requires_feature": "faq"},
        _COMPLAINT,
        _SUPPORT,
        _CONTACT_HUMAN,
    ),
    "guardrails": {
        "never_state": ["returns or projections", "fee commitments", "tax outcomes", "client names",
                        "regulatory advice"],
        "never_state_notes": {
            "returns or projections": "Never project returns. Financial outcomes require a signed proposal.",
        },
        "escalate_keywords": ["urgent", "notice from income tax", "assessment", "audit", "deadline today",
                              "fraud", "complaint"],
        "escalation_message": "This needs an advisor — connecting you now.",
        "forbidden_terms": ["add to cart", "buy now", "checkout", "place order", "track order", "shipping"],
    },
    "business_hours": {
        "timezone": "Asia/Kolkata", "always_open": False,
        "open": "09:30", "close": "18:30", "open_days": [0, 1, 2, 3, 4, 5],
    },
}


# ── healthcare ────────────────────────────────────────────────────────────

_HEALTHCARE = {
    "vertical": "healthcare",
    "display_name": "CareBridge",
    "prompt": {
        "name": "Healthcare Provider",
        "tone": "compassionate and professional",
        "industry": "healthcare",
        "domain_specific_queries": "services, appointments, treatments, or general health information",
        "domain_specific_topics": "services, appointments, treatments, general health information, consultations",
        "support_trigger_topics": "medical emergencies, appointment scheduling, urgent clinical questions",
        "complex_topics": "treatment plans, chronic condition management, specialist referrals",
        "listing_type": "services or treatments",
        "keywords": [
            "appointment", "doctor", "treatment", "medical", "health", "clinic",
            "hospital", "consultation", "prescription", "symptom",
        ],
    },
    "features": {
        "cart": False, "buy_now": False, "orders": False, "track_order": False,
        "returns": False, "brochure_pdf": False, "distributors": False,
        "offerings": True, "offering_details": True,
        "lead_capture": True, "quote": False, "callback": True, "book_appointment": True,
        "handoff": True, "faq": True, "kb": True, "complaints": True, "campaigns": False,
        "human_handover": True,
    },
    "vocabulary": {
        "item_noun": "treatments", "item_noun_singular": "treatment",
        "browse_label": "Treatments", "catalog_label": "Treatment Guide",
        "catalog_noun": "treatment guide",
        "order_noun": "appointment", "order_noun_plural": "appointments",
        "cart_noun": "shortlist", "checkout_label": "Book Appointment",
        "brochure_label": "Treatment Guide", "brochure_noun": "treatment guide",
        "offer_noun": "service", "offer_noun_plural": "services",
        "lead_noun": "enquiry", "enquiry_label": "Enquire",
        "quote_label": "Get a Cost Estimate", "callback_label": "Request a Callback",
        "support_label": "Support", "track_label": "Track Appointment",
    },
    "menu": {
        "key": "kb_main",
        "body": "How can we help you today?",
        "footer": "Or type your question",
        "button_text": "Show Options",
        "buttons": [
            {"id": "menu_treatments", "title": "Treatments", "description": "What we treat",
             "section": "🩺 Care", "icon": "🩺", "sort_order": 0, "requires_feature": "offerings"},
            {"id": "menu_specialities", "title": "Specialities", "description": "Our departments",
             "section": "🩺 Care", "icon": "🏥", "sort_order": 1, "requires_feature": "offering_details"},
            {"id": "menu_appointment", "title": "Book Appointment", "description": "See a doctor",
             "section": "📞 Talk To Us", "icon": "📅", "sort_order": 2, "requires_feature": "book_appointment",
             "flow": "book_appointment"},
            {"id": "menu_callback", "title": "Request a Callback", "description": "Have us call you back",
             "section": "📞 Talk To Us", "icon": "📞", "sort_order": 3, "requires_feature": "callback",
             "flow": "book_callback"},
            {"id": "menu_grievance", "title": "Feedback", "description": "Share feedback or a complaint",
             "section": "🆘 Support", "icon": "📝", "sort_order": 4, "requires_feature": "complaints",
             "flow": "raise_ticket"},
            {"id": "menu_human", "title": "Talk to Human", "description": "Chat with our team",
             "section": "🆘 Support", "icon": "🙋", "sort_order": 5, "requires_feature": "human_handover", "flow": "book_callback"},
        ],
    },
    "intents": _intents(
        _GREETING,
        {"name": "service_enquiry", "examples": ["do you treat knee pain", "what is physiotherapy"],
         "keywords": ["treat", "treatment", "do you treat", "symptom", "condition", "speciality",
                      "physiotherapy", "consultation"], "requires_feature": "offerings"},
        {"name": "package_details", "examples": ["what is included in the health checkup", "how long is the surgery"],
         "keywords": ["included", "procedure", "duration", "recovery", "pre-op", "post-op", "detail"],
         "requires_feature": "offering_details"},
        _PRICING,
        {"name": "booking_inquiry", "examples": ["I want to book a doctor", "appointment for tomorrow"],
         "keywords": ["appointment", "book", "booking", "doctor", "slot", "available", "schedule"],
         "requires_feature": "book_appointment", "flow": "book_appointment"},
        {"name": "emergency", "examples": ["this is an emergency", "someone collapsed"],
         "keywords": ["emergency", "urgent", "collapsed", "unconscious", "bleeding", "chest pain",
                      "breathing", "severe pain", "ambulance", "critical"], "requires_feature": "handoff",
         "flow": "raise_ticket"},
        _COMPLAINT,
        _SUPPORT,
        _CONTACT_HUMAN,
    ),
    "guardrails": {
        "never_state": ["diagnoses", "treatment costs", "outcomes", "medication advice", "doctor names without consent"],
        "never_state_notes": {
            "diagnoses": "Never diagnose. Route to a doctor.",
            "treatment costs": "Costs vary by case. Share details and let the team confirm.",
        },
        "escalate_keywords": ["emergency", "chest pain", "collapsed", "unconscious", "bleeding heavily",
                              "breathing difficulty", "suicidal", "suicide", "overdose"],
        "escalation_message": "This sounds urgent — please call our 24x7 helpline. I'm also alerting a doctor now.",
        "forbidden_terms": ["add to cart", "buy now", "checkout", "place order", "track order", "shipping"],
    },
    "business_hours": {"timezone": "Asia/Kolkata", "always_open": True},
}


# ── generic ───────────────────────────────────────────────────────────────

_GENERIC = {
    "vertical": "generic",
    "display_name": "Support",
    "prompt": {
        # Matches the legacy COMPANY_TYPE_CONFIGS['generic'] entry.
        "name": "Generic",
        "tone": "helpful",
        "industry": "business",
        "domain_specific_queries": "products, services, pricing, or support",
        "domain_specific_topics": "products, services, pricing, support, information",
        "support_trigger_topics": "custom requests, complex inquiries, urgent issues",
        "complex_topics": "custom requirements, enterprise needs, complex issues",
        "listing_type": "products, services, or information",
        "keywords": ["product", "service", "price", "support", "information", "help"],
    },
    "features": {
        "cart": False, "buy_now": False, "orders": False, "track_order": False,
        "returns": False, "brochure_pdf": False, "distributors": False,
        "offerings": True, "offering_details": True,
        "lead_capture": True, "quote": False, "callback": True, "book_appointment": False,
        "handoff": True, "faq": True, "kb": True, "complaints": True, "campaigns": False,
        "human_handover": True,
    },
    "vocabulary": {
        "item_noun": "offerings", "item_noun_singular": "offering",
        "browse_label": "What We Offer", "catalog_label": "Brochure",
        "catalog_noun": "brochure",
        "order_noun": "request", "order_noun_plural": "requests",
        "cart_noun": "shortlist", "checkout_label": "Get Started",
        "brochure_label": "Brochure", "brochure_noun": "brochure",
        "offer_noun": "offer", "offer_noun_plural": "offers",
        "lead_noun": "enquiry", "enquiry_label": "Enquire",
        "quote_label": "Get a Quote", "callback_label": "Request a Callback",
        "support_label": "Support", "track_label": "Track Request",
    },
    "menu": {
        "key": "kb_main",
        "body": "What would you like help with?",
        "footer": "Or type your question directly",
        "button_text": "Show Options",
        "buttons": [
            {"id": "menu_offerings", "title": "What We Offer", "description": "Browse our offerings",
             "section": "General", "icon": "📋", "sort_order": 0, "requires_feature": "offerings"},
            {"id": "menu_faq", "title": "FAQs", "description": "Common questions",
             "section": "General", "icon": "❓", "sort_order": 1, "requires_feature": "faq"},
            {"id": "menu_callback", "title": "Request a Callback", "description": "Have us call you back",
             "section": "Talk To Us", "icon": "📞", "sort_order": 2, "requires_feature": "callback",
             "flow": "book_callback"},
            {"id": "menu_complaint", "title": "Raise a Complaint", "description": "Tell us what went wrong",
             "section": "Support", "icon": "📝", "sort_order": 3, "requires_feature": "complaints",
             "flow": "raise_ticket"},
            {"id": "menu_human", "title": "Talk to Human", "description": "Chat with our team",
             "section": "Support", "icon": "🙋", "sort_order": 4, "requires_feature": "human_handover", "flow": "book_callback"},
        ],
    },
    "intents": _intents(
        _GREETING,
        {"name": "service_enquiry", "examples": ["what do you offer", "tell me about your services"],
         "keywords": ["service", "services", "offer", "offerings", "what do you do"],
         "requires_feature": "offerings"},
        {"name": "faq", "examples": ["how does this work", "what are your timings"],
         "keywords": ["how", "what", "when", "policy", "policies", "faq"], "requires_feature": "faq"},
        {"name": "callback_request", "examples": ["call me back", "arrange a call"],
         "keywords": ["call back", "callback", "phone call", "speak to someone"],
         "requires_feature": "callback", "flow": "book_callback"},
        _COMPLAINT,
        _SUPPORT,
        _CONTACT_HUMAN,
    ),
}


VERTICAL_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "ecommerce": _ECOMMERCE,
    "it_software": _IT_SOFTWARE,
    "tours_travel": _TOURS_TRAVEL,
    "banking": _BANKING,
    "finance": _FINANCE,
    "healthcare": _HEALTHCARE,
    "generic": _GENERIC,
}


def get_vertical_defaults(vertical: str) -> Dict[str, Any]:
    """Deep copy of the default layer for a vertical (safe to mutate)."""
    layer = deepcopy(VERTICAL_DEFAULTS.get(vertical, VERTICAL_DEFAULTS["generic"]))
    # Commerce flows are grafted on here rather than declared in _ECOMMERCE so
    # they are defined after DEFAULT_FLOWS at module load. Gating stays with
    # requires_feature: a shop that turns buy_now off never surfaces the flow.
    if layer.get("vertical") == "ecommerce":
        layer["flows"] = deepcopy(COMMERCE_FLOWS)
    return layer


def list_verticals() -> List[str]:
    return sorted(VERTICAL_DEFAULTS)


# ── default flows (data, identical for every tenant unless overridden) ─────
# Flows are the reusable conversational skeletons. A tenant references them from
# its intents/menu by name; a tenant can override any of them by shipping a
# flow with the same name in clients/<id>/config.json.

def _ask(step_id, key, prompt, validate="", invalid="", max_attempts=3, optional=False) -> Dict[str, Any]:
    return {
        "id": step_id, "type": "ask", "key": key, "prompt": prompt,
        "validate": validate, "invalid_message": invalid, "max_attempts": max_attempts,
        "optional": optional,
    }


def _say(step_id, prompt) -> Dict[str, Any]:
    return {"id": step_id, "type": "say", "prompt": prompt}


_LEAD_STEPS = [
    _ask("ask_name", "name", "May I know your name?", validate="name:2",
         invalid="Could you share your name (at least 2 characters)?"),
    _ask("ask_phone", "phone", "What's your phone number?",
         validate="phone:10", invalid="That doesn't look like a valid phone number. Please try again."),
    _ask("ask_email", "email", "And your email address?",
         validate="email", invalid="That email doesn't look right. Please try again.", optional=True),
    _ask("ask_need", "need", "Briefly, what can we help you with?",
         validate="min_len:3", invalid="A few more words would help us route this correctly."),
]

_SAVE_LEAD = {
    "id": "save", "type": "save_lead",
    "collect_keys": ["name", "phone", "email", "need"],
    "lead_source": "",
    "next": "notify",
}

_NOTIFY = {
    "id": "notify", "type": "notify",
    "channels": [],   # empty = every active channel in profile.notifications
    "subject": "New enquiry from WhatsApp",
    "next": "done",
}

_DONE = {"id": "done", "type": "say", "prompt": "", "goto": ""}

DEFAULT_FLOWS: List[Dict[str, Any]] = [
    {
        "name": "get_quote",
        "intent": "quote_request",
        "requires_feature": "quote",
        "description": "Collect project details and send them to sales for a quote.",
        "start_message": "Happy to help with a quote. A few quick questions and our team will get back to you.",
        "success_message": "Thanks! Our team has your details and will contact you shortly.",
        "out_of_hours_variant": "book_callback",
        "steps": [
            _say("intro", "Happy to help with a quote. A few quick questions and our team will get back to you."),
            *_LEAD_STEPS,
            _ask("ask_project", "project", "What kind of project is this, and is there a timeline you have in mind?",
                 validate="min_len:5", optional=True,
                 invalid="A little more detail helps our team prepare."),
            # Not the shared _SAVE_LEAD: this flow asks one more question, and
            # collect_keys is a whitelist — project must be listed or it is
            # silently dropped from the saved lead.
            {**_SAVE_LEAD, "collect_keys": ["name", "phone", "email", "need", "project"]},
            _NOTIFY,
            {"id": "done", "type": "say",
             "prompt": "Thanks! Our team has your details and will contact you shortly."},
        ],
    },
    {
        "name": "enquire",
        "intent": "service_enquiry",
        "requires_feature": "lead_capture",
        "description": "General enquiry capture — no quote language.",
        "start_message": "Happy to help. A few quick questions and our team will follow up.",
        "success_message": "Thanks! Our team has your details and will reach out shortly.",
        "out_of_hours_variant": "book_callback",
        "steps": [
            _say("intro", "Happy to help. A few quick questions and our team will follow up."),
            *_LEAD_STEPS,
            _SAVE_LEAD,
            _NOTIFY,
            {"id": "done", "type": "say",
             "prompt": "Thanks! Our team has your details and will reach out shortly."},
        ],
    },
    {
        "name": "raise_ticket",
        "intent": "complaint",
        "requires_feature": "complaints",
        "description": "Raise a support ticket with full context for the agent.",
        "start_message": "I'm sorry about that. Let me capture the details so the right person picks it up.",
        "success_message": "Ticket raised. Our support team will get back to you shortly.",
        "out_of_hours_variant": "book_callback",
        "steps": [
            _say("intro", "I'm sorry about that. Let me capture the details so the right person picks it up."),
            *_LEAD_STEPS,
            _ask("ask_issue", "issue", "What exactly happened? Please share as much detail as you can.",
                 validate="min_len:5", invalid="A few more words will help us resolve this faster."),
            _ask("ask_urgency", "urgency", "How urgent is this? Reply *normal* or *urgent*.",
                 validate="min_len:3", optional=True, invalid="Just reply *normal* or *urgent*."),
            {"id": "save", "type": "save_lead",
             "collect_keys": ["name", "phone", "email", "issue", "urgency"],
             "lead_source": "complaint", "next": "notify"},
            {"id": "notify", "type": "notify", "channels": [],
             "subject": "Support ticket from WhatsApp", "next": "handoff"},
            {"id": "handoff", "type": "handoff", "handoff_reason": "support_ticket",
             "store_context": True, "next": "done"},
            {"id": "done", "type": "say",
             "prompt": "Ticket raised. Our support team will get back to you shortly."},
        ],
    },
    {
        "name": "book_callback",
        "intent": "callback_request",
        "requires_feature": "callback",
        "description": "Out-of-hours variant — collect details, promise a callback.",
        "start_message": "Sure — leave your details and we'll call you back.",
        "success_message": "Done! We'll call you back as soon as we're back in office.",
        "steps": [
            _say("intro", "Sure — leave your details and we'll call you back."),
            _ask("ask_name", "name", "May I know your name?", validate="name:2",
                 invalid="Could you share your name (at least 2 characters)?"),
            _ask("ask_phone", "phone", "What's the best number to reach you on?",
                 validate="phone:10",
                 invalid="That doesn't look like a valid phone number. Please try again."),
            _ask("ask_time", "preferred_time", "Any preferred time to call?",
                 validate="min_len:2", optional=True, invalid="Any time works — just type a time."),
            _ask("ask_need", "need", "What's this regarding?", validate="min_len:3",
                 invalid="A few more words will help us route this correctly."),
            {"id": "save", "type": "save_lead",
             "collect_keys": ["name", "phone", "preferred_time", "need"],
             "lead_source": "callback", "next": "notify"},
            _NOTIFY,
            {"id": "done", "type": "say",
             "prompt": "Done! We'll call you back as soon as we're back in office."},
        ],
    },
    {
        "name": "book_appointment",
        "intent": "booking_inquiry",
        "requires_feature": "book_appointment",
        "description": "Book a slot — a save_lead + notify variant.",
        "start_message": "Happy to book you in. A few quick questions.",
        "success_message": "Booked! Our team will confirm your slot shortly.",
        "steps": [
            _say("intro", "Happy to book you in. A few quick questions."),
            *_LEAD_STEPS,
            _ask("ask_slot", "preferred_slot", "What date and time suits you?", validate="min_len:3",
                 invalid="Please share a rough date and time."),
            {"id": "save", "type": "save_lead",
             "collect_keys": ["name", "phone", "email", "need", "preferred_slot"],
             "lead_source": "appointment", "next": "notify"},
            _NOTIFY,
            {"id": "done", "type": "say", "prompt": "Booked! Our team will confirm your slot shortly."},
        ],
    },
    {
        "name": "place_order",
        "intent": "place_order",
        "requires_feature": "buy_now",
        "description": "Commerce order entry — delegates to the cart service.",
        "success_message": "Your order is confirmed!",
        "steps": [
            {"id": "handoff_to_cart", "type": "handoff", "handoff_reason": "cart_checkout",
             "store_context": True, "next": "done"},
            {"id": "done", "type": "say", "prompt": "Your order is confirmed!"},
        ],
    },
    {
        "name": "track_order",
        "intent": "order_status",
        "requires_feature": "track_order",
        "description": "Commerce order tracking — delegates to the order service.",
        "success_message": "",
        "steps": [
            {"id": "handoff_to_orders", "type": "handoff", "handoff_reason": "order_tracking",
             "store_context": True, "next": "done"},
            {"id": "done", "type": "say", "prompt": ""},
        ],
    },
]

# Flows that only make sense for a shop. Kept OUT of DEFAULT_FLOWS on purpose:
# inheriting a "cart_checkout" step is exactly the cross-tenant leak the profile
# system exists to prevent. lint.lint_forbidden_terms fails the build if a
# commerce term ever reaches a non-commerce profile again.
COMMERCE_FLOWS: List[Dict[str, Any]] = [
    f for f in DEFAULT_FLOWS if f["name"] in ("place_order", "track_order")
]
DEFAULT_FLOWS: List[Dict[str, Any]] = [
    f for f in DEFAULT_FLOWS if f["name"] not in ("place_order", "track_order")
]
