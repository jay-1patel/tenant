import json
import re
import inspect
import threading
from typing import Any, Callable, Dict, List, Optional

from routing.config import logger


class Tool:
    def __init__(self, name: str, description: str, parameters: Dict, handler: Callable):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.handler = handler

    def to_openai_schema(self) -> Dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, **kwargs) -> Any:
        return self.handler(**kwargs)


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._tenant = threading.local()

    def set_tenant(self, tenant_id: str = ""):
        self._tenant.tenant_id = str(tenant_id or "")

    def current_tenant(self) -> str:
        return str(getattr(self._tenant, "tenant_id", "") or "")

    def register(self, tool: Tool):
        self._tools[tool.name] = tool
        logger.info(f"Tool registered: {tool.name}")

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def get_openai_schemas(self, tool_names: List[str] = None) -> List[Dict]:
        if tool_names is None:
            tool_names = self.list_tools()
        schemas = []
        for name in tool_names:
            tool = self._tools.get(name)
            if tool:
                schemas.append(tool.to_openai_schema())
        return schemas

    def execute_tool(self, name: str, arguments: Dict, tenant_id: str = None) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Tool '{name}' not found"}
        effective_tenant = str(tenant_id or self.current_tenant())
        try:
            parameters = inspect.signature(tool.handler).parameters
            if "tenant_id" in parameters:
                arguments = {**arguments, "tenant_id": effective_tenant}
            return tool.execute(**arguments)
        except Exception as e:
            logger.error(f"Tool '{name}' execution failed: {e}")
            return {"error": str(e)}


registry = ToolRegistry()


def _search_products(query: str, limit: int = 5, tenant_id: str = "") -> str:
    from ..database import search_products
    products = search_products(query, limit=limit, tenant_id=tenant_id)
    if not products:
        return json.dumps({"found": 0, "message": "No products found matching your query."})
    results = []
    for p in products:
        results.append({
            "name": p["name"],
            "description": p.get("short_description") or p.get("description", ""),
            "price": p.get("price", ""),
            "mrp": p.get("mrp", ""),
            "category": p.get("category", ""),
            "moq": p.get("moq", ""),
            "media_url": p.get("media_url", ""),
            "ingredients": p.get("ingredients", []),
            "nutritional_facts": p.get("nutritional_facts", ""),
        })
    return json.dumps({"found": len(results), "products": results})


def _get_product_details(product_name: str, tenant_id: str = "") -> str:
    from ..database import search_products
    products = search_products(product_name, limit=1, tenant_id=tenant_id)
    if not products:
        return json.dumps({"found": False, "message": f"Product '{product_name}' not found."})
    p = products[0]
    return json.dumps({
        "found": True,
        "product": {
            "name": p["name"],
            "description": p.get("description", ""),
            "short_description": p.get("short_description", ""),
            "price": p.get("price", ""),
            "mrp": p.get("mrp", ""),
            "category": p.get("category", ""),
            "unit": p.get("unit", ""),
            "moq": p.get("moq", ""),
            "media_url": p.get("media_url", ""),
            "ingredients": p.get("ingredients", []),
            "nutritional_facts": p.get("nutritional_facts", ""),
        }
    })


def _check_order_status(order_id: str = "", phone_number: str = "") -> str:
    """Order tracking v1: look up a specific order by number, or list the
    user's last 5 orders when only the phone number (wa_id) is given."""
    try:
        from backend.services import order_service
    except Exception:
        order_service = None

    if order_service:
        if order_id:
            for o in order_service.get_user_orders(phone_number or "", limit=50):
                if o.get("order_number", "").upper() == order_id.strip().upper():
                    return json.dumps({"found": True, "order": o})
            return json.dumps({"found": False,
                               "message": f"No order found with ID {order_id}."})
        if phone_number:
            orders = order_service.get_user_orders(phone_number, limit=5)
            if orders:
                return json.dumps({"found": True, "orders": orders})
            return json.dumps({"found": False,
                               "message": "You have no orders yet."})
    return json.dumps({
        "found": False,
        "message": "Order tracking is not connected yet. Please contact our team with your order details.",
        "order_id": order_id,
        "phone": phone_number,
    })


