"""Admin-editable record columns — the schema behind a tenant's content table.

Every tenant owns a table of records (products, services, packages, departments)
and every business shapes that table differently. A clothing brand wants a
``size``, an FMCG brand wants a ``shelf_life_days``, a travel company wants
``includes_flight`` and ``max_person``. So the columns are data, seeded from the
vertical and then owned by the admin.

Two things live here:

1. ``DEFAULT_COLUMNS`` / ``SYSTEM_COLUMNS`` — the per-vertical seed. This is the
   same pattern as ``defaults.py``: behaviour ships as data.
2. The registry store — ``tenant_record_columns`` rows plus the real
   ``ALTER TABLE`` against ``products`` so adding a column in the console is a
   real database change, not a JSON blob that pretends to be one.

System columns are the ones the bot and the shared record code read by name
(``name``, ``price``, ...). They are always present and cannot be dropped; a
tenant adds columns beside them. Removing a column drops the data with it, so
callers should confirm first (see ``drop_column``).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger("records")

# The physical table every tenant's records live in. Named `products` for
# historical reasons; the tenant console calls it "records".
RECORDS_TABLE = "products"

#: Column types an admin can pick, and the SQL type each maps to. `options` is
#: only meaningful for `select`, which is why it lives next to the type map.
COLUMN_TYPES: Dict[str, Dict[str, Any]] = {
    "text": {"sql": "TEXT", "label": "Text", "hint": "Short free text."},
    "long_text": {"sql": "TEXT", "label": "Long text", "hint": "Multi-line text, e.g. an itinerary."},
    "number": {"sql": "REAL", "label": "Number", "hint": "Any number, stored with decimals."},
    "integer": {"sql": "INTEGER", "label": "Whole number", "hint": "Counts, days, max travellers."},
    "boolean": {"sql": "INTEGER", "label": "Yes / no", "hint": "A tick box."},
    "date": {"sql": "TEXT", "label": "Date", "hint": "YYYY-MM-DD."},
    "select": {"sql": "TEXT", "label": "Pick from a list", "hint": "The admin supplies the choices."},
}

#: Columns the shared record code reads by name. Always present, never dropped.
SYSTEM_COLUMNS: List[Dict[str, Any]] = [
    {"key": "name", "label": "Name", "type": "text", "required": True, "help": "What the bot calls this record."},
    {"key": "category", "label": "Category", "type": "text", "required": True, "help": "Groups records in the table and in the bot's menu."},
    {"key": "short_label", "label": "Tag", "type": "text", "help": "A small highlight, e.g. “Best seller”."},
    {"key": "short_description", "label": "Short description", "type": "long_text", "help": "The one line the bot replies with."},
    {"key": "description", "label": "Full description", "type": "long_text", "help": "The detail read out when a customer asks for more."},
    {"key": "is_active", "label": "Visible to the bot", "type": "boolean", "help": "Off keeps the record but hides it from the bot."},
]

#: Columns every tenant starts with but which belong to the tenant: an admin
#: can remove them when they are irrelevant (a consultancy does not need a
#: price; a services firm has no image). Their physical columns live on the
#: shared records table, so removal only unregisters — the data of every other
#: tenant is untouched — and re-adding registers without re-creating.
SHARED_PRESENTATION_COLUMNS: List[Dict[str, Any]] = [
    {"key": "price", "label": "Price", "type": "text", "help": "Free text so a currency symbol is preserved. Blank when there is no price."},
    {"key": "detail_url", "label": "Link", "type": "text", "help": "Where the customer can see it."},
    {"key": "media_url", "label": "Image URL", "type": "text", "help": "Shown on the product page."},
]

_SYSTEM_KEYS = {c["key"] for c in SYSTEM_COLUMNS}
_SHARED_PRESENTATION_KEYS = {c["key"] for c in SHARED_PRESENTATION_COLUMNS}


def _col(
    key: str,
    label: str,
    col_type: str = "text",
    *,
    required: bool = False,
    options: Iterable[str] = (),
    help: str = "",
) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "type": col_type,
        "required": required,
        "options": list(options),
        "help": help,
    }


#: Per-vertical seed. Only the columns that make the vertical recognisable —
#: an admin adds the rest from the console.
DEFAULT_COLUMNS: Dict[str, List[Dict[str, Any]]] = {
    "ecommerce": [
        _col("sku", "SKU", "text", help="Stock keeping unit, e.g. TG-1042."),
        _col("size", "Size", "text", help="S / M / L, or 500 g / 1 kg."),
        _col("in_stock", "In stock", "integer", help="Units on hand right now."),
        _col("mrp", "MRP", "text", help="Struck-through price, if you show one."),
        _col("warranty", "Warranty", "text", help="e.g. 12 months."),
        _col("returnable", "Returnable", "boolean"),
    ],
    "it_software": [
        _col("tech_stack", "Tech stack", "text", help="React, Node.js, AWS."),
        _col("timeline", "Typical timeline", "text", help="e.g. 8–10 weeks."),
        _col("engagement", "Engagement model", "select", options=["Fixed price", "Time and materials", "Retainer", "Mixed"]),
        _col("team_size", "Team size", "integer"),
    ],
    "tours_travel": [
        _col("package_name", "Package name", "text", required=True, help="The name customers search for."),
        _col("destination", "Destination", "text", required=True, help="Kerala, Munnar, Dubai…"),
        _col("duration", "Duration", "text", help="e.g. 5 nights / 6 days."),
        _col("includes_flight", "Includes flight", "boolean"),
        _col("includes_hotel", "Includes hotel", "boolean"),
        _col("includes_bus", "Includes bus", "boolean"),
        _col("includes_food", "Includes food", "boolean"),
        _col("includes_guide", "Includes guide", "boolean"),
        _col("max_person", "Max travellers", "integer", help="Optional. Leave blank for no limit."),
        _col("itinerary", "Itinerary", "long_text", help="Day-by-day plan the bot reads out."),
    ],
    "banking": [
        _col("account_type", "Account type", "text"),
        _col("interest_rate", "Interest rate", "text"),
        _col("annual_fee", "Annual fee", "text"),
        _col("eligibility", "Eligibility", "text", help="Who can open it."),
    ],
    "finance": [
        _col("filing_type", "Filing", "select", options=["ITR", "GST", "Audit", "Registration", "Payroll", "Advisory"]),
        _col("next_deadline", "Next deadline", "date"),
        _col("documents_needed", "Documents needed", "text", help="PAN, ITR, bank statement."),
    ],
    "healthcare": [
        _col("department_head", "Department head", "text"),
        _col("timings", "Timings", "text", help="Mon–Sat, 9:00–18:00."),
        _col("location", "Location", "text"),
    ],
    "generic": [
        _col("availability", "Availability", "text", help="In stock / On request."),
        _col("lead_time", "Lead time", "text"),
    ],
}


def default_columns_for(vertical: Optional[str]) -> List[Dict[str, Any]]:
    """System columns followed by the vertical's own, keyed for insertion."""
    seeded = DEFAULT_COLUMNS.get(vertical or "", [])
    out: List[Dict[str, Any]] = []
    for order, col in enumerate(SYSTEM_COLUMNS + SHARED_PRESENTATION_COLUMNS + seeded):
        row = dict(col)
        # SYSTEM_COLUMNS are hand-written literals and omit the optional keys that
        # the `_col` helper always sets. Fill them here so every spec is uniform
        # and seed_columns can read them without a KeyError.
        row.setdefault("required", False)
        row.setdefault("options", [])
        row.setdefault("help", "")
        row["sort_order"] = order
        row["is_system"] = col["key"] in _SYSTEM_KEYS
        out.append(row)
    return out


