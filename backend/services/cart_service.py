"""
Unified cart service (Phase 1) — single source of truth for shopping carts.

Storage: SQLite `carts` + `cart_items` tables (survives restarts, safe with
multiple workers). Totals are always COMPUTED from items, never stored.

All prices are floats (INR). `price_at_add` is informational/display only;
checkout revalidates against the live products table (see order_service).

Button contract: see docs/cart_contract.md. parse_shop_button() maps both the
canonical b2c_* IDs and legacy menu_*/checkout_confirm IDs to one action set.
"""
import json
import logging
import re
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# shared.tenancy lives at the repo root, not next to this file.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.tenancy.gating import guard_result  # noqa: E402


def _gate(wa_id: str, feature: str = "cart"):
    """Refusal payload when this user's tenant has commerce switched off.

    Menus already hide the cart; this is the real gate, so typing the command
    or hitting a stale button still gets a polite refusal instead of a cart.
    """
    return guard_result(wa_id, feature)

logger = logging.getLogger("cart_service")

CART_TTL_DAYS = 7
CHECKOUT_TTL_MINUTES = 15


def _utcnow() -> datetime:
    return datetime.utcnow()


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _db():
    """Lazy import so kb/ can use this service without import-order issues."""
    import sys, os
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    import database as db
    return db


def _tenant_for(wa_id: str):
    """Tenant that owns this conversation. user_states is stamped by the
    webhook before cart/checkout runs, so one indexed read per write."""
    try:
        from shared.tenancy.resolver import resolve_tenant_for_user
        return resolve_tenant_for_user(wa_id)
    except Exception:
        return None


# ── Price parsing (products.price is TEXT) ──────────────────────────────────

_NUM_RE = re.compile(r"[\d,]+(?:\.\d+)?")


