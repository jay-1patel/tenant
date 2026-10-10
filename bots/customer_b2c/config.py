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
B2C_AWAITING_CALLBACK_TYPE = "B2C_AWAITING_CALLBACK_TYPE"
B2C_AWAITING_CALLBACK_DETAILS = "B2C_AWAITING_CALLBACK_DETAILS"

# ── System prompt used by the B2C assistant ──────────────────────────────────
B2C_SYSTEM_PROMPT = (
    "You are a friendly, helpful assistant for retail customers. You help with "
    "product information, nutrition details, recipe suggestions, order "
    "tracking, complaints, and shipping queries. Be warm, clear, and concise."
)

# ── Behavioural thresholds ───────────────────────────────────────────────────
# Phrases that explicitly request a human agent (handover trigger).
HUMAN_HANDOVER_PHRASES = [
    "human", "agent", "real person", "talk to a human", "speak to a human",
    "customer support", "representative",
]

# Fallback recipe list used when the query is generic / not DB-backed.
B2C_DEFAULT_RECIPES = [
    {"title": "Peanut Chikki Energy Bites", "ingredients": ["Peanut Chikki", "Jaggery", "Ghee"]},
    {"title": "Millet Breakfast Bowl", "ingredients": ["Millet Flakes", "Milk", "Honey"]},
    {"title": "Almond Nut Mix", "ingredients": ["Almonds", "Pistachios", "Dates"]},
]