# ── validation ───────────────────────────────────────────────────────────

#: Column keys are interpolated into DDL, so the grammar is deliberately narrow:
#: lower snake_case that cannot collide with SQL or with a system column.
KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

RESERVED_KEYS = _SYSTEM_KEYS | {
    # Read by shared code or by SQLite itself — an admin column named after one of
    # these would shadow it in `SELECT *` reads.
    "id", "slug", "tenant_id", "created_at", "updated_at", "sort_order",
    "attrs_json", "embedding", "variants_json", "ingredients",
    "bulk_discount_tiers", "stock_quantity", "nutritional_facts", "mrp", "unit", "moq",
    "media_type",
}

IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')


class ColumnError(ValueError):
    """A column definition the server refuses. The message is shown to the admin."""


def validate_key(key: str) -> str:
    key = (key or "").strip().lower()
    if not KEY_PATTERN.match(key):
        raise ColumnError(
            "Column key must start with a letter and use only lower-case letters, "
            "digits and underscores (max 40 characters)."
        )
    if key in RESERVED_KEYS:
        raise ColumnError(f"‘{key}’ is reserved — pick another name for the column.")
    return key


def validate_type(col_type: str) -> str:
    col_type = (col_type or "").strip()
    if col_type not in COLUMN_TYPES:
        raise ColumnError(
            f"Unknown column type ‘{col_type}’. Use one of: {', '.join(sorted(COLUMN_TYPES))}."
        )
    return col_type


