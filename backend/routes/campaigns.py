import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from database import get_db_context
from routes.auth import require_permission, require_tenant_access

logger = logging.getLogger("campaigns")
router = APIRouter(prefix="/api/admin/tenants/{tenant_id}/campaigns", tags=["campaigns"])


# ── Vocabulary ───────────────────────────────────────────────────────────
# The status set is engine-owned: admins may only park a campaign in draft,
# queue it (scheduled) or call it off. sending / completed / paused / failed
# belong to the broadcast engine once it fires.

CAMPAIGN_TYPES = ("promotional", "transactional", "informational")
CAMPAIGN_STATUSES = ("draft", "scheduled", "sending", "completed", "paused", "failed", "cancelled")
ADMIN_STATUSES = ("draft", "scheduled", "paused", "cancelled")
AUDIENCE_TYPES = ("all", "distributors", "customers", "segments")
MEDIA_EXTENSIONS = ("jpg", "jpeg", "png", "mp4")

# A segment is a named, reusable audience: distributors filtered by
# region / tier / city / interests, or customers by purchase value.
SEGMENT_AUDIENCES = ("distributors", "customers")
# Criteria combine as AND by default; a distributor segment can set
# match: "any" to combine its positive list filters with OR instead.
DISTRIBUTOR_CRITERIA = (
    "regions", "tiers", "city", "product_interests", "min_sales_volume",
    "credit_status", "registered_within_days",
    "exclude_regions", "exclude_tiers", "exclude_city", "match",
)
CUSTOMER_CRITERIA = (
    "min_total_purchases", "max_total_purchases",
    "order_count_min", "order_count_max",
    "last_order_within_days", "inactive_for_days", "registered_within_days",
)

# A campaign's type must be consistent with its template's Meta category.
CATEGORY_BY_CAMPAIGN_TYPE = {
    "promotional": ("MARKETING",),
    "transactional": ("UTILITY", "AUTHENTICATION"),
    "informational": ("MARKETING", "UTILITY", "AUTHENTICATION"),
}
# The template registry is the existing global whatsapp_templates table
# (registered via the WhatsApp provider / KB template manager). A template
# counts as approved once the provider accepted it.
APPROVED_TEMPLATE_STATUSES = ("registered", "already_exists")
TEMPLATE_STATUSES = ("registered", "pending", "rejected")


# ── Pydantic models ────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str = ""
    status: str = "draft"
    campaign_type: str = "promotional"
    audience_type: str = "all"
    segment_id: int | None = None
    target_count: int = 0
    whatsapp_template: str = ""
    template_type: str = "whatsapp_template"
    message_template: str = ""
    template_variables: dict = {}
    variable_fallbacks: dict = {}
    buttons: list = []
    list_items: list = []
    media_filename: str | None = None
    schedule_mode: str = "now"
    scheduled_at: str | None = None
    timezone: str = "Asia/Kolkata"


class SegmentCreate(BaseModel):
    name: str = ""
    audience_type: str = "distributors"
    criteria: dict = {}


class AudienceCount(BaseModel):
    audience_type: str = "distributors"
    criteria: dict = {}


TEMPLATE_CATEGORIES = ("MARKETING", "UTILITY", "AUTHENTICATION")


class TemplateCreate(BaseModel):
    name: str = ""
    category: str = "UTILITY"
    body: str = ""
    language: str = "en"
    header: str = ""
    footer: str = ""
    params: list = []


class TemplateStatus(BaseModel):
    status: str = "approved"


# ── Helpers ────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    d = dict(row)

    for key in (
        "segment_json", "template_variables_json", "variable_fallbacks_json",
        "buttons_json", "list_items_json",
    ):
        raw = d.get(key, "{}")
        if isinstance(raw, str):
            try:
                d[key.replace("_json", "")] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d[key.replace("_json", "")] = {} if "var" in key or "segment" in key else []
        else:
            d[key.replace("_json", "")] = raw

    # Nest metrics fields to match frontend Campaign type
    d["metrics"] = {
        "sent": d.pop("sent", 0) or 0,
        "delivered": d.pop("delivered", 0) or 0,
        "read": d.pop("read_count", 0) or 0,
        "replied": d.pop("replied", 0) or 0,
        "failed": d.pop("failed", 0) or 0,
    }

    return d


