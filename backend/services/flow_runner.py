"""
Profile-driven flow runner (Phase 3).

One runner executes every flow defined in a tenant profile (shared/tenancy
schemas.FlowSpec / FlowStep). The only fixed contract is the step types; a new
tenant ships data, never code.

State: conversation progress lives in user_states via services/state_manager
(decision D3 — no parallel store). Side effects write `leads` and `handoffs`.
Notifications fan out through shared/tenancy.signing.notify (email + signed
webhook, per-tenant config).

Delivery: the runner NEVER sends WhatsApp messages itself. It returns the
outbound messages in its outcome dict; the webhook layer sends them. That
keeps the runner testable without WhatsApp credentials.

Complaint wrap: a save_lead with lead_source="complaint" also inserts a
`complaints` row (same shape routing.complaint_flow writes) so the existing
complaints admin keeps working while the runner owns the conversation. The
legacy complaint_flow stays in place for the routing/ stack until Phase 7.
"""
import json
import logging
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

# shared.tenancy lives at the repo root, not next to this file.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("flow_runner")

CANCEL_WORDS = {"cancel", "stop", "quit", "exit", "menu", "nevermind", "never mind", "cancel it"}
SKIP_WORDS = {"skip", "-", "na", "n/a", "none", "no email"}

_STATUS_BOT = "bot"
_STATUS_PAUSED = "paused"


# ── profile / tenant resolution ───────────────────────────────────────────

def _profile(tenant_id=None, wa_id=None):
    from shared.tenancy.loader import get_tenant_profile
    from shared.tenancy.resolver import resolve_tenant_for_user

    return get_tenant_profile(tenant_id or resolve_tenant_for_user(wa_id or ""))


def _db():
    # `database` (backend/database.py) resolves when backend/ is on sys.path —
    # the style used by state_manager and the services layer.
    import database as db
    return db


def _state():
    # Works under both import styles used in this repo: `services.X` (webhook,
    # backend dir on sys.path) and `backend.services.X`.
    try:
        from services import state_manager
    except ImportError:
        from backend.services import state_manager
    return state_manager


# ── validation ─────────────────────────────────────────────────────────────

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def validate_answer(rule: str, value: str) -> bool:
    """Validate a free-text answer against a step's validate rule.

    Rules: email | phone:<digits> | name:<min_chars> | digits | min_len:<n>.
    An empty rule accepts any non-empty answer (the caller checks emptiness).
    """
    value = (value or "").strip()
    if not rule:
        return bool(value)
    rule = rule.strip().lower()
    if rule == "email":
        return bool(_EMAIL_RE.match(value))
    if rule == "digits":
        return bool(value) and value.isdigit()
    if rule.startswith("phone"):
        digits = re.sub(r"\D", "", value)
        wanted = int(rule.split(":", 1)[1]) if ":" in rule else 10
        return len(digits) >= wanted
    if rule.startswith("name"):
        wanted = int(rule.split(":", 1)[1]) if ":" in rule else 2
        return len(value.replace(" ", "")) >= wanted
    if rule.startswith("min_len"):
        wanted = int(rule.split(":", 1)[1]) if ":" in rule else 1
        return len(value) >= wanted
    # Unknown rule: never block the user on our authoring mistake.
    logger.warning("Unknown validate rule %r — accepting answer", rule)
    return True


# ── outcome contract ──────────────────────────────────────────────────────

def _outcome(flow_name, messages, *, finished=False, lead_id=None,
             handoff_id=None, status=_STATUS_BOT):
    return {
        "handled": True,
        "flow": flow_name,
        "finished": finished,
        "messages": messages,
        "lead_id": lead_id,
        "handoff_id": handoff_id,
        "status": status,
    }


# ── side effects ───────────────────────────────────────────────────────────

def _lead_payload(collected: dict, collect_keys: list) -> dict:
    data = {k: v for k, v in collected.items() if not str(k).startswith("_")}
    if collect_keys:
        keep = {k.lower() for k in collect_keys}
        data = {k: v for k, v in data.items() if str(k).lower() in keep}
    return data