def validate_options(col_type: str, options: Any) -> List[str]:
    if col_type != "select":
        return []
    if not isinstance(options, (list, tuple)):
        raise ColumnError("A ‘Pick from a list’ column needs its choices as a list.")
    cleaned = [str(o).strip() for o in options if str(o).strip()]
    if not cleaned:
        raise ColumnError("A ‘Pick from a list’ column needs at least one choice.")
    if len(cleaned) > 50:
        raise ColumnError("A list column can hold at most 50 choices.")
    return cleaned


def sql_type(col_type: str) -> str:
    return COLUMN_TYPES[validate_type(col_type)]["sql"]


# ── DDL ──────────────────────────────────────────────────────────────────

def _supports_drop_column() -> bool:
    """`ALTER TABLE ... DROP COLUMN` landed in SQLite 3.35.0."""
    try:
        parts = tuple(int(p) for p in sqlite3.sqlite_version.split(".")[:3])
    except ValueError:  # pragma: no cover - only on a non-numeric build string
        return False
    return parts >= (3, 35, 0)


def existing_columns(conn) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({RECORDS_TABLE})").fetchall()}


def add_column(conn, key: str, col_type: str, *, check_reserved: bool = True) -> bool:
    """Add a real column to the records table. No-op when it already exists.

    `check_reserved` is off for the vertical seed: `mrp` and `unit` are legacy
    physical columns the seed wants to expose even though an admin may not mint
    a column with that name.
    """
    key = (key or "").strip().lower()
    if check_reserved:
        key = validate_key(key)
    if not IDENT.match(key) or not KEY_PATTERN.match(key):
        raise ColumnError(f"Unsafe column name ‘{key}’.")
    if key in existing_columns(conn):
        return False
    conn.execute(f"ALTER TABLE {RECORDS_TABLE} ADD COLUMN {key} {sql_type(col_type)}")
    logger.info(f"RECORD_COLUMN_ADDED | table={RECORDS_TABLE} | column={key} | type={col_type}")
    return True


def drop_column(conn, key: str) -> bool:
    """Drop the column and its data. False when the table cannot be altered.

    Shared presentation columns (price, link, image) are never physically
    dropped: their column belongs to the shared records table and every other
    tenant's data lives in it. Removal unregisters them for this tenant only.
    """
    key = (key or "").strip().lower()
    if key in _SYSTEM_KEYS or key in RESERVED_KEYS:
        raise ColumnError("A core column cannot be removed — hide it with “Visible to the bot” instead.")
    if key in _SHARED_PRESENTATION_KEYS:
        return False
    if key not in existing_columns(conn):
        return False
    if not IDENT.match(key):
        raise ColumnError(f"Unsafe column name ‘{key}’.")
    if not _supports_drop_column():
        raise ColumnError(
            "This database cannot drop columns (SQLite is older than 3.35). "
            "The column is hidden from the table; its values are still stored."
        )
    conn.execute(f"ALTER TABLE {RECORDS_TABLE} DROP COLUMN {key}")
    logger.info(f"RECORD_COLUMN_DROPPED | table={RECORDS_TABLE} | column={key}")
    return True


# ── registry store ───────────────────────────────────────────────────────

def _loads(value, default):
    try:
        return json.loads(value) if value else default
    except (TypeError, ValueError):
        return default


def _row_to_column(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "key": row["key"],
        "label": row["label"],
        "type": row["type"],
        "required": bool(row["required"]),
        "options": _loads(row["options_json"], []),
        "help": row["help"] or "",
        "sort_order": row["sort_order"] or 0,
        "is_system": bool(row["is_system"]),
        "created_at": row["created_at"],
    }


