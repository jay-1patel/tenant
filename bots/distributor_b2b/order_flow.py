"""B2B Order Placement Flow (v2: image browsing + cart + checkout details).

Flow:

    DIST_ORDER_START      -> fetch products, show first product
    DIST_BROWSE_PRODUCTS  -> image + [Order Now] [Next] [View Cart]
    DIST_REVIEW_ORDER     -> cart summary + [Checkout] [Add More] [Cancel]
    DIST_ASK_NAME         -> collect customer name
    DIST_ASK_MOBILE       -> collect 10-digit mobile number
    DIST_ASK_ADDRESS      -> collect delivery address
    -> order placed (create_order with customer block) + payment placeholder

Design:
    * Cart persistence: the cart array lives in ``context["cart"]`` (stored in
      user_states.context_json by the orchestrator).
    * One product per message: WhatsApp allows max 3 reply buttons and button
      replies carry only the title, so "Order Now" always refers to the product
      currently being shown (``context["browsing_product_id"]``).
    * Product images are sent from ``products.media_url`` when available, with
      graceful fallback to text-only if no image is set.
    * MOQ: adding from the button uses max(moq, 1) as the initial quantity;
      the customer can change quantity later by typing a product name.
    * Customer details collected at checkout; payment step is a placeholder.

This module is pure B2B logic and is the only place that owns the order FSM.
The orchestrator never deals with cart/order details.
"""

import logging
import re

logger = logging.getLogger("b2b_order_flow")

CART_KEY = "cart"
BROWSING_KEY = "browsing_product_id"
CHECKOUT_KEY = "checkout"

# Button labels (WhatsApp button replies return only the title text).
BTN_ORDER_NOW = "Order Now"
BTN_NEXT = "Next"
BTN_VIEW_CART = "View Cart"
BTN_CHECKOUT = "Checkout"
BTN_ADD_MORE = "Add More"
BTN_CANCEL = "Cancel"
BTN_CHANGE_QTY = "Change Quantity"


def _sender():
    from services.whatsapp_sender import (
        send_text_message, send_list_menu, send_button_message, send_image_message,
    )
    return send_text_message, send_list_menu, send_button_message, send_image_message


def _tools():
    from . import tools
    return tools


def _states():
    from . import config
    return config