def _get_faq_answer(question: str, tenant_id: str = "") -> str:
    from ..database import get_db_context
    if not tenant_id:
        return json.dumps({"found": False, "message": "No tenant-scoped FAQ data available."})
    try:
        from shared.tenancy import store
        tenant = store.get_tenant(str(tenant_id)) or {}
    except Exception:
        tenant = {}
    allowed = {str(tenant_id), str(tenant.get("id") or ""), str(tenant.get("slug") or "")}
    allowed.discard("")
    marks = ",".join("?" for _ in allowed)
    with get_db_context() as conn:
        row = conn.execute(
            f"SELECT content, source_file FROM faq_dataset WHERE content LIKE ? AND tenant_id IN ({marks}) LIMIT 1",
            [f"%{question}%", *sorted(allowed)],
        ).fetchone()
    if row:
        return json.dumps({"found": True, "content": row["content"], "source_file": row["source_file"]})
    return json.dumps({"found": False, "message": "No FAQ found for that question."})


def _get_contact_details() -> str:
    from .bot_config import get_contact_details
    details = get_contact_details()
    sanitized = {k: v for k, v in details.items() if v}
    if not sanitized:
        return json.dumps({"found": False, "message": "No contact details are configured."})
    return json.dumps({"found": True, "contact_details": sanitized})


def _human_handover(reason: str = "", user_message: str = "") -> str:
    return json.dumps({
        "action": "escalate",
        "message": "I'll connect you with our team - they'll follow up here shortly.",
        "reason": reason,
    })


def _list_categories(tenant_id: str = "") -> str:
    from ..database import list_products
    categories = sorted({p.get("category") for p in list_products(active_only=True, limit=1000, tenant_id=tenant_id) if p.get("category")})
    rows = [(category,) for category in categories]
    categories = [r["category"] for r in rows if r["category"]]
    return json.dumps({"categories": categories, "count": len(categories)})


def _get_products_by_category(category: str, limit: int = 10, tenant_id: str = "") -> str:
    from ..database import get_products_by_category
    products = get_products_by_category(category, limit=limit, tenant_id=tenant_id)
    if not products:
        return json.dumps({"found": 0, "message": f"No products in category '{category}'."})
    results = []
    for p in products:
        results.append({
            "name": p["name"],
            "price": p.get("price", ""),
            "description": p.get("short_description", ""),
        })
    return json.dumps({"found": len(results), "category": category, "products": results})