def _opt_out_clause(tenant_id: str) -> tuple:
    """Consent guard: opted-out contacts never receive campaigns."""
    return ("wa_id NOT IN (SELECT wa_id FROM campaign_opt_outs WHERE tenant_id = ?)", [tenant_id])


def _estimate_target_count(conn, criteria: dict | None, tenant_id: str, audience_type: str = "distributors") -> int:
    """Count the contacts a campaign will reach.

    Contacts who opted out (STOP) are always excluded. Customers are the
    tenant's chat contacts, filtered by their purchase behaviour; distributors
    are counted from the distributor directory with the segment's filters.
    Positive list filters combine with AND (or OR with match: "any");
    exclusions always apply on top.
    """
    opt_clause, opt_params = _opt_out_clause(tenant_id)

    if audience_type == "customers":
        conditions, params = [], []
        c = criteria or {}

        def _days_clause(column: str, within_days, after: bool) -> None:
            if within_days is None:
                return
            params.append(f"-{int(within_days)} days")
            if after:
                conditions.append(f"{column} >= datetime('now', ?)")
            else:
                conditions.append(f"(COALESCE({column}, '') = '' OR {column} < datetime('now', ?))")

        for key, op in (("min_total_purchases", ">="), ("max_total_purchases", "<=")):
            if c.get(key) is not None:
                params.append(float(c[key]))
                conditions.append(f"total {op} ?")
        for key, op in (("order_count_min", ">="), ("order_count_max", "<=")):
            if c.get(key) is not None:
                params.append(int(c[key]))
                conditions.append(f"cnt {op} ?")
        _days_clause("last_order", c.get("last_order_within_days"), after=True)
        _days_clause("last_order", c.get("inactive_for_days"), after=False)
        _days_clause("first_seen", c.get("registered_within_days"), after=True)

        where = (" AND " + " AND ".join(conditions)) if conditions else ""
        row = conn.execute(
            f"""SELECT COUNT(*) AS cnt FROM (
                    SELECT c.wa_id,
                           c.created_at AS first_seen,
                           (SELECT COALESCE(SUM(o.total_amount), 0) FROM orders o WHERE o.wa_id = c.wa_id) AS total,
                           (SELECT COUNT(*) FROM orders o WHERE o.wa_id = c.wa_id) AS cnt,
                           (SELECT MAX(o.created_at) FROM orders o WHERE o.wa_id = c.wa_id) AS last_order
                    FROM (SELECT wa_id, MIN(created_at) AS created_at
                          FROM chat_history WHERE tenant_id = ? GROUP BY wa_id) c
                    WHERE {opt_clause}
                ) WHERE 1=1{where}""",
            [tenant_id, *opt_params, *params],
        ).fetchone()
        return row["cnt"] if row else 0

    c = criteria or {}
    where, params = [], []
    positive_clauses, positive_params = [], []

    def _in_clause(column: str, values) -> None:
        placeholders = ",".join("?" for _ in values)
        positive_clauses.append(f"{column} IN ({placeholders})")
        positive_params.extend(values)

    if c.get("regions") and "All" not in c["regions"]:
        _in_clause("region", c["regions"])
    if c.get("tiers"):
        _in_clause("tier", c["tiers"])
    if c.get("city"):
        positive_clauses.append("LOWER(city) = LOWER(?)")
        positive_params.append(str(c["city"]).strip())
    for interest in c.get("product_interests") or []:
        positive_clauses.append("product_interests LIKE ?")
        positive_params.append(f"%{interest}%")

    joiner = " OR " if c.get("match") == "any" else " AND "
    if positive_clauses:
        where.append("(" + joiner.join(positive_clauses) + ")")
        params.extend(positive_params)

    if c.get("min_sales_volume") is not None:
        where.append("sales_volume >= ?")
        params.append(float(c["min_sales_volume"]))
    if c.get("credit_status"):
        if c["credit_status"] == "outstanding":
            where.append("outstanding_payments > 0")
        elif c["credit_status"] == "clear":
            where.append("outstanding_payments <= 0")
    if c.get("registered_within_days") is not None:
        where.append("created_at >= datetime('now', ?)")
        params.append(f"-{int(c['registered_within_days'])} days")

    for key, column in (("exclude_regions", "region"), ("exclude_tiers", "tier"), ("exclude_city", "city")):
        values = c.get(key) or []
        if isinstance(values, str):
            values = [values]
        if values:
            placeholders = ",".join("?" for _ in values)
            if column == "city":
                where.append(f"(city IS NULL OR LOWER(city) NOT IN ({placeholders.lower()}))")
                params.extend(str(v).strip().lower() for v in values)
            else:
                where.append(f"({column} IS NULL OR {column} NOT IN ({placeholders}))")
                params.extend(values)

    where.append(opt_clause)
    params.extend(opt_params)

    row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM distributors WHERE tenant_id = ? AND {' AND '.join(where)}",
        [tenant_id, *params],
    ).fetchone()
    return row["cnt"] if row else 0