def parse_price(value) -> float:
    """Defensively parse a price that may be '₹1,299.50', '1299', 1299.0, None."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    m = _NUM_RE.search(str(value).replace("₹", ""))
    if not m:
        return 0.0
    try:
        return round(float(m.group(0).replace(",", "")), 2)
    except ValueError:
        return 0.0


# ── Core cart operations ─────────────────────────────────────────────────────

def get_cart(wa_id: str) -> list:
    """Return items as [{product_id, name, qty, price_at_add}] (empty if none/expired)."""
    db = _db()
    try:
        with db.get_db_context() as conn:
            row = conn.execute(
                "SELECT c.id, c.expires_at FROM carts c WHERE c.wa_id = ?", (wa_id,)
            ).fetchone()
            if not row:
                return []
            if row["expires_at"] <= _ts(_utcnow()):
                conn.execute("DELETE FROM carts WHERE id = ?", (row["id"],))
                return []
            items = conn.execute(
                """SELECT ci.product_id, COALESCE(p.name, 'Product') AS name,
                          ci.qty, ci.price_at_add
                     FROM cart_items ci LEFT JOIN products p ON p.id = ci.product_id
                     WHERE ci.cart_id = ? ORDER BY ci.added_at, ci.id""",
                (row["id"],),
            ).fetchall()
            return [
                {
                    "product_id": it["product_id"],
                    "name": it["name"],
                    "qty": it["qty"],
                    "price_at_add": it["price_at_add"],
                }
                for it in items
            ]
    except Exception as e:
        logger.error(f"CART_READ_FAIL | wa_id={wa_id} | {e}")
        return []


def get_or_create_active_cart(wa_id: str) -> dict:
    """Get or create an active cart for the user. Returns dict with cart info."""
    blocked = _gate(wa_id)
    if blocked:
        return blocked
    db = _db()
    try:
        with db.get_db_context() as conn:
            now = _utcnow()
            expires = _ts(now + timedelta(days=CART_TTL_DAYS))
            row = conn.execute(
                "SELECT id, wa_id, created_at, updated_at, expires_at FROM carts WHERE wa_id = ?", (wa_id,)
            ).fetchone()
            if not row:
                cur = conn.execute(
                    "INSERT INTO carts (wa_id, created_at, updated_at, expires_at, tenant_id) VALUES (?, ?, ?, ?, ?)",
                    (wa_id, _ts(now), _ts(now), expires, _tenant_for(wa_id)),
                )
                cart_id = cur.lastrowid
                return {
                    "id": cart_id,
                    "wa_id": wa_id,
                    "status": "active",
                    "created_at": _ts(now),
                    "updated_at": _ts(now),
                    "expires_at": expires,
                }
            if row["expires_at"] <= _ts(now):
                conn.execute("DELETE FROM carts WHERE id = ?", (row["id"],))
                cur = conn.execute(
                    "INSERT INTO carts (wa_id, created_at, updated_at, expires_at, tenant_id) VALUES (?, ?, ?, ?, ?)",
                    (wa_id, _ts(now), _ts(now), expires, _tenant_for(wa_id)),
                )
                cart_id = cur.lastrowid
                return {
                    "id": cart_id,
                    "wa_id": wa_id,
                    "status": "active",
                    "created_at": _ts(now),
                    "updated_at": _ts(now),
                    "expires_at": expires,
                }
            return {
                "id": row["id"],
                "wa_id": row["wa_id"],
                "status": "active",
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "expires_at": row["expires_at"],
            }
    except Exception as e:
        logger.error(f"CART_GET_OR_CREATE_FAIL | wa_id={wa_id} | {e}")
        return {"status": "error", "error": str(e)}


def get_cart_items(cart_id: int) -> list:
    """Return cart items for a specific cart_id."""
    db = _db()
    try:
        with db.get_db_context() as conn:
            items = conn.execute(
                """SELECT ci.product_id, COALESCE(p.name, 'Product') AS name,
                          ci.qty, ci.price_at_add, ci.added_at
                     FROM cart_items ci LEFT JOIN products p ON p.id = ci.product_id
                     WHERE ci.cart_id = ? ORDER BY ci.added_at, ci.id""",
                (cart_id,),
            ).fetchall()
            return [
                {
                    "product_id": it["product_id"],
                    "name": it["name"],
                    "qty": it["qty"],
                    "price_at_add": it["price_at_add"],
                    "added_at": it["added_at"],
                }
                for it in items
            ]
    except Exception as e:
        logger.error(f"CART_GET_ITEMS_FAIL | cart_id={cart_id} | {e}")
        return []


def add_to_cart(wa_id: str, product: dict, quantity: int = 1) -> dict:
    """Add a product (dict with id, name, price, media_url). Re-add increments qty."""
    blocked = _gate(wa_id)
    if blocked:
        return blocked
    db = _db()
    product_id = product.get("id")
    if product_id is None:
        return {"ok": False, "error": "missing_product_id"}
    qty = max(1, int(quantity or 1))
    price = parse_price(product.get("price"))
    try:
        with db.get_db_context() as conn:
            cart_id = _upsert_cart_row(conn, wa_id)
            conn.execute(
                """INSERT INTO cart_items (cart_id, product_id, qty, price_at_add, added_at, tenant_id)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cart_id, product_id)
                   DO UPDATE SET qty = qty + excluded.qty,
                                 price_at_add = excluded.price_at_add""",
                (cart_id, product_id, qty, price, _ts(_utcnow()), _tenant_for(wa_id)),
            )
            # Get the updated item
            row = conn.execute(
                "SELECT qty FROM cart_items WHERE cart_id = ? AND product_id = ?",
                (cart_id, product_id),
            ).fetchone()
        return {"ok": True, "item": {"product_id": product_id, "qty": row["qty"] if row else qty}}
    except Exception as e:
        logger.error(f"CART_ADD_FAIL | wa_id={wa_id} | product={product_id} | {e}")
        return {"ok": False, "error": str(e)}


def set_qty(wa_id: str, product_id: int, qty: int) -> dict:
    """Set exact quantity; qty <= 0 removes the item."""
    blocked = _gate(wa_id)
    if blocked:
        return blocked
    db = _db()
    try:
        with db.get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM carts WHERE wa_id = ?", (wa_id,)
            ).fetchone()
            if not row:
                return {"ok": True, "removed": True}
            if qty is None or int(qty) <= 0:
                conn.execute(
                    "DELETE FROM cart_items WHERE cart_id = ? AND product_id = ?",
                    (row["id"], product_id),
                )
            else:
                conn.execute(
                    "UPDATE cart_items SET qty = ? WHERE cart_id = ? AND product_id = ?",
                    (int(qty), row["id"], product_id),
                )
            _touch_cart(conn, wa_id)
        return {"ok": True}
    except Exception as e:
        logger.error(f"CART_SETQTY_FAIL | wa_id={wa_id} | product={product_id} | {e}")
        return {"ok": False, "error": str(e)}


def remove_item(wa_id: str, product_id: int) -> dict:
    return set_qty(wa_id, product_id, 0)


def clear_cart(wa_id: str) -> int:
    """Clear the user's cart. Returns number of items removed."""
    if _gate(wa_id):
        return 0
    db = _db()
    try:
        with db.get_db_context() as conn:
            row = conn.execute(
                "SELECT id FROM carts WHERE wa_id = ?", (wa_id,)
            ).fetchone()
            if not row:
                return 0
            count = conn.execute(
                "DELETE FROM cart_items WHERE cart_id = ?", (row["id"],)
            ).rowcount
            conn.execute("DELETE FROM carts WHERE wa_id = ?", (wa_id,))
            return count
    except Exception as e:
        logger.error(f"CART_CLEAR_FAIL | wa_id={wa_id} | {e}")
        return 0


