"""Profile-driven answers for informational intents (panels).

Menu rows like Technologies, Projects, Careers and Benefits have no flow and
no backend service: their entire content is tenant data. The answer text lives
in the tenant profile (vertical defaults -> clients/<id>/config.json ->
published DB version), so a tenant that publishes new text changes the panel
without a code change — nothing here is brand-specific.

Resolution never raises: every function returns None when the profile layer is
unavailable or the tenant configured no answer, and the caller then falls
through to the existing pipeline unchanged.
"""
import logging

logger = logging.getLogger("services.intent_answers")


def _profile(tenant_id=None, wa_id: str = ""):
    """The tenant profile, or None. Same defensive pattern as flow_runner."""
    try:
        import sys as _sys
        from pathlib import Path as _Path

        root = str(_Path(__file__).resolve().parents[2])
        if root not in _sys.path:
            _sys.path.insert(0, root)

        from shared.tenancy.loader import get_tenant_profile
        from shared.tenancy.resolver import resolve_tenant_for_user

        return get_tenant_profile(tenant_id or resolve_tenant_for_user(wa_id or ""))
    except Exception as exc:  # pragma: no cover - defensive by design
        logger.debug("intent_answers: profile unavailable (%s)", exc)
        return None


def _answered_intents(profile) -> list:
    """Active intents that carry answer text, in profile order."""
    if profile is None:
        return []
    active = {i.name for i in profile.active_intents()}
    return [
        i for i in profile.intents
        if i.name in active and (i.answer or "").strip()
    ]


def answer_for_button(wa_id: str, button_id: str, tenant_id=None) -> str | None:
    """Answer text for a tapped profile menu row, or None.

    Dispatches on the button id (load-bearing, stable) via its ``intent``
    field — the row's title never enters the decision.
    """
    if not button_id:
        return None
    profile = _profile(tenant_id, wa_id)
    if profile is None:
        return None
    for b in profile.menu.buttons:
        if b.id == button_id and getattr(b, "intent", None):
            return answer_for_intent(wa_id, b.intent, tenant_id=tenant_id or profile.tenant_id)
    return None


def answer_for_intent(wa_id: str, intent_name: str, tenant_id=None) -> str | None:
    """Answer text for a named intent (also serves registry buttons, whose ids
    match intent names by convention: projects, technologies, careers,
    benefits). None unless the intent is active AND has answer text."""
    if not intent_name:
        return None
    profile = _profile(tenant_id, wa_id)
    if profile is None:
        return None
    for intent in _answered_intents(profile):
        if intent.name == intent_name:
            return intent.answer.strip()
    return None


def answer_for_text(wa_id: str, text: str, tenant_id=None) -> str | None:
    """Answer text for a typed query, via the rules tier of intent matching.

    Deliberately rules-only (exact examples + word-boundary keywords): this
    runs in front of the LLM pipeline, so it must stay cheap and
    deterministic. An utterance that does not clearly name a panel falls
    through to the normal FAQ/KB path.
    """
    if not (text or "").strip():
        return None
    profile = _profile(tenant_id, wa_id)
    if profile is None:
        return None
    try:
        from shared.tenancy.intent_match import match_by_rules

        candidates = _answered_intents(profile)
        if not candidates:
            return None
        matched = match_by_rules(text, candidates)
        if not matched:
            return None
        intent_name, score = matched
        for intent in candidates:
            if intent.name == intent_name:
                return intent.answer.strip()
    except Exception as exc:
        logger.debug("intent_answers: text match failed (%s)", exc)
    return None