def _get_campaign(conn, campaign_id: int, tenant_id: str):
    """Fetch one of this tenant's campaigns, or raise 404."""
    row = conn.execute(
        "SELECT * FROM campaigns WHERE id = ? AND tenant_id = ?",
        (campaign_id, tenant_id),
    ).fetchone()
    if not row:
        raise HTTPException(404, f"Campaign {campaign_id} not found")
    return row


def _campaign_errors(conn, body: CampaignCreate, tenant_id: str):
    """Collect the compulsory / format problems with one campaign submission.

    Returns (errors, approved_template_row_or_None).
    """
    errors = []
    if not (body.name or "").strip():
        errors.append("campaign name is required")
    if body.campaign_type not in CAMPAIGN_TYPES:
        errors.append(f"campaign type must be one of: {', '.join(CAMPAIGN_TYPES)}")
    if body.audience_type not in AUDIENCE_TYPES:
        errors.append(f"audience must be one of: {', '.join(AUDIENCE_TYPES)}")
    segment = None
    if body.audience_type == "segments":
        if not body.segment_id:
            errors.append("a segment must be selected for the segments audience")
        else:
            row = conn.execute(
                "SELECT * FROM segments WHERE id = ? AND tenant_id = ?",
                (body.segment_id, tenant_id),
            ).fetchone()
            segment = dict(row) if row else None
            if not segment:
                errors.append(f"segment {body.segment_id} does not exist")

    template = None
    if not (body.whatsapp_template or "").strip():
        errors.append("an approved WhatsApp template must be selected")
    else:
        row = conn.execute(
            "SELECT * FROM whatsapp_templates WHERE name = ?",
            (body.whatsapp_template.strip(),),
        ).fetchone()
        template = dict(row) if row else None
        if not template or template.get("status") not in APPROVED_TEMPLATE_STATUSES:
            errors.append(
                f"WhatsApp template '{body.whatsapp_template.strip()}' does not exist or is not approved"
            )
        elif (
            body.campaign_type in CATEGORY_BY_CAMPAIGN_TYPE
            and template.get("category") not in CATEGORY_BY_CAMPAIGN_TYPE[body.campaign_type]
        ):
            errors.append(
                f"a {body.campaign_type} campaign needs a "
                f"{' or '.join(CATEGORY_BY_CAMPAIGN_TYPE[body.campaign_type])} template, "
                f"but '{template['name']}' is {template.get('category')}"
            )

    if body.schedule_mode not in ("now", "scheduled"):
        errors.append("schedule mode must be 'now' or 'scheduled'")
    if body.schedule_mode == "scheduled":
        if not (body.scheduled_at or "").strip():
            errors.append("schedule date and time are required when scheduling for later")
        else:
            try:
                datetime.fromisoformat(body.scheduled_at)
            except ValueError:
                errors.append("the schedule date/time could not be parsed")

    if body.media_filename:
        ext = body.media_filename.lower().rsplit(".", 1)[-1] if "." in body.media_filename else ""
        if ext not in MEDIA_EXTENSIONS:
            errors.append("media must be a JPG, PNG or MP4 file")

    for button in body.buttons:
        if not isinstance(button, dict):
            errors.append("buttons must be objects")
            break
        text = str(button.get("text") or "").strip()
        url = str(button.get("url") or "").strip()
        if text and not url:
            errors.append("a CTA button needs a URL")
        if url and not url.startswith("https://"):
            errors.append("CTA URLs must be valid HTTPS URLs")

    return errors, template, segment