def cart_total(wa_id: str) -> float:
    return round(sum(it["qty"] * it["price_at_add"] for it in get_cart(wa_id)), 2)


def cart_count(wa_id: str) -> int:
    return sum(it["qty"] for it in get_cart(wa_id))


def cart_summary(wa_id: str) -> dict:
    """Return a summary dict with total_items and total_amount."""
    blocked = _gate(wa_id)
    if blocked:
        return blocked
    items = get_cart(wa_id)
    total_items = sum(it["qty"] for it in items)
    total_amount = round(sum(it["qty"] * it["price_at_add"] for it in items), 2)
    return {
        "total_items": total_items,
        "total_amount": total_amount,
        "items": items,
    }


def format_cart_text(wa_id: str) -> str:
    """Human-readable cart summary for WhatsApp."""
    items = get_cart(wa_id)
    if not items:
        return "Your cart is empty."
    lines = ["*Your Cart:*", ""]
    for it in items:
        line_total = it["qty"] * it["price_at_add"]
        lines.append(
            f"• {it['name']} × {it['qty']} @ ₹{it['price_at_add']:.2f}  → ₹{line_total:.2f}"
        )
    lines += ["", f"*Total: ₹{cart_total(wa_id):.2f}*", "",
              "_Final prices refresh at checkout._"]
    return "\n".join(lines)


# ── Checkout sessions (Phase 2) ──────────────────────────────────────────────

def start_checkout(wa_id: str) -> dict:
    """Freeze the cart into an active checkout session (15-min TTL)."""
    blocked = _gate(wa_id)
    if blocked:
        return blocked
    db = _db()
    items = get_cart(wa_id)
    if not items:
        return {"ok": False, "error": "empty_cart"}
    session_id = str(uuid.uuid4())
    now = _utcnow()
    expires = _ts(now + timedelta(minutes=CHECKOUT_TTL_MINUTES))
    try:
        with db.get_db_context() as conn:
            conn.execute(
                """INSERT INTO checkout_sessions
                       (id, wa_id, cart_snapshot_json, status, state, created_at, expires_at, tenant_id)
                   VALUES (?, ?, ?, 'active', 'name', ?, ?, ?)""",
                (session_id, wa_id, json.dumps(items), _ts(now), expires, _tenant_for(wa_id)),
            )
        return {"ok": True, "session": {"id": session_id, "state": "name"}, "snapshot": {"items": items}}
    except Exception as e:
        logger.error(f"CHECKOUT_START_FAIL | wa_id={wa_id} | {e}")
        return {"ok": False, "error": str(e)}