async def handle_order_message(wa_id: str, message: str, state: str, context: dict, tier: str) -> dict:
    """Route a message through the order FSM.

    Args:
        wa_id: Distributor WhatsApp ID.
        message: Incoming text (or button-reply title).
        state: Current FSM state (one of the DIST_* order states).
        context: Current context dict (holds the cart).
        tier: Distributor tier (for discounts).

    Returns:
        dict: {"new_state", "context", ...} to persist.
    """
    send_text_message, send_list_menu, send_button_message, send_image_message = _sender()
    tools = _tools()
    cfg = _states()

    message = (message or "").strip()
    context = context or {}
    cart = context.get(CART_KEY) or []

    # -- DIST_ORDER_START: kick off the flow -------------------------------
    if state == cfg.DIST_ORDER_START:
        products = tools.get_products()
        if not products:
            await send_text_message(wa_id, "Our product catalog is currently empty. Please try again later.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}
        return await _show_product(wa_id, context, products, index=0)

    # -- DIST_BROWSE_PRODUCTS: image + Order Now / Next / View Cart --------
    if state == cfg.DIST_BROWSE_PRODUCTS:
        if _is_cancel(message):
            context[CART_KEY] = []
            context.pop(BROWSING_KEY, None)
            await send_text_message(wa_id, "Order cancelled. Back to the main menu.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}

        lowered = message.lower()

        if message == BTN_ORDER_NOW or lowered in ("order", "add to cart"):
            product = _current_product(context, tools)
            if not product:
                products = tools.get_products()
                if not products:
                    await send_text_message(wa_id, "Our product catalog is currently empty.")
                    return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}
                return await _show_product(wa_id, context, products, index=0)
            cart = _add_to_cart(cart, product, qty=tools.get_moq(product))
            context[CART_KEY] = cart
            summary = _format_cart_summary(cart)
            await send_button_message(
                wa_id,
                f"✅ Added *{product['name']}* to your cart!\n\n{summary}\n\n"
                "Add more goodies or head to checkout? 👇",
                _browse_buttons(),
            )
            return {"new_state": cfg.DIST_BROWSE_PRODUCTS, "context": context}

        if message == BTN_NEXT or lowered in ("skip", "next product"):
            products = tools.get_products()
            if not products:
                await send_text_message(wa_id, "Our product catalog is currently empty.")
                return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}
            current_id = context.get(BROWSING_KEY)
            index = next((i for i, p in enumerate(products) if p.get("id") == current_id), -1)
            return await _show_product(wa_id, context, products, index=(index + 1) % len(products))

        if message == BTN_VIEW_CART or lowered in ("cart", "my cart", "review"):
            return await _show_review(wa_id, context, tier)

        # Typed free text: try to resolve as a product name/id and show it.
        product = _resolve_product(message)
        if product:
            context[BROWSING_KEY] = product.get("id")
            return await _show_product(wa_id, context, tools.get_products(),
                                       index=_index_of(tools.get_products(), product.get("id")))

        await send_button_message(
            wa_id,
            "Please use the buttons below, or type a product name to view it.",
            _browse_buttons(),
        )
        return {"new_state": cfg.DIST_BROWSE_PRODUCTS, "context": context}

    # -- DIST_SELECT_PRODUCTS (legacy text path): user picks a product -----
    if state == cfg.DIST_SELECT_PRODUCTS:
        if _is_done(message):
            return await _go_to_review(wa_id, context, tier)
        if _is_cancel(message):
            context[CART_KEY] = []
            await send_text_message(wa_id, "Order cancelled. Back to the main menu.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}

        product = _resolve_product(message)
        if not product:
            await send_text_message(wa_id, "I couldn't find that product. Please pick one from the catalog or type 'done' to review your cart.")
            return {"new_state": cfg.DIST_SELECT_PRODUCTS, "context": context}

        context[BROWSING_KEY] = product.get("id")
        moq = tools.get_moq(product)
        await send_text_message(
            wa_id,
            f"Selected: {product['name']} (min order {moq}).\n"
            "How many units would you like? (type a number, or 'done' to review cart)",
        )
        return {"new_state": cfg.DIST_SET_QUANTITIES, "context": context}

    # -- DIST_SET_QUANTITIES (legacy text path): user enters quantity ------
    if state == cfg.DIST_SET_QUANTITIES:
        if _is_done(message):
            return await _go_to_review(wa_id, context, tier)
        if _is_cancel(message):
            context[CART_KEY] = []
            await send_text_message(wa_id, "Order cancelled. Back to the main menu.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}

        product = _current_product(context, tools)
        if not product:
            await send_text_message(wa_id, "Please select a product first (or type 'done' to review cart).")
            return {"new_state": cfg.DIST_SELECT_PRODUCTS, "context": context}

        qty = _parse_qty(message)
        moq = tools.get_moq(product)
        if qty is None:
            await send_text_message(wa_id, "Please enter a valid quantity as a number (e.g. 50).")
            return {"new_state": cfg.DIST_SET_QUANTITIES, "context": context}
        if qty < moq:
            await send_text_message(
                wa_id,
                f"Minimum order for {product['name']} is {moq} units. Please enter at least {moq}.",
            )
            return {"new_state": cfg.DIST_SET_QUANTITIES, "context": context}

        cart = _add_to_cart(cart, product, qty=qty, replace=True)
        context[CART_KEY] = cart

        line = _format_cart_line(cart[-1])
        await send_text_message(
            wa_id,
            f"Added {line}.\n\nCart now has {len(cart)} item(s).\n"
            "Type another product name to add more, or 'done' to review the order.",
        )
        return {"new_state": cfg.DIST_SELECT_PRODUCTS, "context": context}

    # -- DIST_REVIEW_ORDER: show summary, ask to confirm/checkout ----------
    if state == cfg.DIST_REVIEW_ORDER:
        if _is_cancel(message):
            context[CART_KEY] = []
            context.pop(CHECKOUT_KEY, None)
            await send_text_message(wa_id, "Order cancelled. Back to the main menu.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}

        lowered = message.lower()
        if message == BTN_CHECKOUT or lowered in ("checkout", "confirm", "place order", "confirm order", "yes", "y", "ok"):
            return await _start_checkout(wa_id, context)

        if message == BTN_ADD_MORE or lowered in ("add more", "browse", "continue shopping"):
            products = tools.get_products()
            if not products:
                await send_text_message(wa_id, "Our product catalog is currently empty.")
                return {"new_state": cfg.DIST_BROWSE_PRODUCTS, "context": context}
            return await _show_product(wa_id, context, products, index=0)

        # Anything else: re-show the review.
        return await _show_review(wa_id, context, tier)

    # -- DIST_CONFIRM_ORDER (legacy): final confirmation -------------------
    if state == cfg.DIST_CONFIRM_ORDER:
        if _is_confirm(message):
            return await _start_checkout(wa_id, context)
        if _is_cancel(message):
            context[CART_KEY] = []
            await send_text_message(wa_id, "Order cancelled. Back to the main menu.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}
        return await _show_review(wa_id, context, tier)

    # -- Checkout detail collection ----------------------------------------
    if state == cfg.DIST_ASK_NAME:
        if _is_cancel(message):
            context.pop(CHECKOUT_KEY, None)
            await send_text_message(wa_id, "Checkout cancelled. Your cart is saved — type 'cart' to resume.")
            return {"new_state": cfg.DIST_REVIEW_ORDER, "context": context}
        if not message or len(message) < 2:
            await send_text_message(wa_id, "Please enter a valid name.")
            return {"new_state": cfg.DIST_ASK_NAME, "context": context}
        checkout = context.get(CHECKOUT_KEY) or {}
        checkout["name"] = message
        context[CHECKOUT_KEY] = checkout
        await send_text_message(wa_id, "Thanks! Now please enter your mobile number (10 digits).")
        return {"new_state": cfg.DIST_ASK_MOBILE, "context": context}

    if state == cfg.DIST_ASK_MOBILE:
        if _is_cancel(message):
            context.pop(CHECKOUT_KEY, None)
            await send_text_message(wa_id, "Checkout cancelled. Your cart is saved — type 'cart' to resume.")
            return {"new_state": cfg.DIST_REVIEW_ORDER, "context": context}
        mobile = re.sub(r"[\s\-+]", "", message)
        if not re.fullmatch(r"\d{10}", mobile) and not re.fullmatch(r"\d{11,13}", mobile):
            await send_text_message(wa_id, "That doesn't look like a valid mobile number. Please enter a 10-digit number.")
            return {"new_state": cfg.DIST_ASK_MOBILE, "context": context}
        checkout = context.get(CHECKOUT_KEY) or {}
        checkout["mobile"] = mobile
        context[CHECKOUT_KEY] = checkout
        await send_text_message(
            wa_id,
            "Got it. Finally, please enter your full delivery address "
            "(house/street, city, state, pincode).",
        )
        return {"new_state": cfg.DIST_ASK_ADDRESS, "context": context}

    if state == cfg.DIST_ASK_ADDRESS:
        if _is_cancel(message):
            context.pop(CHECKOUT_KEY, None)
            await send_text_message(wa_id, "Checkout cancelled. Your cart is saved — type 'cart' to resume.")
            return {"new_state": cfg.DIST_REVIEW_ORDER, "context": context}
        if not message or len(message) < 8:
            await send_text_message(wa_id, "Please enter a complete delivery address (house/street, city, state, pincode).")
            return {"new_state": cfg.DIST_ASK_ADDRESS, "context": context}
        checkout = context.get(CHECKOUT_KEY) or {}
        checkout["address"] = message
        context[CHECKOUT_KEY] = checkout
        return await _place_order(wa_id, context, tier)

    # Unknown state: fall back to start.
    await send_text_message(wa_id, "Let's start a new order.")
    return {"new_state": cfg.DIST_ORDER_START, "context": context}


# -- Product browsing helpers ------------------------------------------------

def _browse_buttons() -> list:
    return [
        {"type": "reply", "reply": {"id": "order_now", "title": BTN_ORDER_NOW}},
        {"type": "reply", "reply": {"id": "next_product", "title": BTN_NEXT}},
        {"type": "reply", "reply": {"id": "view_cart", "title": BTN_VIEW_CART}},
    ]


def _review_buttons() -> list:
    return [
        {"type": "reply", "reply": {"id": "checkout", "title": BTN_CHECKOUT}},
        {"type": "reply", "reply": {"id": "add_more", "title": BTN_ADD_MORE}},
        {"type": "reply", "reply": {"id": "cancel_order", "title": BTN_CANCEL}},
    ]


async def _show_product(wa_id: str, context: dict, products: list, index: int) -> dict:
    """Show one product: image (if any) + caption + buttons in ONE message."""
    send_text_message, _, send_button_message, send_image_message = _sender()
    cfg = _states()

    if not products:
        await send_text_message(wa_id, "Our product catalog is currently empty. Please try again later.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}

    index = index % len(products)
    product = products[index]
    context[BROWSING_KEY] = product.get("id")

    tools = _tools()
    moq = tools.get_moq(product)
    price = product.get("price")
    caption = f"*{product.get('name', 'Product')}*\n"
    short_desc = (product.get("short_description") or "").strip()
    description = (product.get("description") or "").strip()
    if short_desc:
        caption += f"{short_desc}\n"
    elif description:
        caption += f"{description[:120]}\n"
    if price:
        caption += f"Price: Rs {price}"
        if product.get("unit"):
            caption += f" per {product['unit']}"
        caption += "\n"
    mrp = (product.get("mrp") or "").strip()
    if mrp:
        caption += f"MRP: Rs {mrp}\n"
    caption += f"MOQ: {moq}\n"

    # Extra details: bulk discount tiers + nutritional facts.
    bulk = tools.parse_bulk_discount_tiers(product.get("bulk_discount_tiers"))
    if bulk:
        tier_parts = [f"{qty}+: {pct:.0f}% off" for qty, pct in sorted(bulk.items())]
        caption += "Bulk offers: " + ", ".join(tier_parts) + "\n"
    nutritional_days = product.get("lead_time_days") or 0
    if nutritional_days:
        caption += f"Delivery: {nutritional_days} day{'s' if int(nutritional_days) != 1 else ''}\n"
    if description and short_desc:
        caption += f"\n{description[:200]}\n"

    caption += f"\nTap *{BTN_ORDER_NOW}* to add to cart."

    media_url = (product.get("media_url") or "").strip()
    if media_url:
        # ONE API call: image as header + caption as body + buttons.
        # Falls back to text-only buttons if the combined send fails.
        sent = await send_button_message(
            wa_id, caption, _browse_buttons(),
            header_media={"type": "image", "image": {"link": media_url}},
        )
        if not sent:
            await send_button_message(wa_id, caption, _browse_buttons())
    else:
        await send_button_message(wa_id, caption, _browse_buttons())

    cart = context.get(CART_KEY) or []
    if cart:
        summary = _format_cart_summary(cart)
        await send_text_message(
            wa_id,
            f"🛒 Your cart so far:\n{summary}\n\nKeep browsing or tap *View Cart* to checkout 👇",
        )
    return {"new_state": cfg.DIST_BROWSE_PRODUCTS, "context": context}


def _index_of(products: list, product_id) -> int:
    for i, p in enumerate(products):
        if p.get("id") == product_id:
            return i
    return 0


def _current_product(context: dict, tools) -> dict:
    pid = context.get(BROWSING_KEY)
    if pid is None:
        return {}
    return tools.get_product_by_id(pid)


# -- Cart helpers ------------------------------------------------------------

def _resolve_product(message: str) -> dict:
    """Resolve a user's message to a product dict by id or name."""
    tools = _tools()
    lowered = (message or "").strip().lower()
    if lowered.isdigit():
        p = tools.get_product_by_id(int(lowered))
        if p:
            return p
    return tools.get_product_by_name(message)


def _parse_qty(message: str):
    try:
        return int(float(message.strip()))
    except (ValueError, TypeError):
        return None


def _add_to_cart(cart: list, product: dict, qty: int, replace: bool = False) -> list:
    """Add a product to the cart; merge if the same product already exists."""
    tools = _tools()
    pid = product.get("id")
    for i, item in enumerate(cart):
        if item.get("product_id") == pid:
            if replace:
                cart[i]["qty"] = qty
            else:
                cart[i]["qty"] += qty
            return cart
    cart.append(
        {
            "product_id": product.get("id"),
            "name": product.get("name"),
            "qty": qty,
            "price": float(product.get("price") or 0.0),
            "moq": tools.get_moq(product),
        }
    )
    return cart


def _format_cart_line(item: dict) -> str:
    return f"{item['name']} x {item['qty']}"


def _format_cart_summary(cart: list) -> str:
    if not cart:
        return "Your cart is empty."
    lines = [f"• {_format_cart_line(item)}" for item in cart]
    return "\n".join(lines)


def _is_done(message: str) -> bool:
    return message.lower() in ("done", "review", "finish", "no more", "confirm cart", "review order")


def _is_confirm(message: str) -> bool:
    return message.lower() in ("yes", "confirm", "place order", "confirm order", "y", "ok")


def _is_cancel(message: str) -> bool:
    return message.lower() in ("cancel", "no", "abort", "stop")


# -- Review / checkout --------------------------------------------------------

def _summarize_cart(cart: list, tier: str) -> dict:
    """Compute line totals and overall discount for the cart.

    Applies product bulk-discount tiers plus the distributor's tier discount.
    """
    tools = _tools()
    subtotal = 0.0
    lines = []
    for item in cart:
        qty = int(item.get("qty", 0))
        from .config import DIST_TIER_DISCOUNTS
        tier_pct = float(DIST_TIER_DISCOUNTS.get((tier or "Bronze").strip().title(), 0.0))
        unit_price = float(item.get("price", 0.0))
        # Re-check product bulk discount via a fresh product lookup if available.
        fresh = tools.get_product_by_id(item.get("product_id")) or tools.get_product_by_name(item.get("name", ""))
        if fresh:
            prod = tools.line_item_price(fresh, qty)
            unit_price = prod["unit_price"]
        line_total = unit_price * qty
        tier_discount = line_total * tier_pct
        net = line_total - tier_discount
        subtotal += net
        lines.append(
            {
                "name": item.get("name"),
                "qty": qty,
                "unit_price": round(unit_price, 2),
                "line_total": round(net, 2),
            }
        )
    return {
        "lines": lines,
        "subtotal": round(subtotal, 2),
        "tier": (tier or "Bronze").strip().title(),
        "tier_pct": tier_pct,
        "discount": round(sum(l["line_total"] * tier_pct / max(1.0 - tier_pct, 0.01) for l in lines), 2),
    }


async def _show_review(wa_id: str, context: dict, tier: str) -> dict:
    send_text_message, _, send_button_message, _ = _sender()
    cfg = _states()
    cart = context.get(CART_KEY) or []
    if not cart:
        products = _tools().get_products()
        if products:
            await send_text_message(wa_id, "Your cart is empty. Browse products to add one:")
            return await _show_product(wa_id, context, products, index=0)
        await send_text_message(wa_id, "Your cart is empty and the catalog is currently unavailable.")
        return {"new_state": cfg.DIST_BROWSE_PRODUCTS, "context": context}
    summary = _summarize_cart(cart, tier)
    lines = ["🛒 *Your Cart*", ""]
    for ln in summary["lines"]:
        lines.append(f"• {ln['name']} x {ln['qty']} — Rs {ln['line_total']:.2f}")
    lines.append("")
    lines.append(f"*Total: Rs {summary['subtotal']:.2f}* (incl. {summary['tier']} discount 🎉)")
    lines.append("")
    lines.append("Ready to checkout, or fancy adding more? 👇")
    await send_button_message(wa_id, "\n".join(lines), _review_buttons())
    return {"new_state": cfg.DIST_REVIEW_ORDER, "context": context}


async def _go_to_review(wa_id: str, context: dict, tier: str) -> dict:
    return await _show_review(wa_id, context, tier)


async def _start_checkout(wa_id: str, context: dict) -> dict:
    send_text_message, _, _, _ = _sender()
    cfg = _states()
    cart = context.get(CART_KEY) or []
    if not cart:
        await send_text_message(wa_id, "Your cart is empty. Nothing to order.")
        products = _tools().get_products()
        if products:
            return await _show_product(wa_id, context, products, index=0)
        return {"new_state": cfg.DIST_BROWSE_PRODUCTS, "context": context}
    context.pop(CHECKOUT_KEY, None)
    await send_text_message(wa_id, "Great! Let's collect your delivery details.\n\nWhat is your full name?")
    return {"new_state": cfg.DIST_ASK_NAME, "context": context}


async def _place_order(wa_id: str, context: dict, tier: str) -> dict:
    send_text_message, _, _, _ = _sender()
    tools = _tools()
    cfg = _states()

    cart = context.get(CART_KEY) or []
    summary = _summarize_cart(cart, tier)
    if not cart:
        await send_text_message(wa_id, "Your cart is empty. Nothing to order.")
        return {"new_state": cfg.DIST_BROWSE_PRODUCTS, "context": context}

    checkout = context.get(CHECKOUT_KEY) or {}

    # Build line items for the DB (name, qty, unit price after discounts),
    # plus the collected customer details as a "customer" block.
    items = [
        {"name": ln["name"], "qty": ln["qty"], "price": ln["unit_price"]}
        for ln in summary["lines"]
    ]
    if checkout:
        items.append({
            "customer": {
                "name": checkout.get("name", ""),
                "mobile": checkout.get("mobile", ""),
                "address": checkout.get("address", ""),
            }
        })

    order_number = tools.create_order(
        wa_id=wa_id,
        items=items,
        tier=summary["tier"],
        discount_applied=summary["discount"],
        source="whatsapp",
    )

    # Clear the cart now that the order is placed.
    context[CART_KEY] = []
    context.pop(BROWSING_KEY, None)
    context.pop(CHECKOUT_KEY, None)

    name = checkout.get("name", "")
    address = checkout.get("address", "")
    subtotal = summary["subtotal"]

    # Generate online payment link if tenant has active gateway
    payment_link_info = None
    try:
        from database import get_db_context
        tenant_id = None
        with get_db_context() as conn:
            dist_row = conn.execute("SELECT tenant_id FROM distributors WHERE wa_id = ?", (wa_id,)).fetchone()
            if dist_row and dist_row["tenant_id"]:
                tenant_id = dist_row["tenant_id"]
        if tenant_id:
            from services.payment_flow_service import generate_payment_link_for_order
            payment_link_info = await generate_payment_link_for_order(
                tenant_id=tenant_id,
                order_id=order_number,
                amount=float(subtotal),
                customer_phone=checkout.get("mobile", wa_id),
                customer_name=name,
                description=f"B2B Order {order_number}",
            )
    except Exception as e:
        logger.warning(f"Could not generate payment link for {order_number}: {e}")

    confirmation_lines = [
        f"🎉 Order confirmed! Thanks, {name}!",
        "",
        f"📦 Order number: *{order_number}*",
        f"📍 Delivering to: {address}",
        f"💰 Total: Rs {subtotal:.2f}",
        "",
    ]

    if payment_link_info and payment_link_info.get("payment_url"):
        confirmation_lines.append(f"💳 *Pay Online via Link:*")
        confirmation_lines.append(payment_link_info["payment_url"])
        confirmation_lines.append("\n(Or settle upon invoice/delivery as per agreed terms) 🙏")
    else:
        confirmation_lines.append(
            "💳 *Payment & Invoicing:* Our finance team will generate your GST invoice "
            "and contact you shortly to coordinate payment and dispatch. 🙏"
        )

    await send_text_message(wa_id, "\n".join(confirmation_lines))
    return {"new_state": cfg.B2B_MAIN_MENU_STATE, "context": context}