def _criteria_errors(audience_type: str, criteria: dict) -> list:
    """Validate one segment's criteria against its audience type."""
    if audience_type not in SEGMENT_AUDIENCES:
        return [f"segment audience type must be one of: {', '.join(SEGMENT_AUDIENCES)}"]
    allowed = DISTRIBUTOR_CRITERIA if audience_type == "distributors" else CUSTOMER_CRITERIA
    c = criteria or {}
    errors = []
    for key in c:
        if key not in allowed:
            errors.append(f"'{key}' is not a valid criterion for a {audience_type} segment")

    for key in ("min_total_purchases", "max_total_purchases"):
        if c.get(key) is not None:
            try:
                float(c[key])
            except (TypeError, ValueError):
                errors.append(f"{key} must be a number")
    for key in ("order_count_min", "order_count_max",
                "last_order_within_days", "inactive_for_days", "registered_within_days"):
        if c.get(key) is not None:
            try:
                int(c[key])
            except (TypeError, ValueError):
                errors.append(f"{key} must be a whole number")
    if audience_type == "distributors":
        if c.get("credit_status") and c["credit_status"] not in ("outstanding", "clear"):
            errors.append("credit_status must be 'outstanding' or 'clear'")
        if c.get("match") and c["match"] not in ("all", "any"):
            errors.append("match must be 'all' or 'any'")
        if c.get("min_sales_volume") is not None:
            try:
                float(c["min_sales_volume"])
            except (TypeError, ValueError):
                errors.append("min_sales_volume must be a number")
    return errors


# ── WhatsApp templates — the campaign builder's message source ─────────

