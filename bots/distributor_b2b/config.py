"""B2B Distributor configuration.

Centralises the B2B persona's state-machine states, system prompt, and any
behavioural thresholds. Kept free of cross-module imports so it can be
imported safely at startup.
"""

# -- FSM state names (prefixed with B2B_ for legacy flows, DIST_ for the
#    new order/ticket flows to avoid any conflict with B2C states) ----------

# Legacy B2B states
B2B_MAIN_MENU_STATE = "B2B_MAIN_MENU"
B2B_AWAITING_ORDER_ID = "B2B_AWAITING_ORDER_ID"
B2B_AWAITING_ORDER_CATEGORY = "B2B_AWAITING_ORDER_CATEGORY"
B2B_AWAITING_ORDER_ITEMS = "B2B_AWAITING_ORDER_ITEMS"
B2B_AWAITING_PAYMENT = "B2B_AWAITING_PAYMENT"
B2B_AWAITING_COMPLAINT_DESC = "B2B_AWAITING_COMPLAINT_DESC"
B2B_AWAITING_CATALOG_QUERY = "B2B_AWAITING_CATALOG_QUERY"

# New order-placement FSM states
DIST_ORDER_START = "DIST_ORDER_START"
DIST_BROWSE_PRODUCTS = "DIST_BROWSE_PRODUCTS"
DIST_SELECT_PRODUCTS = "DIST_SELECT_PRODUCTS"
DIST_SET_QUANTITIES = "DIST_SET_QUANTITIES"
DIST_REVIEW_ORDER = "DIST_REVIEW_ORDER"
DIST_CONFIRM_ORDER = "DIST_CONFIRM_ORDER"
DIST_ASK_NAME = "DIST_ASK_NAME"
DIST_ASK_MOBILE = "DIST_ASK_MOBILE"
DIST_ASK_ADDRESS = "DIST_ASK_ADDRESS"

# New support-ticket FSM states
DIST_TICKET_START = "DIST_TICKET_START"
DIST_TICKET_CATEGORY = "DIST_TICKET_CATEGORY"
DIST_TICKET_DETAILS = "DIST_TICKET_DETAILS"
DIST_TICKET_CREATED = "DIST_TICKET_CREATED"

# New distributor FSM states (catalog / finance).
# NOTE: Names begin with B2B_ so the orchestrator's state-prefix logic
# (services.orchestrator.process_incoming_message) does not double-prefix
# them to B2B_B2B_*.
B2B_VIEW_CATALOG = "B2B_VIEW_CATALOG"
B2B_VIEW_PRICE_LIST = "B2B_VIEW_PRICE_LIST"
B2B_VIEW_SCHEMES = "B2B_VIEW_SCHEMES"
B2B_AWAITING_PAYMENT_PROOF = "B2B_AWAITING_PAYMENT_PROOF"
B2B_AWAITING_INVOICE_ORDER_ID = "B2B_AWAITING_INVOICE_ORDER_ID"
B2B_AWAITING_CALLBACK_TYPE = "B2B_AWAITING_CALLBACK_TYPE"
B2B_AWAITING_CALLBACK_DETAILS = "B2B_AWAITING_CALLBACK_DETAILS" 

# -- System prompt used by the B2B assistant --------------------------------
B2B_SYSTEM_PROMPT = (
    "You are a professional B2B assistant for distributors. You help with "
    "placing and tracking bulk orders, checking outstanding payments, "
    "resolving invoice queries, and connecting distributors to their assigned "
    "sales representatives. Be concise, courteous, and business-focused."
)

# -- Behavioural thresholds --------------------------------------------------
# Minimum payment amount that requires confirmation before proceeding.
B2B_PAYMENT_CONFIRM_THRESHOLD = 10000.0
# Fallback sales representative if none is assigned for a distributor.
B2B_DEFAULT_SALES_REP = {
    "name": "Rahul Sharma",
    "phone": "+91 98765 43210",
}

# -- Tier configuration ------------------------------------------------------
# Discount multiplier applied per distributor tier (fraction off list price).
# Bronze = 0%, Silver = 3%, Gold = 5%, Platinum = 8%.
DIST_TIER_DISCOUNTS = {
    "Bronze": 0.0,
    "Silver": 0.03,
    "Gold": 0.05,
    "Platinum": 0.08,
}

# Which tiers unlock the "Priority Support" row in the main menu.
DIST_PRIORITY_TIERS = {"Gold", "Platinum"}

# Standard delivery lead time (days) used when a product has none defined.
DIST_DEFAULT_LEAD_TIME_DAYS = 5