def _calculate_margin(quantity: int = 1, product_id: int = None, product_name: str = "", tenant_id: str = "") -> str:
    """
    B2B Margin Calculator - Calculate profit, revenue, and margin for distributors.

    This is a WOW feature that helps distributors understand their potential earnings.
    It fetches real pricing data from the database and calculates comprehensive metrics.

    Args:
        quantity: Number of units/items (default 1)
        product_id: Optional specific product ID for precise calculations
        product_name: Product name to search for if product_id not provided

    Returns:
        JSON string with margin analysis including:
        - product_name, quantity
        - cost_price (distributor_price)
        - selling_price (mrp)
        - total_revenue, total_cost
        - total_profit
        - margin_percentage
        - profit_per_unit
        - recommendations
    """
    from ..database import get_product, search_products

    try:
        # Validate inputs
        if quantity <= 0:
            return json.dumps({
                "found": False,
                "message": "Quantity must be greater than 0. Please provide a valid quantity.",
                "example": "Try: calculate_margin(quantity=100, product_name='Chikki Spread')"
            })

        # Find product
        product = None
        if product_id:
            product = get_product(product_id, tenant_id=tenant_id)
        elif product_name:
            products = search_products(product_name, limit=1, tenant_id=tenant_id)
            if products:
                product = products[0]

        if not product:
            return json.dumps({
                "found": False,
                "message": f"Product not found. Please check the product name or ID.",
                "searched_for": {"product_id": product_id, "product_name": product_name},
                "suggestion": "Use search_products to find the correct product name first."
            })

        # Extract pricing data
        product_name = product.get("name", "Unknown Product")

        # Try to get distributor pricing, fallback to price field
        distributor_price_str = product.get("price", "0").replace("₹", "").replace("Rs.", "").replace(",", "").strip()
        mrp_str = product.get("mrp", product.get("price", "0")).replace("₹", "").replace("Rs.", "").replace(",", "").strip()

        try:
            distributor_price = float(distributor_price_str) if distributor_price_str else 0.0
            mrp = float(mrp_str) if mrp_str else 0.0
        except ValueError:
            return json.dumps({
                "found": False,
                "message": f"Pricing data not available for {product_name}.",
                "product": {"name": product_name, "raw_price": distributor_price_str, "raw_mrp": mrp_str}
            })

        if distributor_price <= 0 or mrp <= 0:
            return json.dumps({
                "found": False,
                "message": f"Valid pricing data not available for {product_name}.",
                "product": {"name": product_name, "distributor_price": distributor_price, "mrp": mrp}
            })

        # Perform margin calculations
        total_cost = distributor_price * quantity
        total_revenue = mrp * quantity
        total_profit = total_revenue - total_cost

        # Margin percentage (profit as percentage of revenue)
        margin_percentage = (total_profit / total_revenue * 100) if total_revenue > 0 else 0.0
        profit_per_unit = (mrp - distributor_price)

        # Generate business insights
        insights = []
        if margin_percentage >= 30:
            insights.append("✅ Excellent margin - Highly profitable for bulk orders")
        elif margin_percentage >= 20:
            insights.append("✅ Good margin - Suitable for distributor business")
        elif margin_percentage >= 10:
            insights.append("⚠️ Moderate margin - Consider larger quantities for better profitability")
        else:
            insights.append("⚠️ Low margin - Recommend negotiating bulk pricing or focusing on volume")

        # Volume recommendations
        if quantity < 50:
            volume_tip = "💡 Tip: Consider ordering 100+ units to maximize wholesale benefits"
        elif quantity < 200:
            volume_tip = "💡 Tip: Good volume! Consider 200+ units for better distributor margins"
        else:
            volume_tip = "💡 Excellent volume! You're getting optimal wholesale pricing"

        return json.dumps({
            "found": True,
            "product": {
                "id": product.get("id"),
                "name": product_name,
                "category": product.get("category", ""),
            },
            "order_quantity": quantity,
            "pricing": {
                "distributor_price": f"₹{distributor_price:.2f}",
                "mrp": f"₹{mrp:.2f}",
                "profit_per_unit": f"₹{profit_per_unit:.2f}",
            },
            "financials": {
                "total_cost": f"₹{total_cost:.2f}",
                "total_revenue": f"₹{total_revenue:.2f}",
                "total_profit": f"₹{total_profit:.2f}",
                "margin_percentage": f"{margin_percentage:.1f}%"
            },
            "insights": insights,
            "volume_recommendation": volume_tip,
            "summary": f"For {quantity} units of {product_name}: Your profit is ₹{total_profit:.2f} ({margin_percentage:.1f}% margin). {volume_tip}"
        }, indent=2)

    except Exception as e:
        logger.error(f"Margin calculation error: {e}")
        return json.dumps({
            "found": False,
            "message": f"Error calculating margin: {str(e)}",
            "error": str(e)
        })


