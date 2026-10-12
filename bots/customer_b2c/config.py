"""
B2C Customer configuration.

Centralises the B2C persona's state-machine states, system prompt, and any
behavioural thresholds. Kept free of cross-module imports so it can be
imported safely at startup.
"""

# ── FSM state names ──────────────────────────────────────────────────────────
B2C_MAIN_MENU_STATE = "B2C_MAIN_MENU"
B2C_AWAITING_PRODUCT_QUERY = "B2C_AWAITING_PRODUCT_QUERY"
B2C_AWAITING_ORDER_ID = "B2C_AWAITING_ORDER_ID"
B2C_AWAITING_COMPLAINT_TYPE = "B2C_AWAITING_COMPLAINT_TYPE"
B2C_AWAITING_COMPLAINT_DESC = "B2C_AWAITING_COMPLAINT_DESC"
B2C_AWAITING_SHIPPING_QUERY = "B2C_AWAITING_SHIPPING_QUERY"
B2C_AWAITING_RECIPE_QUERY = "B2C_AWAITING_RECIPE_QUERY"

# ── System prompt used by the B2C assistant ──────────────────────────────────
B2C_SYSTEM_PROMPT = (
    "You are a friendly, helpful assistant for retail customers. You help with "
    "product information, nutrition details, recipe suggestions, order "
    "tracking, complaints, and shipping queries. Be warm, clear, and concise."
)

# ── Behavioural thresholds ───────────────────────────────────────────────────
# Phrases that explicitly request a human agent (handover trigger).
# Only EXPLICIT requests count — generic wording like "customer support" or
# a bare "agent" is a question the bot answers itself. The menu's
# "Talk to Human" row is the other allowed trigger.
HUMAN_HANDOVER_PHRASES = [
    "human handover", "handover to human", "hand over to human",
    "talk to human", "talk to a human", "talk to the human",
    "speak to human", "speak to a human", "speak to the human",
    "talk to agent", "talk to an agent",
    "speak to agent", "speak to an agent",
    "talk to someone", "speak to someone",
    "real person", "real human", "live person", "live agent",
    "human agent",
]

# Fallback recipe list used when the query is generic / not DB-backed.
B2C_DEFAULT_RECIPES = [
    {"title": "Peanut Chikki Energy Bites", "ingredients": ["Peanut Chikki", "Jaggery", "Ghee"]},
    {"title": "Millet Breakfast Bowl", "ingredients": ["Millet Flakes", "Milk", "Honey"]},
    {"title": "Almond Nut Mix", "ingredients": ["Almonds", "Pistachios", "Dates"]},
]