@router.get("/templates")
def list_templates(
    tenant_id: str,
    current_admin: dict = Depends(require_tenant_access),
):
    """The WhatsApp template registry the campaign form picks from."""
    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT id, name, category, body_template, header_text, footer, "
            "language, params_json, status, send2_response, "
            "registered_at, updated_at "
            "FROM whatsapp_templates ORDER BY name COLLATE NOCASE",
        ).fetchall()

    def _loads(raw, default):
        try:
            return json.loads(raw) if raw else default
        except (json.JSONDecodeError, TypeError):
            return default

    return {
        "templates": [
            {
                "id": r["id"],
                "name": r["name"],
                "category": r["category"],
                "body": r["body_template"],
                "header": r["header_text"],
                "footer": r["footer"],
                "language": r["language"],
                "params": _loads(r["params_json"], []),
                "status": r["status"],
                "provider_response": r["send2_response"],
                "created_at": r["registered_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]
    }


@router.post("/templates", status_code=201)
def create_template(
    tenant_id: str,
    body: TemplateCreate,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    """Register a WhatsApp template. Adding it as a campaigns admin is the
    approval step, so it is created 'approved' and can be withdrawn later."""
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "template name is required")
    if not body.body.strip():
        raise HTTPException(422, "template body is required")
    if body.category not in TEMPLATE_CATEGORIES:
        raise HTTPException(422, f"category must be one of: {', '.join(TEMPLATE_CATEGORIES)}")

    import database as db

    if db.get_template(name):
        raise HTTPException(409, f"a template named '{name}' already exists")

    template_id = db.save_template(name, {
        "category": body.category,
        "body_template": body.body,
        "header_text": body.header,
        "footer": body.footer,
        "language": body.language,
        "params": body.params,
        "status": "registered",
    })

    logger.info(f"WA_TEMPLATE_CREATED | tenant={tenant_id} | name={name}")
    return {"ok": True, "id": template_id}


@router.put("/templates/{template_id}")
def set_template_status(
    tenant_id: str,
    template_id: int,
    body: TemplateStatus,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    if body.status not in TEMPLATE_STATUSES and body.status not in ("failed", "error"):
        raise HTTPException(422, f"status must be one of: {', '.join(TEMPLATE_STATUSES)}")

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_context() as conn:
        result = conn.execute(
            "UPDATE whatsapp_templates SET status = ?, updated_at = ? WHERE id = ?",
            (body.status, now, template_id),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "template not found")

    return {"ok": True}


@router.post("/media")
async def upload_campaign_media(
    tenant_id: str,
    file: UploadFile = File(...),
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    """Store a campaign attachment (JPG / PNG / MP4) and return its filename.

    The file lands in the shared upload directory and is tracked in
    admin_files under the 'campaigns' module, so the existing tenant
    preview/download endpoints serve it. The returned filename is what the
    campaign stores in media_filename.
    """
    content = await file.read()
    if not content:
        raise HTTPException(422, "The upload is empty")
    if len(content) > 16 * 1024 * 1024:
        raise HTTPException(413, "Media must be under 16 MB")

    original = (file.filename or "media").strip()
    ext = Path(original).suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png", ".mp4"):
        raise HTTPException(422, "Media must be a JPG, PNG or MP4 file")

    from routes.admin import UPLOAD_DIR, _guess_media_type
    import database as db

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    stored = f"campaign_{tenant_id}_{uuid.uuid4().hex[:12]}{ext}"
    with open(os.path.join(UPLOAD_DIR, stored), "wb") as fh:
        fh.write(content)

    db.save_admin_file(
        stored, ext.lstrip("."), "campaigns", len(content), file_path=stored, tenant_id=tenant_id
    )

    logger.info(
        "CAMPAIGN_MEDIA_UPLOADED | tenant=%s | stored=%s | bytes=%s",
        tenant_id, stored, len(content),
    )
    return {
        "filename": stored,
        "original_name": original,
        "size": len(content),
        "media_type": _guess_media_type(stored),
    }


@router.delete("/templates/{template_id}")
def delete_template(
    tenant_id: str,
    template_id: int,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    with get_db_context() as conn:
        result = conn.execute(
            "DELETE FROM whatsapp_templates WHERE id = ?", (template_id,)
        )
        if result.rowcount == 0:
            raise HTTPException(404, "template not found")
    logger.info(f"WA_TEMPLATE_DELETED | tenant={tenant_id} | id={template_id}")
    return {"ok": True}


class TestSendBody(BaseModel):
    wa_id: str


@router.post("/{campaign_id}/test-send")
def test_send_campaign(
    tenant_id: str,
    campaign_id: int,
    body: TestSendBody,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    """Send the campaign's rendered message to one number before the real
    broadcast, so the admin sees exactly what the audience would get."""
    wa_id = (body.wa_id or "").strip().lstrip("+")
    if not re.fullmatch(r"\d{6,15}", wa_id):
        raise HTTPException(422, "the test number must be a valid digits-only WhatsApp id")

    with get_db_context() as conn:
        row = _get_campaign(conn, campaign_id, tenant_id)
    d = dict(row)
    try:
        fallbacks = json.loads(d.get("variable_fallbacks_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        fallbacks = {}

    def _render(match: "re.Match") -> str:
        variable = match.group(1) or match.group(2)
        return str(fallbacks.get(variable) or f"[{variable}]")

    rendered = re.sub(r"\{\{\s*(\w+)\s*\}\}|\{(\w+)\}", _render, d.get("message_template") or "")

    from routing.whatsapp import send_whatsapp_message

    try:
        send_whatsapp_message(wa_id, rendered)
    except Exception as exc:  # provider outage / bad credentials
        raise HTTPException(502, f"Test send failed: {exc}")

    logger.info(
        f"CAMPAIGN_TEST_SENT | tenant={tenant_id} | campaign={campaign_id} | to={wa_id}"
    )
    return {"ok": True, "sent_to": wa_id}


# ── Segments — named, reusable audiences ───────────────────────────────

def _segment_to_dict(conn, row: dict, tenant_id: str) -> dict:
    try:
        criteria = json.loads(row.get("criteria_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        criteria = {}
    return {
        "id": row["id"],
        "name": row["name"],
        "audience_type": row["audience_type"],
        "criteria": criteria,
        "target_count": _estimate_target_count(
            conn, criteria, tenant_id, row["audience_type"]
        ),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/segments")
def list_segments(
    tenant_id: str,
    current_admin: dict = Depends(require_tenant_access),
):
    """The tenant's saved segments, each with the audience it reaches."""
    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT * FROM segments WHERE tenant_id = ? ORDER BY name COLLATE NOCASE",
            (tenant_id,),
        ).fetchall()
        segments = [_segment_to_dict(conn, dict(r), tenant_id) for r in rows]
    return {"segments": segments}


@router.post("/segments", status_code=201)
def create_segment(
    tenant_id: str,
    body: SegmentCreate,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "segment name is required")
    errors = _criteria_errors(body.audience_type, body.criteria)
    if errors:
        raise HTTPException(422, "; ".join(errors))

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_context() as conn:
        try:
            cursor = conn.execute(
                """INSERT INTO segments
                    (tenant_id, name, audience_type, criteria_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (tenant_id, name, body.audience_type, json.dumps(body.criteria or {}), now, now),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, f"a segment named '{name}' already exists") from exc

    logger.info(f"SEGMENT_CREATED | tenant={tenant_id} | name={name} | audience={body.audience_type}")
    return {"ok": True, "id": cursor.lastrowid}


@router.put("/segments/{segment_id}")
def update_segment(
    tenant_id: str,
    segment_id: int,
    body: SegmentCreate,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(422, "segment name is required")
    errors = _criteria_errors(body.audience_type, body.criteria)
    if errors:
        raise HTTPException(422, "; ".join(errors))

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_context() as conn:
        try:
            result = conn.execute(
                """UPDATE segments SET name = ?, audience_type = ?, criteria_json = ?,
                   updated_at = ? WHERE id = ? AND tenant_id = ?""",
                (name, body.audience_type, json.dumps(body.criteria or {}), now, segment_id, tenant_id),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(409, f"a segment named '{name}' already exists") from exc
        if result.rowcount == 0:
            raise HTTPException(404, "segment not found")

    return {"ok": True}


@router.delete("/segments/{segment_id}")
def delete_segment(
    tenant_id: str,
    segment_id: int,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    with get_db_context() as conn:
        result = conn.execute(
            "DELETE FROM segments WHERE id = ? AND tenant_id = ?",
            (segment_id, tenant_id),
        )
        if result.rowcount == 0:
            raise HTTPException(404, "segment not found")

    return {"ok": True}


# ── GET /campaigns — list + stats ──────────────────────────────────────

@router.get("")
def list_campaigns(
    tenant_id: str,
    current_admin: dict = Depends(require_tenant_access),
):
    with get_db_context() as conn:
        rows = conn.execute(
            "SELECT * FROM campaigns WHERE tenant_id = ? ORDER BY created_at DESC",
            (tenant_id,),
        ).fetchall()

        campaigns = [_row_to_dict(r) for r in rows]

        # Stats: last 24h
        cutoff = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        stats_row = conn.execute(
            """SELECT
                COALESCE(SUM(sent), 0) AS total_sent_24h,
                COUNT(CASE WHEN status = 'sending' OR status = 'scheduled' THEN 1 END) AS active_campaigns
            FROM campaigns WHERE tenant_id = ? AND created_at >= ?""",
            (tenant_id, cutoff),
        ).fetchone()

        total_sent = stats_row["total_sent_24h"] if stats_row else 0
        active = stats_row["active_campaigns"] if stats_row else 0

        # Overall rates from this tenant's campaigns with data
        rate_row = conn.execute(
            """SELECT
                COALESCE(SUM(sent), 0) AS all_sent,
                COALESCE(SUM(delivered), 0) AS all_delivered,
                COALESCE(SUM(read_count), 0) AS all_read,
                COALESCE(SUM(replied), 0) AS all_replied
            FROM campaigns WHERE tenant_id = ?""",
            (tenant_id,),
        ).fetchone()

        all_sent = rate_row["all_sent"] if rate_row else 0
        all_delivered = rate_row["all_delivered"] if rate_row else 0
        all_replied = rate_row["all_replied"] if rate_row else 0

        delivery_rate = round((all_delivered / all_sent * 100), 1) if all_sent else 0
        reply_rate = round((all_replied / all_sent * 100), 1) if all_sent else 0

    return {
        "campaigns": campaigns,
        "stats": {
            "total_sent_24h": total_sent,
            "delivery_rate": delivery_rate,
            "reply_rate": reply_rate,
            "active_campaigns": active,
        },
    }


# ── POST /campaigns — create ──────────────────────────────────────────

@router.post("")
def create_campaign(
    tenant_id: str,
    body: CampaignCreate,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    with get_db_context() as conn:
        errors, template, segment = _campaign_errors(conn, body, tenant_id)
        if errors:
            raise HTTPException(422, "; ".join(errors))

        # A segment brings its own audience type and criteria; the criteria are
        # snapshotted onto the campaign so the request shows exactly what was
        # targeted even if the segment is edited later.
        audience = segment["audience_type"] if segment else body.audience_type
        criteria = json.loads(segment["criteria_json"] or "{}") if segment else {}
        target = _estimate_target_count(conn, criteria, tenant_id, audience)

        # Status is engine-owned: a campaign is either a draft or queued to
        # fire (immediately for 'now', at the chosen time for 'scheduled').
        status = "draft" if body.status == "draft" else "scheduled"
        message = (body.message_template or "").strip() or (template or {}).get("body_template", "")

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        cursor = conn.execute(
            """INSERT INTO campaigns
                (tenant_id, name, status, campaign_type, audience_type, segment_id, segment_json,
                 target_count, whatsapp_template, template_type, message_template,
                 template_variables_json, variable_fallbacks_json, buttons_json,
                 list_items_json, media_filename,
                 schedule_mode, scheduled_at, timezone, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tenant_id,
                body.name,
                status,
                body.campaign_type,
                body.audience_type,
                body.segment_id,
                json.dumps(criteria),
                target,
                body.whatsapp_template.strip(),
                body.template_type,
                message,
                json.dumps(body.template_variables),
                json.dumps(body.variable_fallbacks or {}),
                json.dumps(body.buttons),
                json.dumps(body.list_items),
                body.media_filename,
                body.schedule_mode,
                body.scheduled_at,
                body.timezone,
                now,
                now,
            ),
        )

        campaign_id = cursor.lastrowid

    logger.info(f"CAMPAIGN_CREATED | tenant={tenant_id} | id={campaign_id} | name={body.name}")
    return {"ok": True, "id": campaign_id}


# ── PUT /campaigns/{id} — update ──────────────────────────────────────

@router.put("/{campaign_id}")
def update_campaign(
    tenant_id: str,
    campaign_id: int,
    body: CampaignCreate,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    if body.status not in ADMIN_STATUSES:
        raise HTTPException(
            422,
            f"status is engine-managed; admins may only set: {', '.join(ADMIN_STATUSES)}",
        )

    with get_db_context() as conn:
        _get_campaign(conn, campaign_id, tenant_id)

        errors, template, segment = _campaign_errors(conn, body, tenant_id)
        if errors:
            raise HTTPException(422, "; ".join(errors))

        audience = segment["audience_type"] if segment else body.audience_type
        criteria = json.loads(segment["criteria_json"] or "{}") if segment else {}
        target = _estimate_target_count(conn, criteria, tenant_id, audience)
        message = (body.message_template or "").strip() or (template or {}).get("body_template", "")

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        result = conn.execute(
            """UPDATE campaigns SET
                name = ?, status = ?, campaign_type = ?, audience_type = ?, segment_id = ?,
                segment_json = ?, target_count = ?, whatsapp_template = ?, template_type = ?,
                message_template = ?, template_variables_json = ?, variable_fallbacks_json = ?,
                buttons_json = ?, list_items_json = ?, media_filename = ?, schedule_mode = ?,
                scheduled_at = ?, timezone = ?, updated_at = ?
            WHERE id = ? AND tenant_id = ?""",
            (
                body.name,
                body.status,
                body.campaign_type,
                body.audience_type,
                body.segment_id,
                json.dumps(criteria),
                target,
                body.whatsapp_template.strip(),
                body.template_type,
                message,
                json.dumps(body.template_variables),
                json.dumps(body.variable_fallbacks or {}),
                json.dumps(body.buttons),
                json.dumps(body.list_items),
                body.media_filename,
                body.schedule_mode,
                body.scheduled_at,
                body.timezone,
                now,
                campaign_id,
                tenant_id,
            ),
        )

        if result.rowcount == 0:
            raise HTTPException(404, f"Campaign {campaign_id} not found")

    logger.info(f"CAMPAIGN_UPDATED | tenant={tenant_id} | id={campaign_id}")
    return {"ok": True}


# ── DELETE /campaigns/{id} ────────────────────────────────────────────

@router.delete("/{campaign_id}")
def delete_campaign(
    tenant_id: str,
    campaign_id: int,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    with get_db_context() as conn:
        result = conn.execute(
            "DELETE FROM campaigns WHERE id = ? AND tenant_id = ?",
            (campaign_id, tenant_id),
        )

        if result.rowcount == 0:
            raise HTTPException(404, f"Campaign {campaign_id} not found")

    logger.info(f"CAMPAIGN_DELETED | tenant={tenant_id} | id={campaign_id}")
    return {"ok": True}


# ── POST /campaigns/{id}/duplicate ────────────────────────────────────

@router.post("/{campaign_id}/duplicate")
def duplicate_campaign(
    tenant_id: str,
    campaign_id: int,
    current_admin: dict = Depends(require_permission("manage_campaigns")),
):
    with get_db_context() as conn:
        row = _get_campaign(conn, campaign_id, tenant_id)

        d = dict(row)
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        cursor = conn.execute(
            """INSERT INTO campaigns
                (tenant_id, name, status, campaign_type, audience_type, segment_json, target_count,
                 whatsapp_template, template_type, message_template, template_variables_json,
                 buttons_json, list_items_json, media_filename,
                 schedule_mode, scheduled_at, timezone, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tenant_id,
                f"{d['name']} (copy)",
                "draft",
                d.get("campaign_type", "promotional"),
                d["audience_type"],
                d["segment_json"],
                d["target_count"],
                d.get("whatsapp_template", ""),
                d["template_type"],
                d["message_template"],
                d["template_variables_json"],
                d["buttons_json"],
                d["list_items_json"],
                d["media_filename"],
                d["schedule_mode"],
                None,
                d["timezone"],
                now,
                now,
            ),
        )

        new_id = cursor.lastrowid

    logger.info(f"CAMPAIGN_DUPLICATED | tenant={tenant_id} | from={campaign_id} → to={new_id}")
    return {"ok": True, "id": new_id}


# ── POST /campaigns/audience/count ────────────────────────────────────

@router.post("/audience/count")
def audience_count(
    tenant_id: str,
    body: AudienceCount,
    current_admin: dict = Depends(require_tenant_access),
):
    """Live preview of how many contacts a set of criteria reaches."""
    errors = _criteria_errors(body.audience_type, body.criteria)
    if errors:
        raise HTTPException(422, "; ".join(errors))
    with get_db_context() as conn:
        count = _estimate_target_count(conn, body.criteria, tenant_id, body.audience_type)

    return {"count": count}


# ── GET /campaigns/{id}/metrics ───────────────────────────────────────

@router.get("/{campaign_id}/metrics")
def campaign_metrics(
    tenant_id: str,
    campaign_id: int,
    current_admin: dict = Depends(require_tenant_access),
):
    with get_db_context() as conn:
        row = _get_campaign(conn, campaign_id, tenant_id)
        d = dict(row)

    return {
        "campaign_id": campaign_id,
        "status": d["status"],
        "progress": {
            "sent": d["sent"],
            "total": d["target_count"],
        },
        "funnel": {
            "sent": d["sent"],
            "delivered": d["delivered"],
            "read": d["read_count"],
            "replied": d["replied"],
        },
    }


# ── GET /campaigns/{id}/replies ───────────────────────────────────────

@router.get("/{campaign_id}/replies")
def campaign_replies(
    tenant_id: str,
    campaign_id: int,
    current_admin: dict = Depends(require_tenant_access),
):
    with get_db_context() as conn:
        _get_campaign(conn, campaign_id, tenant_id)

        rows = conn.execute(
            """SELECT wa_id, name, reply_text, replied_at
            FROM campaign_replies
            WHERE campaign_id = ?
            ORDER BY replied_at DESC""",
            (campaign_id,),
        ).fetchall()

    return {"replies": [dict(r) for r in rows]}