_NUTRITION_STOP_WORDS = {
    "who", "what", "how", "can", "the", "for", "and", "are", "its", "not",
    "but", "all", "you", "your", "tell", "about", "some", "which", "also",
    "have", "does", "would", "could", "should", "want", "need", "like", "know",
    "ate", "eat", "eats", "if", "is", "of", "to", "in", "do", "did", "done",
    "am", "an", "why", "when", "where", "them", "their", "please", "thanks",
    "thank", "help", "info", "give", "gives", "given", "show", "shows",
    "looking", "look", "before", "after", "had", "have", "much", "many",
    "any", "then", "there", "here", "did", "was", "were", "been", "has",
}

_VARIANT_KEYWORDS = [
    "original", "classic", "peanut", "pistachio", "almond", "cashew",
    "assorted", "dry fruit", "toffee", "coconut", "signature", "tri combo",
]


def _load_nutrition_products(tenant_id: str = "") -> List[Dict]:
    """Parse this tenant's KB nutrition facts document into structured data."""
    from ..database import get_db_context
    if not tenant_id:
        return []
    try:
        from shared.tenancy import store
        tenant = store.get_tenant(str(tenant_id)) or {}
    except Exception:
        tenant = {}
    allowed = {str(tenant_id), str(tenant.get("id") or ""), str(tenant.get("slug") or "")}
    allowed.discard("")
    marks = ",".join("?" for _ in allowed)
    with get_db_context() as conn:
        row = conn.execute(
            f"SELECT content FROM knowledge_base WHERE title LIKE '%Nutrition%' AND tenant_id IN ({marks}) ORDER BY id LIMIT 1",
            sorted(allowed),
        ).fetchone()
    if not row or not row["content"]:
        return []

    text = row["content"]
    lines = text.split("\n")

    block_starts = []
    for i, line in enumerate(lines):
        if line.strip().startswith("Pack details:"):
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            if j >= 0:
                block_starts.append(j)

    products = []
    for idx, start in enumerate(block_starts):
        end = block_starts[idx + 1] if idx + 1 < len(block_starts) else len(lines)
        block = "\n".join(lines[start:end])
        name = lines[start].strip()

        piece_m = re.search(r"(\d+(?:\.\d+)?)\s*g\s+(?:per\s+piece|pieces?)\b", block, re.IGNORECASE)
        piece_weight = float(piece_m.group(1)) if piece_m else None

        energy_m = re.search(r"Energy\s*\(Kcal\)[^\d]*([\d.]+)", block, re.IGNORECASE)
        if not energy_m:
            continue
        energy = float(energy_m.group(1))

        per_piece_table = bool(
            re.search(r"Nutritional Facts\s*/\s*\d+\s*g\s*\(single piece\)", block, re.IGNORECASE)
        )

        if piece_weight and piece_weight > 0:
            if per_piece_table:
                energy_per_piece = energy
                energy_per_100g = energy * 100 / piece_weight
            else:
                energy_per_100g = energy
                energy_per_piece = energy * piece_weight / 100
        else:
            energy_per_100g = energy
            energy_per_piece = None

        def _nut(label: str) -> float:
            m = re.search(re.escape(label) + r"[^\d]*([\d.]+)", block, re.IGNORECASE)
            return float(m.group(1)) if m else None

        protein = _nut("Protein (g)")
        carbs = _nut("Carbohydrates (g)")
        sugar = _nut("Total Sugars (g)")
        fat = _nut("Total Fats (g)")
        fibre = _nut("Dietary fibre (g)")

        def _scale(value: float) -> float:
            if value is None:
                return None
            if per_piece_table:
                return round(value, 1)
            if piece_weight and piece_weight > 0:
                return round(value * piece_weight / 100, 1)
            return None

        products.append({
            "name": name,
            "piece_weight_g": piece_weight,
            "energy_per_100g_kcal": round(energy_per_100g, 1),
            "energy_per_piece_kcal": round(energy_per_piece, 1) if energy_per_piece is not None else None,
            "protein_per_piece_g": _scale(protein),
            "carbs_per_piece_g": _scale(carbs),
            "sugar_per_piece_g": _scale(sugar),
            "fat_per_piece_g": _scale(fat),
            "fibre_per_piece_g": _scale(fibre),
        })

    return products