def seed_columns(conn, tenant_id: str, vertical: str) -> int:
    """Insert the vertical's default columns if this tenant has none yet."""
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM tenant_record_columns WHERE tenant_id = ?",
        (tenant_id,),
    ).fetchone()["c"]
    if count:
        return 0

    inserted = 0
    for spec in default_columns_for(vertical):
        # A column that already exists in the table (from an older migration, or
        # because another tenant seeded it) is registered but not re-added.
        physical = spec["key"] in existing_columns(conn)
        if not physical and not spec["is_system"]:
            try:
                add_column(conn, spec["key"], spec["type"], check_reserved=False)
            except ColumnError as exc:
                logger.warning(f"RECORD_COLUMN_SEED_SKIPPED | tenant={tenant_id} | column={spec['key']} | {exc}")
                continue
        conn.execute(
            """INSERT INTO tenant_record_columns
               (tenant_id, key, label, type, required, options_json, help, sort_order, is_system)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tenant_id, spec["key"], spec["label"], spec["type"],
                1 if spec["required"] else 0,
                json.dumps(spec["options"]),
                spec["help"], spec["sort_order"],
                1 if spec["is_system"] else 0,
            ),
        )
        inserted += 1
    logger.info(f"RECORD_COLUMNS_SEEDED | tenant={tenant_id} | vertical={vertical} | count={inserted}")
    return inserted


def list_columns(conn, tenant_id: str) -> List[Dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM tenant_record_columns WHERE tenant_id = ? ORDER BY sort_order ASC, id ASC",
        (tenant_id,),
    ).fetchall()
    return [_row_to_column(r) for r in rows]


def sync_columns(conn, tenant_id: str, vertical: str) -> List[Dict[str, Any]]:
    """The tenant's registered columns, seeding the vertical's defaults first.

    The registry is authoritative. Every tenant shares one physical
    ``products`` table, so a bare physical column cannot be attributed to a
    tenant — one brand's ``package_name`` sits in the same table as another's
    ``sku``. Registering physical columns here would therefore leak every
    vertical's fields into every tenant. New fields are added deliberately, with
    ``create_column``.
    """
    seed_columns(conn, tenant_id, vertical)
    return list_columns(conn, tenant_id)


def create_column(
    conn,
    tenant_id: str,
    *,
    key: str,
    label: str,
    col_type: str,
    required: bool = False,
    options: Any = None,
    help: str = "",
) -> Dict[str, Any]:
    key = validate_key(key)
    col_type = validate_type(col_type)
    label = (label or "").strip() or key.replace("_", " ").capitalize()
    options = validate_options(col_type, options)

    if any(c["key"] == key for c in list_columns(conn, tenant_id)):
        raise ColumnError(f"A column called ‘{key}’ already exists.")

    add_column(conn, key, col_type)
    order = max((c["sort_order"] for c in list_columns(conn, tenant_id)), default=-1) + 1
    conn.execute(
        """INSERT INTO tenant_record_columns
           (tenant_id, key, label, type, required, options_json, help, sort_order, is_system)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
        (tenant_id, key, label, col_type, 1 if required else 0, json.dumps(options), help or "", order),
    )
    logger.info(f"RECORD_COLUMN_CREATED | tenant={tenant_id} | column={key} | type={col_type}")
    return next(c for c in list_columns(conn, tenant_id) if c["key"] == key)


def update_column(
    conn,
    tenant_id: str,
    key: str,
    *,
    label: Optional[str] = None,
    col_type: Optional[str] = None,
    required: Optional[bool] = None,
    options: Any = None,
    help: Optional[str] = None,
    sort_order: Optional[int] = None,
) -> Dict[str, Any]:
    """Edit a column's presentation, and its type where SQLite allows it.

    Changing a column's SQL type in place is a data conversion, so it is refused
    while the column holds values. The admin empties the column first, or drops
    and re-adds it.
    """
    key = (key or "").strip().lower()
    column = next((c for c in list_columns(conn, tenant_id) if c["key"] == key), None)
    if not column:
        raise ColumnError(f"No column called ‘{key}’ on this tenant.")

    updates: Dict[str, Any] = {}
    if label is not None:
        cleaned = label.strip()
        if not cleaned:
            raise ColumnError("A column needs a header.")
        updates["label"] = cleaned
    if help is not None:
        updates["help"] = help.strip()
    if required is not None:
        updates["required"] = 1 if required else 0
    if sort_order is not None:
        updates["sort_order"] = int(sort_order)
    if options is not None:
        updates["options_json"] = json.dumps(options if isinstance(options, list) else [])
    if col_type is not None and col_type != column["type"]:
        new_type = validate_type(col_type)
        updates["type"] = new_type
        updates["options_json"] = json.dumps(validate_options(new_type, updates.get("options_json", column["options"])))
        populated = conn.execute(
            f'SELECT COUNT(*) AS c FROM {RECORDS_TABLE} WHERE tenant_id = ? AND "{key}" IS NOT NULL',
            (tenant_id,),
        ).fetchone()["c"]
        if populated:
            raise ColumnError(
                f"‘{column['label']}’ still holds {populated} value(s), so its type cannot change. "
                "Clear the column, or delete it and add it again."
            )

    if not updates:
        return column

    assignments = ", ".join(f"{field} = ?" for field in updates)
    conn.execute(
        f"UPDATE tenant_record_columns SET {assignments} WHERE tenant_id = ? AND key = ?",
        list(updates.values()) + [tenant_id, key],
    )
    logger.info(f"RECORD_COLUMN_UPDATED | tenant={tenant_id} | column={key} | fields={sorted(updates)}")
    return next(c for c in list_columns(conn, tenant_id) if c["key"] == key)