def get_session(session_id: str) -> dict | None:
    db = _db()
    try:
        with db.get_db_context() as conn:
            row = conn.execute(
                "SELECT * FROM checkout_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row:
                result = dict(row)
                result["order_draft_json"] = json.loads(result.get("order_draft_json") or "{}")
                result["cart_snapshot_json"] = json.loads(result.get("cart_snapshot_json") or "[]")
                return result
            return None
    except Exception as e:
        logger.error(f"CHECKOUT_GET_FAIL | session={session_id} | {e}")
        return None


def get_active_checkout(wa_id: str) -> dict | None:
    """Get the active checkout session for a user."""
    db = _db()
    try:
        with db.get_db_context() as conn:
            row = conn.execute(
                """SELECT * FROM checkout_sessions
                   WHERE wa_id = ? AND status = 'active'
                   ORDER BY created_at DESC LIMIT 1""",
                (wa_id,),
            ).fetchone()
            if row:
                result = dict(row)
                result["order_draft_json"] = json.loads(result.get("order_draft_json") or "{}")
                result["cart_snapshot_json"] = json.loads(result.get("cart_snapshot_json") or "[]")
                return result
            return None
    except Exception as e:
        logger.error(f"CHECKOUT_GET_ACTIVE_FAIL | wa_id={wa_id} | {e}")
        return None


def update_checkout(wa_id: str, state: str = None, order_draft: dict = None) -> dict | None:
    """Update checkout session state and/or order_draft."""
    db = _db()
    try:
        with db.get_db_context() as conn:
            session = get_active_checkout(wa_id)
            if not session:
                return None
            
            updates = []
            params = []
            if state is not None:
                updates.append("state = ?")
                params.append(state)
            if order_draft is not None:
                updates.append("order_draft_json = ?")
                params.append(json.dumps(order_draft))
            
            if not updates:
                # Return session with parsed order_draft_json
                session["order_draft_json"] = json.loads(session.get("order_draft_json") or "{}")
                return session
            
            params.append(session["id"])
            conn.execute(
                f"UPDATE checkout_sessions SET {', '.join(updates)} WHERE id = ?",
                params,
            )
            
            row = conn.execute(
                "SELECT * FROM checkout_sessions WHERE id = ?", (session["id"],)
            ).fetchone()
            if row:
                result = dict(row)
                result["order_draft_json"] = json.loads(result.get("order_draft_json") or "{}")
                return result
            return None
    except Exception as e:
        logger.error(f"CHECKOUT_UPDATE_FAIL | wa_id={wa_id} | {e}")
        return None


def cancel_session(session_id: str, reason: str = "cancelled") -> None:
    db = _db()
    try:
        with db.get_db_context() as conn:
            conn.execute(
                "UPDATE checkout_sessions SET status='cancelled' WHERE id = ? AND status='active'",
                (session_id,),
            )
        logger.info(f"CHECKOUT_CANCELLED | session={session_id} | reason={reason}")
    except Exception as e:
        logger.error(f"CHECKOUT_CANCEL_FAIL | session={session_id} | {e}")


def confirm_order(
    wa_id: str,
    name: str = None,
    mobile: str = None,
    address: str = None,
    pincode: str = None,
    idempotency_key: str = None,
    payment_method: str = "cod"
) -> dict:
    """Create an order from the active checkout session or directly from cart."""
    blocked = _gate(wa_id)
    if blocked:
        return blocked
    db = _db()
    
    # Get the active checkout session
    session = get_active_checkout(wa_id)
    session_id = session["id"] if session else None
    
    # Use cart snapshot from session if available, otherwise current cart
    if session and session.get("cart_snapshot_json"):
        items = session["cart_snapshot_json"]
    else:
        items = get_cart(wa_id)
    
    if not items:
        return {"ok": False, "error": "no_cart"}
    
    # Prepare items for order_service
    order_items = [
        {
            "product_id": it["product_id"],
            "name": it["name"],
            "qty": it["qty"],
            "price": it["price_at_add"],
        }
        for it in items
    ]
    
    # Build order_draft from params or session
    order_draft = {}
    if name:
        order_draft["name"] = name
    if mobile:
        order_draft["mobile"] = mobile
    if address:
        order_draft["address"] = address
    if pincode:
        order_draft["pincode"] = pincode
    if payment_method:
        order_draft["payment_method"] = payment_method
    
    # If session exists, merge with session's order_draft
    if session and session.get("order_draft_json"):
        try:
            session_draft = session["order_draft_json"]
            if isinstance(session_draft, str):
                session_draft = json.loads(session_draft)
            order_draft = {**session_draft, **order_draft}
        except Exception:
            pass
    
    # Generate idempotency key if not provided
    if not idempotency_key:
        idempotency_key = session_id if session else str(uuid.uuid4())
    
    try:
        from backend.services.order_service import create_order, OrderError
    except Exception as e:
        logger.error(f"Failed to import order_service: {e}")
        return {"ok": False, "error": "order_service_unavailable"}
    
    try:
        result = create_order(
            wa_id=wa_id,
            items=order_items,
            source="kb_checkout" if not session else "checkout_session",
            session_id=session_id,
            idempotency_key=idempotency_key,
            payment_method=order_draft.get("payment_method", "cod"),
        )
        
        if not result.get("ok"):
            return {"ok": False, "error": result.get("error", "order failed")}
        
        if result.get("duplicate"):
            return {"ok": True, "existing": True, "order": {"order_number": result["order_number"], "total": result["total"]}}
        
        return {"ok": True, "existing": False, "order": {"order_number": result["order_number"], "total": result["total"], "idempotency_key": idempotency_key}}
    
    except OrderError as oe:
        logger.info(f"ORDER_ERROR | wa_id={wa_id} | reason={oe.reason} | detail={oe.detail}")
        return {"ok": False, "error": oe.reason, "detail": oe.detail}
    except Exception as e:
        logger.error(f"CONFIRM_ORDER_FAIL | wa_id={wa_id} | {e}")
        return {"ok": False, "error": str(e)}


def revalidate_prices(wa_id: str) -> dict:
    """Revalidate cart item prices against current products table."""
    db = _db()
    items = get_cart(wa_id)
    if not items:
        return {"ok": True, "changed": False, "items": []}
    
    changed_items = []
    try:
        with db.get_db_context() as conn:
            for it in items:
                row = conn.execute(
                    "SELECT price FROM products WHERE id = ?", (it["product_id"],)
                ).fetchone()
                if row:
                    current_price = parse_price(row["price"])
                    if abs(current_price - it["price_at_add"]) > 0.001:
                        changed_items.append({
                            "product_id": it["product_id"],
                            "name": it["name"],
                            "old_price": it["price_at_add"],
                            "new_price": current_price,
                            "qty": it["qty"],
                        })
                        # Update the cart item with new price
                        conn.execute(
                            "UPDATE cart_items SET price_at_add = ? WHERE cart_id = (SELECT id FROM carts WHERE wa_id = ?) AND product_id = ?",
                            (current_price, wa_id, it["product_id"]),
                        )
        
        if changed_items:
            return {"ok": True, "changed": True, "items": changed_items}
        return {"ok": True, "changed": False, "items": []}
    except Exception as e:
        logger.error(f"REVALIDATE_PRICES_FAIL | wa_id={wa_id} | {e}")
        return {"ok": False, "error": str(e)}


def get_user_orders(wa_id: str, limit: int = 5) -> list:
    """Get user's recent orders."""
    db = _db()
    try:
        with db.get_db_context() as conn:
            rows = conn.execute(
                """SELECT order_number, items, total_amount, status, payment_status, created_at, idempotency_key
                   FROM orders WHERE wa_id = ?
                   ORDER BY created_at DESC, id DESC LIMIT ?""",
                (wa_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"ORDER_LIST_FAIL | wa_id={wa_id} | {e}")
        return []


# ── Button contract (docs/cart_contract.md) ──────────────────────────────────

_LEGACY_MAP = {
    "menu_add_cart": "add_cart",
    "menu_view_cart": "view_cart",
    "menu_buy_now": "checkout",
    "checkout_confirm": "confirm_order",
    "b2c_view_cart": "view_cart",
    "b2c_checkout": "checkout",
    "b2c_clear_cart": "clear_cart",
    "b2c_continue_shopping": "continue_shopping",
    "b2c_pay_cod": "pay_cod",
    "b2c_confirm_order": "confirm_order",
    "b2c_cancel_order": "cancel_order",
}


def parse_shop_button(button_id: str):
    """Parse a cart/checkout button ID into (action, product_id|None).

    Handles canonical b2c_add_cart_{id} / b2c_buynow_{id}, legacy menu_add_cart_{id}
    / menu_buy_now_{id}, and fixed IDs. Returns ('unknown', None) for unknown IDs
    so callers can fall through to existing routers — never crash.
    """
    if not button_id:
        return "unknown", None
    bid = str(button_id).strip()

    m = re.fullmatch(r"(?:b2c_add_cart|menu_add_cart)_(\d+)", bid)
    if m:
        return "add_cart", int(m.group(1))
    m = re.fullmatch(r"(?:b2c_buynow|menu_buy_now)_(\d+)", bid)
    if m:
        return "buynow", int(m.group(1))

    if bid in _LEGACY_MAP:
        return _LEGACY_MAP[bid], None
    return "unknown", None


# ── Expiry sweep ─────────────────────────────────────────────────────────────

def expire_stale_checkouts() -> int:
    """Expire checkout sessions older than CHECKOUT_TTL_MINUTES. Returns count."""
    db = _db()
    now = _ts(_utcnow())
    try:
        with db.get_db_context() as conn:
            count = conn.execute(
                "UPDATE checkout_sessions SET status='expired' "
                "WHERE status='active' AND expires_at <= ?",
                (now,),
            ).rowcount
        return count
    except Exception as e:
        logger.error(f"EXPIRE_STALE_CHECKOUTS_FAIL | {e}")
        return 0


def cleanup_expired() -> dict:
    """Delete expired carts and expire stale checkout sessions. Returns counts."""
    db = _db()
    now = _ts(_utcnow())
    counts = {"carts": 0, "checkouts": 0}
    try:
        with db.get_db_context() as conn:
            counts["carts"] = conn.execute(
                "DELETE FROM carts WHERE expires_at <= ?", (now,)
            ).rowcount
            counts["checkouts"] = conn.execute(
                "UPDATE checkout_sessions SET status='expired' "
                "WHERE status='active' AND expires_at <= ?",
                (now,),
            ).rowcount
    except Exception as e:
        logger.error(f"CART_CLEANUP_FAIL | {e}")
    return counts


# ── Internal helpers ─────────────────────────────────────────────────────────

def _upsert_cart_row(conn, wa_id: str) -> int:
    """Return the cart id for wa_id, creating/refreshing the 7-day TTL as needed."""
    now = _utcnow()
    expires = _ts(now + timedelta(days=CART_TTL_DAYS))
    row = conn.execute("SELECT id FROM carts WHERE wa_id = ?", (wa_id,)).fetchone()
    if row:
        conn.execute(
            "UPDATE carts SET updated_at = ?, expires_at = ? WHERE id = ?",
            (_ts(now), expires, row["id"]),
        )
        return row["id"]
    cur = conn.execute(
        "INSERT INTO carts (wa_id, created_at, updated_at, expires_at, tenant_id) VALUES (?, ?, ?, ?, ?)",
        (wa_id, _ts(now), _ts(now), expires, _tenant_for(wa_id)),
    )
    return cur.lastrowid


def _touch_cart(conn, wa_id: str) -> None:
    conn.execute(
        "UPDATE carts SET updated_at = ?, expires_at = ? WHERE wa_id = ?",
        (_ts(_utcnow()),
         _ts(_utcnow() + timedelta(days=CART_TTL_DAYS)),
         wa_id),
    )