def _match_nutrition_product(query: str, products: List[Dict]):
    q = query.lower()
    words = [w for w in re.findall(r"[a-z]{3,}", q) if w not in _NUTRITION_STOP_WORDS]
    best = None
    best_score = -1
    for p in products:
        name_l = p["name"].lower()
        score = sum(1 for w in words if w in name_l)
        for kw in _VARIANT_KEYWORDS:
            if kw in q and kw in name_l:
                score += 5
        if score > best_score:
            best_score = score
            best = p
    return best, best_score


def _get_nutrition_info(product: str = "", quantity: float = None, unit: str = "pieces", tenant_id: str = "") -> str:
    from ..database import search_products
    db_products = search_products(product or "", limit=3, tenant_id=tenant_id)
    for p in db_products:
        facts = (p.get("nutritional_facts") or "").strip()
        if facts:
            return json.dumps({
                "found": True,
                "product": p["name"],
                "nutritional_facts": facts,
                "ingredients": p.get("ingredients", []),
            })

    products = _load_nutrition_products(tenant_id)
    if not products:
        return json.dumps({"found": False, "message": "Nutrition data is not available right now."})

    matched, score = _match_nutrition_product(product or "", products)
    if not matched or score <= 0:
        return json.dumps({
            "found": False,
            "message": f"No nutrition data found for '{product}'. Try 'original millet chikki', 'peanut', 'pistachio', or 'assorted dry fruit'.",
            "available_products": [p["name"] for p in products[:6]],
        })

    piece_w = matched["piece_weight_g"] or 100
    per_piece = matched["energy_per_piece_kcal"] or (matched["energy_per_100g_kcal"] * piece_w / 100)
    per_100g = matched["energy_per_100g_kcal"]

    unit = (unit or "pieces").lower()
    if unit in ("g", "gram", "grams"):
        qty = float(quantity) if quantity else 100
        total = per_100g * qty / 100
        qty_label = f"{qty:g}g"
        answer_fact = (
            f"{matched['name']} has {per_100g} kcal per 100g "
            f"(about {round(per_piece, 1)} kcal per {piece_w:g}g piece). "
            f"{qty_label} is about {round(total, 1)} kcal."
        )
    else:
        qty = float(quantity) if quantity else 1
        total = per_piece * qty
        qty_label = "1 piece" if qty == 1 else f"{int(qty)} pieces"
        answer_fact = (
            f"{matched['name']} has about {round(per_piece, 1)} kcal per {piece_w:g}g piece "
            f"({per_100g} kcal per 100g). "
            f"{qty_label} = about {round(total, 1)} kcal."
        )

    return json.dumps({
        "found": True,
        "product": matched["name"],
        "piece_weight_g": piece_w,
        "energy_per_100g_kcal": per_100g,
        "energy_per_piece_kcal": round(per_piece, 1),
        "quantity": qty,
        "unit": "g" if unit in ("g", "gram", "grams") else "pieces",
        "total_kcal": round(total, 1),
        "protein_per_piece_g": matched.get("protein_per_piece_g"),
        "carbs_per_piece_g": matched.get("carbs_per_piece_g"),
        "sugar_per_piece_g": matched.get("sugar_per_piece_g"),
        "fat_per_piece_g": matched.get("fat_per_piece_g"),
        "fibre_per_piece_g": matched.get("fibre_per_piece_g"),
        "answer_fact": answer_fact,
    })