def remove_column(conn, tenant_id: str, key: str) -> bool:
    key = (key or "").strip().lower()
    column = next((c for c in list_columns(conn, tenant_id) if c["key"] == key), None)
    if not column:
        raise ColumnError(f"No column called ‘{key}’ on this tenant.")
    dropped = drop_column(conn, key)
    conn.execute(
        "DELETE FROM tenant_record_columns WHERE tenant_id = ? AND key = ?", (tenant_id, key)
    )
    logger.info(f"RECORD_COLUMN_REMOVED | tenant={tenant_id} | column={key} | dropped={dropped}")
    return dropped


def reset_columns(conn, tenant_id: str, vertical: str) -> List[Dict[str, Any]]:
    """Drop this tenant's own columns and re-seed from the vertical defaults.

    Core columns are left alone — they hold the records themselves.
    """
    for column in list_columns(conn, tenant_id):
        if column["is_system"]:
            continue
        try:
            drop_column(conn, column["key"])
        except ColumnError as exc:
            logger.warning(f"RECORD_COLUMN_RESET_SKIPPED | tenant={tenant_id} | column={column['key']} | {exc}")
    conn.execute("DELETE FROM tenant_record_columns WHERE tenant_id = ? AND is_system = 0", (tenant_id,))
    seed_columns(conn, tenant_id, vertical)
    logger.info(f"RECORD_COLUMNS_RESET | tenant={tenant_id} | vertical={vertical}")
    return list_columns(conn, tenant_id)


# ── values ───────────────────────────────────────────────────────────────

_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off", ""}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def coerce(column: Dict[str, Any], value: Any) -> Any:
    """Turn one submitted cell into the value stored in the column.

    Empty always means NULL — a blank cell is not an empty string, so clearing a
    column really clears it. Raises ColumnError with the column's own label so
    the console can point at the right cell.
    """
    label = column["label"]
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    col_type = column["type"]

    if col_type in ("text", "long_text", "date"):
        text = str(value).strip()
        if col_type == "date":
            if not _DATE.match(text):
                raise ColumnError(f"‘{label}’ must be a date like 2026-04-01.")
        return text

    if col_type == "select":
        text = str(value).strip()
        if text not in column["options"]:
            raise ColumnError(f"‘{text}’ is not one of the choices for ‘{label}’.")
        return text

    if col_type == "boolean":
        if isinstance(value, bool):
            return 1 if value else 0
        text = str(value).strip().lower()
        if text in _TRUE:
            return 1
        if text in _FALSE:
            return None
        raise ColumnError(f"‘{label}’ must be yes or no.")

    if col_type in ("number", "integer"):
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            raise ColumnError(f"‘{label}’ must be a number.")
        return int(number) if col_type == "integer" else number

    raise ColumnError(f"‘{label}’ has an unknown column type ‘{col_type}’.")


def coerce_record(columns: List[Dict[str, Any]], values: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a whole submitted record, collecting one error per bad cell.

    Returns `(clean, errors)` so the console can highlight several cells at once
    instead of surfacing them one save at a time.
    """
    clean: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for column in columns:
        if column["key"] not in values:
            continue
        try:
            clean[column["key"]] = coerce(column, values[column["key"]])
        except ColumnError as exc:
            errors[column["key"]] = str(exc)
    for column in columns:
        # System columns (name, category, price...) travel in the request's own
        # fields, never in `values`, so a required check here would reject every
        # save. Their required-ness is enforced by the route instead: pydantic
        # on create, the existing row on update.
        if column.get("is_system"):
            continue
        if column["required"] and clean.get(column["key"]) in (None, ""):
            errors.setdefault(column["key"], f"‘{column['label']}’ is required.")
    return clean, errors


def present(columns: List[Dict[str, Any]], row: Dict[str, Any]) -> Dict[str, Any]:
    """The registered columns of one row, typed for JSON.

    Physical columns the tenant has not registered are left out — the console
    shows the registry, not `SELECT *`.
    """
    out: Dict[str, Any] = {}
    for column in columns:
        value = row.get(column["key"])
        if column["type"] == "boolean":
            out[column["key"]] = None if value is None else bool(value)
        elif column["type"] in ("number", "integer"):
            out[column["key"]] = None if value is None else value
        else:
            out[column["key"]] = value if value is None else str(value)
    return out

