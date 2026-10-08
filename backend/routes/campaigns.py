import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
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
ADMIN_STATUSES = ("draft", "scheduled", "cancelled")
AUDIENCE_TYPES = ("all", "distributors", "customers", "segments")
MEDIA_EXTENSIONS = ("jpg", "jpeg", "png", "mp4")
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
    segment: dict | None = None
    target_count: int = 0
    whatsapp_template: str = ""
    template_type: str = "whatsapp_template"
    message_template: str = ""
    template_variables: dict = {}
    buttons: list = []
    list_items: list = []
    media_filename: str | None = None
    schedule_mode: str = "now"
    scheduled_at: str | None = None
    timezone: str = "Asia/Kolkata"


class AudienceSegment(BaseModel):
    segment: dict | None = None


class TemplateCreate(BaseModel):
    name: str = ""
    category: str = "promotional"
    body: str = ""


class TemplateStatus(BaseModel):
    status: str = "approved"


# ── Helpers ────────────────────────────────────────────────────────────

def _row_to_dict(row) -> dict:
    d = dict(row)

    for key in ("segment_json", "template_variables_json", "buttons_json", "list_items_json"):
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


def _estimate_target_count(conn, segment: dict | None, tenant_id: str, audience_type: str = "distributors") -> int:
    """Count the contacts a campaign will reach.

    Customers are the tenant's chat contacts; distributors and segments are
    counted from the distributor directory (with the segment's filters).
    """
    if audience_type == "customers":
        row = conn.execute(
            "SELECT COUNT(DISTINCT wa_id) AS cnt FROM chat_history WHERE tenant_id = ?",
            (tenant_id,),
        ).fetchone()
        return row["cnt"] if row else 0

    clauses, params = ["tenant_id = ?"], [tenant_id]

    if segment:
        regions = segment.get("regions", [])
        if regions and "All" not in regions:
            placeholders = ",".join("?" for _ in regions)
            clauses.append(f"region IN ({placeholders})")
            params.extend(regions)

        tiers = segment.get("tiers", [])
        if tiers:
            placeholders = ",".join("?" for _ in tiers)
            clauses.append(f"tier IN ({placeholders})")
            params.extend(tiers)

        interests = segment.get("product_interests", [])
        for interest in interests:
            clauses.append("product_interests LIKE ?")
            params.append(f"%{interest}%")

    row = conn.execute(
        f"SELECT COUNT(*) AS cnt FROM distributors WHERE {' AND '.join(clauses)}",
        params,
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
    if body.audience_type == "segments" and not body.segment:
        errors.append("a segment must be selected for the segments audience")

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

    return errors, template


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
            "language, status, registered_at, updated_at "
            "FROM whatsapp_templates ORDER BY name COLLATE NOCASE",
        ).fetchall()
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
                "status": r["status"],
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

    import database as db

    if db.get_template(name):
        raise HTTPException(409, f"a template named '{name}' already exists")

    template_id = db.save_template(name, {
        "category": body.category,
        "body_template": body.body,
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
    if body.status not in TEMPLATE_STATUSES:
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


# ── Segments — named audiences derived from the tenant's data ───────────

@router.get("/segments")
def list_segments(
    tenant_id: str,
    current_admin: dict = Depends(require_tenant_access),
):
    """Named segments built from the distributor directory, each mapped to the
    region / tier filters the audience counter understands."""
    with get_db_context() as conn:
        regions = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT region FROM distributors "
                "WHERE tenant_id = ? AND TRIM(region) != '' ORDER BY region",
                (tenant_id,),
            ).fetchall()
        ]
        tiers = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT tier FROM distributors "
                "WHERE tenant_id = ? AND TRIM(tier) != '' ORDER BY tier",
                (tenant_id,),
            ).fetchall()
        ]

    segments = [{"id": "all", "label": "All distributors", "segment": {}}]
    high_value = [t for t in ("Gold", "Platinum") if t in tiers]
    if len(high_value) > 1:
        segments.append({
            "id": "high_value",
            "label": "High value distributors (Gold & Platinum)",
            "segment": {"tiers": high_value},
        })
    for tier in tiers:
        segments.append({"id": f"tier:{tier}", "label": f"{tier} tier", "segment": {"tiers": [tier]}})
    for region in regions:
        segments.append({"id": f"region:{region}", "label": f"Region: {region}", "segment": {"regions": [region]}})
    return {"segments": segments}


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
        errors, template = _campaign_errors(conn, body, tenant_id)
        if errors:
            raise HTTPException(422, "; ".join(errors))

        target = _estimate_target_count(conn, body.segment, tenant_id, body.audience_type)

        # Status is engine-owned: a campaign is either a draft or queued to
        # fire (immediately for 'now', at the chosen time for 'scheduled').
        status = "draft" if body.status == "draft" else "scheduled"
        message = (body.message_template or "").strip() or (template or {}).get("body_template", "")

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
                body.name,
                status,
                body.campaign_type,
                body.audience_type,
                json.dumps(body.segment or {}),
                target,
                body.whatsapp_template.strip(),
                body.template_type,
                message,
                json.dumps(body.template_variables),
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

        errors, template = _campaign_errors(conn, body, tenant_id)
        if errors:
            raise HTTPException(422, "; ".join(errors))

        target = _estimate_target_count(conn, body.segment, tenant_id, body.audience_type)
        message = (body.message_template or "").strip() or (template or {}).get("body_template", "")

        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        result = conn.execute(
            """UPDATE campaigns SET
                name = ?, status = ?, campaign_type = ?, audience_type = ?, segment_json = ?,
                target_count = ?, whatsapp_template = ?, template_type = ?, message_template = ?,
                template_variables_json = ?, buttons_json = ?, list_items_json = ?,
                media_filename = ?, schedule_mode = ?, scheduled_at = ?,
                timezone = ?, updated_at = ?
            WHERE id = ? AND tenant_id = ?""",
            (
                body.name,
                body.status,
                body.campaign_type,
                body.audience_type,
                json.dumps(body.segment or {}),
                target,
                body.whatsapp_template.strip(),
                body.template_type,
                message,
                json.dumps(body.template_variables),
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
    body: AudienceSegment,
    current_admin: dict = Depends(require_tenant_access),
):
    with get_db_context() as conn:
        count = _estimate_target_count(conn, body.segment, tenant_id)

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