def register_default_tools():
    registry.register(Tool(
        name="search_products",
        description="Search for products by name, keyword, or description. Use when the user asks about products, pricing, availability, or wants to find something specific.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query for product name, description, or keywords"},
                "limit": {"type": "integer", "description": "Max results to return (default 5)", "default": 5},
            },
            "required": ["query"],
        },
        handler=_search_products,
    ))

    registry.register(Tool(
        name="get_product_details",
        description="Get detailed information about a specific product by name. Use when the user asks about a particular product.",
        parameters={
            "type": "object",
            "properties": {
                "product_name": {"type": "string", "description": "Name or partial name of the product"},
            },
            "required": ["product_name"],
        },
        handler=_get_product_details,
    ))

    registry.register(Tool(
        name="get_nutrition_info",
        description=(
            "Get official nutrition facts (calories per 100g and per piece) for a TrooGood product and compute "
            "the total for the quantity the user ate. Use when the user asks how many calories/energy, protein, "
            "carbs, etc. are in a chikki, or how much nutrition a portion has (e.g. 'I ate a millet chikki', "
            "'calories in 2 peanut chikkis', 'nutrition in 100g of chikki')."
        ),
        parameters={
            "type": "object",
            "properties": {
                "product": {"type": "string", "description": "Product name or keyword (e.g. 'original millet chikki', 'peanut', 'pistachio', 'assorted dry fruit', 'classic'). For a plain 'millet chikki' use 'original millet chikki'."},
                "quantity": {"type": "number", "description": "How much the user ate, in the given unit. Default 1 piece."},
                "unit": {"type": "string", "enum": ["pieces", "g"], "description": "Unit for quantity: 'pieces' (count of chikkis) or 'g' (grams)."},
            },
            "required": ["product"],
        },
        handler=_get_nutrition_info,
    ))

    registry.register(Tool(
        name="check_order_status",
        description="Check the status of an order by order ID or phone number. Use when the user asks about their order.",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "Order ID or reference number"},
                "phone_number": {"type": "string", "description": "Phone number associated with the order"},
            },
            "required": [],
        },
        handler=_check_order_status,
    ))

    registry.register(Tool(
        name="get_faq_answer",
        description="Get an answer from the FAQ database. Use for common questions about policies, shipping, returns, payments, etc.",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to look up in the FAQ database"},
            },
            "required": ["question"],
        },
        handler=_get_faq_answer,
    ))

    registry.register(Tool(
        name="get_contact_details",
        description="Return the business contact details configured for this bot. Use when the user asks for phone, email, website, address, or location.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_get_contact_details,
    ))

    registry.register(Tool(
        name="human_handover",
        description="Escalate the conversation to a human agent. Use when the user is frustrated, has a complaint, or needs help you cannot provide.",
        parameters={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Reason for escalation"},
                "user_message": {"type": "string", "description": "The user's last message that triggered escalation"},
            },
            "required": [],
        },
        handler=_human_handover,
    ))

    registry.register(Tool(
        name="list_categories",
        description="List all available product categories. Use when the user wants to browse or see what categories are available.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=_list_categories,
    ))

    registry.register(Tool(
        name="get_products_by_category",
        description="Get all products in a specific category. Use when the user wants to see products from a particular category.",
        parameters={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "Category name"},
                "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
            },
            "required": ["category"],
        },
        handler=_get_products_by_category,
    ))

    registry.register(Tool(
        name="calculate_margin",
        description=(
            "B2B Margin Calculator - WOW feature for distributors! Calculate profit, revenue, and margin percentages "
            "for bulk orders. Use when user asks about profit, earnings, margin, business calculations, or "
            "'how much will I make'. Provides comprehensive financial analysis with business insights."
        ),
        parameters={
            "type": "object",
            "properties": {
                "quantity": {"type": "integer", "description": "Number of units/items for margin calculation"},
                "product_id": {"type": "integer", "description": "Specific product ID for precise calculations"},
                "product_name": {"type": "string", "description": "Product name to search for if product_id not provided"},
            },
            "required": ["quantity"],
        },
        handler=_calculate_margin,
    ))

    logger.info(f"Registered {len(registry.list_tools())} default tools")
