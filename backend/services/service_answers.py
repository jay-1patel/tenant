"""Deterministic, tenant-scoped replies for service enquiries."""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("services.service_answers")

SERVICE_QUERY_PHRASES = (
    "service", "services", "offering", "offerings", "what do you do",
    "what do you offer", "what services", "service brochure", "brochure of services",
)
BROAD_SERVICE_PHRASES = (
    "our services", "your services", "what services", "list services",
    "services do you offer", "what do you offer", "tell me about your services",
    "what service do you", "service do you provide", "services do you provide",
    "service brochure", "brochure of services",
)


def is_service_query(text: str) -> bool:
    query = (text or "").strip().lower()
    return any(phrase in query for phrase in SERVICE_QUERY_PHRASES)


def answer_for_text(wa_id: str, text: str, tenant_id: str | None = None) -> str | None:
    """Return only configured service records for a recognized service query."""
    query = (text or "").strip()
    if not query:
        return None

    try:
        from shared.tenancy.loader import get_tenant_profile
        from shared.tenancy.resolver import resolve_tenant_for_user
        from shared.tenancy.intent_match import match_by_rules
        try:
            from backend.database import list_products
        except ImportError:
            from database import list_products

        tid = tenant_id or resolve_tenant_for_user(wa_id or "")
        profile = get_tenant_profile(tid)
        intent = profile.intent("service_enquiry")
        offerings = list_products(active_only=True, limit=100, tenant_id=tid)
        selected = _matching_offerings(query, offerings)
        broad = any(phrase in query.lower() for phrase in BROAD_SERVICE_PHRASES) or query.lower() in {"service", "services", "offerings"}
        matched = match_by_rules(query, [intent]) if intent and intent.enabled else None
        if not matched and not selected and not broad:
            return None
        if not profile.feature_on("offerings") or (intent is not None and not intent.enabled):
            return "Service information isn't available right now. Please contact our team for help."
        if not selected and (matched or broad):
            selected = offerings
    except Exception as exc:
        logger.warning("Could not resolve tenant services for %s: %s", wa_id, exc)
        return None

    if not selected:
        return "We don't have any services listed right now. Please contact our team for details."

    lines = ["Here are the services we offer:"]
    for item in selected[:10]:
        name = (item.get("name") or "").strip()
        if not name:
            continue
        lines.append(f"• *{name}*")
        description = (item.get("short_description") or item.get("description") or "").strip()
        if description:
            lines.append(f"  {description[:240]}")
    return "\n".join(lines) if len(lines) > 1 else "We don't have any services listed right now. Please contact our team for details."


def _matching_offerings(query: str, offerings: list[dict]) -> list[dict]:
    normalized = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
    matches = []
    for item in offerings:
        name = re.sub(r"[^a-z0-9]+", " ", str(item.get("name") or "").lower()).strip()
        if name and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", normalized):
            matches.append(item)
    return matches