def _save_lead(tenant_id: str, wa_id: str, flow_name: str,
               collected: dict, collect_keys: list, lead_source: str) -> int:
    data = _lead_payload(collected, collect_keys)
    with _db().get_db_context() as conn:
        cur = conn.execute(
            """INSERT INTO leads (tenant_id, wa_id, user_name, phone, email,
               collected, status, source, flow)
               VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?)""",
            (
                tenant_id, wa_id,
                str(data.get("name") or ""),
                str(data.get("phone") or ""),
                str(data.get("email") or ""),
                json.dumps(data, ensure_ascii=False),
                lead_source or flow_name,
                flow_name,
            ),
        )
        lead_id = cur.lastrowid
    logger.info("LEAD_SAVED | tenant=%s | flow=%s | lead_id=%s", tenant_id, flow_name, lead_id)

    # Complaint wrap: keep the legacy complaints admin surface alive while
    # the runner owns the conversation (see module docstring).
    if (lead_source or "").lower() in ("complaint", "ticket", "support_ticket"):
        _insert_complaint_row(tenant_id, wa_id, data)
    return lead_id


def _insert_complaint_row(tenant_id: str, wa_id: str, data: dict) -> str:
    now = datetime.now().isoformat()
    ticket_id = f"CMP-{uuid.uuid4().hex[:8].upper()}"
    description = " ".join(
        f"{k}: {v}" for k, v in data.items() if k not in ("name", "phone", "email")
    ) or (data.get("need") or "")
    try:
        with _db().get_db_context() as conn:
            conn.execute(
                """INSERT INTO complaints (ticket_id, wa_id, complaint_type, description,
                   status, priority, subject, updated_at, created_at, tenant_id)
                   VALUES (?, ?, ?, ?, 'open', 'normal', ?, ?, ?, ?)""",
                (
                    ticket_id, wa_id, "Other", description,
                    (data.get("need") or "WhatsApp complaint")[:120],
                    now, now, tenant_id,
                ),
            )
        logger.info("COMPLAINT_WRAPPED | tenant=%s | ticket=%s", tenant_id, ticket_id)
    except Exception as e:
        logger.error("Complaint wrap insert failed: %s", e)
    return ticket_id


def _notify_step(tenant_id: str, wa_id: str, flow_name: str, step, collected: dict,
                 lead_id=None) -> list:
    """Fan the notify step out to the tenant's channels. Failures are logged,
    never fatal — the lead is already in the database."""
    from shared.tenancy.signing import notify as fanout

    payload = {k: v for k, v in collected.items() if not str(k).startswith("_")}
    payload["wa_id"] = wa_id
    payload["flow"] = flow_name
    if lead_id:
        payload["lead_id"] = lead_id

    event = (step.subject or "").strip() or f"flow:{flow_name}"
    try:
        channels = None  # None = every active channel in the profile
        if step.channels:
            profile = _profile(tenant_id)
            picked = []
            for kind in step.channels:
                picked.extend(profile.notifications.active_channels(kind))
            channels = picked
        results = fanout(tenant_id, event, payload, channels=channels)
        ok = sum(1 for r in results if r.get("ok"))
        logger.info("FLOW_NOTIFY | tenant=%s | flow=%s | ok=%s/%s",
                    tenant_id, flow_name, ok, len(results))
        return results
    except Exception as e:
        logger.error("FLOW_NOTIFY_FAILED | tenant=%s | flow=%s | %s", tenant_id, flow_name, e)
        return []


def _handoff(tenant_id: str, wa_id: str, flow_name: str, step,
             collected: dict) -> int:
    reason = step.handoff_reason or flow_name
    data = {k: v for k, v in collected.items() if not str(k).startswith("_")}
    with _db().get_db_context() as conn:
        cur = conn.execute(
            """INSERT INTO handoffs (tenant_id, wa_id, user_name, reason, flow,
               context, collected, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
            (
                tenant_id, wa_id,
                str(data.get("name") or ""),
                reason, flow_name,
                json.dumps({"wa_id": wa_id}, ensure_ascii=False),
                json.dumps(data, ensure_ascii=False),
            ),
        )
        handoff_id = cur.lastrowid
    logger.info("HANDOFF_CREATED | tenant=%s | flow=%s | handoff_id=%s",
                tenant_id, flow_name, handoff_id)
    return handoff_id


# ── the runner ─────────────────────────────────────────────────────────────

def is_running(wa_id: str) -> bool:
    return bool(_state().active_flow(wa_id))


def _save_integration_step(tenant_id: str, wa_id: str, flow_name: str,
                           collected: dict) -> int | None:
    """Persist a delivery/payment onboarding submission as a pending request.

    The chatbot collected the user's provider choices and API details; this
    writes one `integration_requests` row for a super admin to approve. On
    approval the config is merged into the tenant's published profile.
    """
    try:
        from shared.tenancy import integrations as integ
        from database import save_integration_request
    except Exception as exc:
        logger.error("INTEGRATION_SAVE_FAIL | tenant=%s | %s", tenant_id, exc)
        return None

    delivery_provider = str(collected.get("delivery_provider") or "").strip().lower()
    payment_provider = str(collected.get("payment_provider") or "").strip().lower()
    if not delivery_provider and not payment_provider:
        logger.error("INTEGRATION_SAVE_FAIL | tenant=%s | no providers given", tenant_id)
        return None

    # Map any free-text choice onto the registry; unknown providers are kept
    # as-is so a super admin can still review them.
    def _canon(kind: str, value: str) -> str:
        value = (value or "").strip().lower()
        for known in integ.known_providers(kind):
            if value == known or value == integ.provider_label(kind, known).lower():
                return known
        return value

    delivery_provider = _canon("delivery", delivery_provider)
    payment_provider = _canon("payment", payment_provider)

    delivery_config = {}
    for field in integ.config_fields("delivery", delivery_provider):
        key = "delivery_" + field["key"]
        if collected.get(key):
            delivery_config[field["key"]] = str(collected.get(key))
    payment_config = {}
    for field in integ.config_fields("payment", payment_provider):
        key = "payment_" + field["key"]
        if collected.get(key):
            payment_config[field["key"]] = str(collected.get(key))

    # Anything else the user shared for a provider that is not in the registry
    # still travels through, keyed by its ask step.
    for k, v in collected.items():
        if k.startswith("delivery_") and k[len("delivery_"):] not in delivery_config:
            delivery_config.setdefault(k[len("delivery_"):], str(v))
        if k.startswith("payment_") and k[len("payment_"):] not in payment_config:
            payment_config.setdefault(k[len("payment_"):], str(v))

    req_id = save_integration_request(
        tenant_id, wa_id,
        delivery_provider, delivery_config,
        payment_provider, payment_config,
    )

    # Alert the admin surface the way handoffs do: a pending request nobody
    # sees is an integration that never goes live.
    try:
        from services.alerts import send_alert
        send_alert(
            "New delivery/payment integration request (id %s) from %s on tenant "
            "'%s' — delivery: %s, payment: %s. Approve it in the admin panel." % (
                req_id, wa_id, tenant_id,
                integ.provider_label("delivery", delivery_provider),
                integ.provider_label("payment", payment_provider),
            ),
            severity="warning",
        )
    except Exception:
        pass

    return req_id


def flow_for_button(wa_id: str, button_id: str, tenant_id=None):
    """The flow a profile menu button starts, or None.

    Only returns flows whose feature flag is on — the caller falls through to
    the existing pipeline when we return None, so a refused flow can never
    change today's behaviour.
    """
    try:
        profile = _profile(tenant_id, wa_id)
    except Exception as e:
        logger.debug("flow_for_button: profile unavailable: %s", e)
        return None
    for b in profile.menu.buttons:
        if b.id == button_id and getattr(b, "flow", None):
            flow = profile.flow(b.flow)
            if flow and (not flow.requires_feature or profile.feature_on(flow.requires_feature)):
                return flow.name
            logger.info("Button %s wants flow %s but its feature is off — "
                        "falling through to the default pipeline", button_id, b.flow)
            return None
    return None


def start_flow(wa_id: str, flow_name: str, tenant_id=None) -> dict:
    """Begin a flow for a user. Respects out-of-hours variants.

    Returns an outcome dict (never raises): ok=False outcomes carry an error
    the caller can log and fall through on.
    """
    sm = _state()
    try:
        profile = _profile(tenant_id, wa_id)
    except Exception as e:
        return {"handled": False, "ok": False, "error": "profile_unavailable", "messages": []}

    from shared.tenancy.hours import select_flow_name
    flow_name = select_flow_name(profile.tenant_id, flow_name)

    flow = profile.flow(flow_name)
    if flow is None:
        return {"handled": False, "ok": False, "error": "unknown_flow",
                "flow": flow_name, "messages": []}
    if flow.requires_feature and not profile.feature_on(flow.requires_feature):
        return {"handled": False, "ok": False, "error": "feature_disabled",
                "flow": flow_name, "messages": []}

    sm.ensure_conversation_row(wa_id)
    sm.set_tenant(wa_id, profile.tenant_id)
    sm.start_flow(wa_id, flow.name)

    messages = []
    if flow.start_message and flow.steps and flow.steps[0].type != "say":
        messages.append(flow.start_message)

    return _run_from(wa_id, profile, flow, flow.first_step_id(), {}, messages)


def handle_reply(wa_id: str, text: str, tenant_id=None):
    """Advance the running flow with a user reply. None when no flow runs."""
    sm = _state()
    convo = sm.read_conversation(wa_id)
    if not convo or not convo.get("active_flow"):
        return None

    try:
        profile = _profile(tenant_id or convo.get("tenant_id"), wa_id)
    except Exception as e:
        logger.error("handle_reply: profile unavailable: %s", e)
        sm.clear_flow(wa_id)
        return None

    flow = profile.flow(convo["active_flow"])
    if flow is None:
        # Profile changed under a running flow — don't leave the user stuck.
        sm.clear_flow(wa_id)
        return _outcome(convo["active_flow"], ["Sorry — that form is no longer available. "
                                               "Type *menu* to see what I can help with."],
                        finished=True)

    # Cancel always works, from any step.
    if (text or "").strip().lower() in CANCEL_WORDS:
        sm.clear_flow(wa_id)
        return _outcome(flow.name, ["Okay, I've cancelled that. Type *menu* anytime to "
                                     "see what I can help with."], finished=True)

    collected = dict(convo.get("collected") or {})
    step = flow.step(convo.get("current_step") or "") or flow.step(flow.first_step_id())
    if step is None:
        sm.clear_flow(wa_id)
        return _outcome(flow.name, [], finished=True)

    messages = []
    answer = (text or "").strip()

    # ── input steps: consume this reply ────────────────────────────
    if step.type == "ask":
        key = step.key or step.id
        if step.optional and answer.lower() in SKIP_WORDS:
            collected[key] = ""
            collected.pop("_attempts", None)
        elif not answer:
            return _retry(wa_id, flow, step, collected,
                         "Please reply with an answer, or type *cancel*.")
        elif validate_answer(step.validate_rule, answer):
            collected[key] = answer
            collected.pop("_attempts", None)
        else:
            return _retry(wa_id, flow, step, collected,
                          step.invalid_message or "That doesn't look right — please try again.")
        next_id = step.on.get(str(collected[key]).lower()) if step.on else None
        sm.merge_collected(wa_id, {key: collected[key]})
        return _run_from(wa_id, profile, flow, next_id or step.next, collected, messages)

    if step.type == "choice":
        match = _match_choice(answer, step.options)
        if match is None:
            return _retry(wa_id, flow, step, collected,
                          step.invalid_message or
                          f"Please pick one of: {', '.join(step.options)}")
        key = step.key or step.id
        collected[key] = match
        sm.merge_collected(wa_id, {key: match})
        next_id = (step.on.get(match.lower()) or step.on.get(match)) if step.on else None
        return _run_from(wa_id, profile, flow, next_id or step.next, collected, messages)

    if step.type == "confirm":
        verdict = _yes_no(answer, step)
        if verdict is None:
            return _retry(wa_id, flow, step, collected,
                          step.invalid_message or
                          f"Please reply *{step.yes_label}* or *{step.no_label}*.")
        collected[step.key or step.id] = verdict
        sm.merge_collected(wa_id, {step.key or step.id: verdict})
        next_id = step.on.get(verdict) if step.on else None
        return _run_from(wa_id, profile, flow, next_id or step.next, collected, messages)

    # A non-input step is current (shouldn't happen, but stay robust):
    # execute forward from it.
    return _run_from(wa_id, profile, flow, step.id, collected, messages)


# ── internals ─────────────────────────────────────────────────────────────

def _retry(wa_id, flow, step, collected, message):
    """Count a failed attempt; bail out with the failure message past the cap."""
    sm = _state()
    attempts = collected.get("_attempts") or {}
    n = attempts.get(step.id, 0) + 1
    if n >= step.max_attempts:
        sm.clear_flow(wa_id)
        return _outcome(flow.name, [message, flow.failure_message], finished=True)
    attempts[step.id] = n
    collected["_attempts"] = attempts
    sm.merge_collected(wa_id, {"_attempts": attempts})
    return _outcome(flow.name, [message])


def _match_choice(answer: str, options: list):
    a = (answer or "").strip().lower()
    if not a:
        return None
    for opt in options:
        o = (opt or "").strip().lower()
        if a == o or (len(a) >= 3 and a in o) or (len(o) >= 3 and o in a):
            return opt
    return None


def _yes_no(answer: str, step):
    a = (answer or "").strip().lower()
    yes = {(step.yes_label or "yes").lower(), "yes", "y", "yeah", "sure", "ok", "okay", "correct"}
    no = {(step.no_label or "no").lower(), "no", "n", "nope", "cancel"}
    if a in yes:
        return "yes"
    if a in no:
        return "no"
    return None


def _next_after(step, verdict=None) -> str:
    if step.goto:
        return step.goto
    if step.on and verdict:
        return step.on.get(verdict) or step.on.get(verdict.lower()) or step.next
    return step.next


def _run_from(wa_id, profile, flow, step_id, collected, messages):
    """Drain non-input steps until the flow needs input or ends.

    say / save_lead / notify / handoff / book_appointment / create_ticket all
    execute here; ask / choice / confirm park the flow on their prompt.
    """
    sm = _state()
    lead_id = None
    handoff_id = None
    paused = False
    emitted_done = False

    while step_id:
        step = flow.step(step_id)
        if step is None:
            break

        if step.type in ("ask", "choice", "confirm"):
            prompt = step.prompt or step.message
            if prompt:
                messages.append(prompt)
            sm.set_step(wa_id, step.id)
            return _outcome(flow.name, messages, lead_id=lead_id,
                            handoff_id=handoff_id,
                            status=_STATUS_PAUSED if paused else _STATUS_BOT)

        if step.type == "say":
            text = step.prompt or step.message
            if text:
                messages.append(text)
                if text == flow.success_message:
                    emitted_done = True

        elif step.type in ("save_lead", "book_appointment", "create_ticket"):
            source = step.lead_source or (
                {"book_appointment": "appointment",
                 "create_ticket": "ticket"}.get(step.type, flow.name))
            lead_id = _save_lead(profile.tenant_id, wa_id, flow.name,
                                 collected, step.collect_keys, source) or lead_id

        elif step.type == "notify":
            _notify_step(profile.tenant_id, wa_id, flow.name, step, collected, lead_id)
        elif step.type == "save_integration":
            _save_integration_step(profile.tenant_id, wa_id, flow.name, collected)

        elif step.type == "handoff":
            handoff_id = _handoff(profile.tenant_id, wa_id, flow.name, step, collected)
            paused = True
            if step.prompt and step.prompt not in messages:
                messages.append(step.prompt)

        else:
            logger.error("FLOW_SKIP | unknown step type %r in flow %s", step.type, flow.name)

        step_id = _next_after(step)

    # Flow finished.
    sm.clear_flow(wa_id, reset_status=not paused)
    if paused:
        sm.set_status(wa_id, _STATUS_PAUSED)
    if flow.success_message and not emitted_done and flow.success_message not in messages:
        messages.append(flow.success_message)
    return _outcome(flow.name, messages, finished=True, lead_id=lead_id,
                    handoff_id=handoff_id,
                    status=_STATUS_PAUSED if paused else _STATUS_BOT)
