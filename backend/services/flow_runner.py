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

CANCEL_WORDS = {
    "cancel", "stop", "quit", "exit", "menu", "main menu", "nevermind", "never mind",
    "cancel it", "cancel form", "back", "home", "restart", "start over", "leave",
    "abort", "close", "end", "done", "clear", "break", "forget it", "opt out",
}
SKIP_WORDS = {"skip", "-", "na", "n/a", "none", "no email"}

_STATUS_BOT = "bot"
_STATUS_PAUSED = "paused"

_QUESTION_STARTERS = (
    "what", "how", "where", "when", "why", "who", "which",
    "can", "could", "would", "should", "do", "does", "did", "is", "are", "will", "may",
    "tell me", "show me", "i want to", "i would like", "i have a question",
    "details of", "information on", "info about", "price of", "cost of",
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
)


def _is_explicit_topic_switch(text: str, tenant_id=None) -> bool:
    """Return True if the text is definitively invoking another service/intent/topic."""
    if not text:
        return False
    t = text.strip().lower()
    if "?" in t:
        return True
    try:
        try:
            from services import intent_answers, service_answers
        except ImportError:
            from backend.services import intent_answers, service_answers
        if service_answers.is_service_query(t):
            return True
        if intent_answers.answer_for_text("", t, tenant_id=tenant_id):
            return True
        if intent_answers.answer_for_menu_title("", t, tenant_id=tenant_id):
            return True
    except Exception:
        pass
    switch_starters = (
        "what are your", "what is your", "tell me about", "show me",
        "how much", "what services", "what products", "what loans",
        "do you offer", "who are you", "office timings", "location", "address",
    )
    return any(t.startswith(s) for s in switch_starters)


def is_likely_question_or_intent(text: str, tenant_id=None) -> bool:
    """Return True if user input is asking a question or invoking another topic."""
    if not text:
        return False
    t = text.strip().lower()
    if "?" in t:
        return True
    if any(t.startswith(w + " ") or t == w for w in _QUESTION_STARTERS):
        return True
    if t in CANCEL_WORDS:
        return True
    if _is_explicit_topic_switch(t, tenant_id=tenant_id):
        return True
    try:
        try:
            from services import intent_answers, service_answers
        except ImportError:
            from backend.services import intent_answers, service_answers
        if service_answers.is_service_query(t):
            return True
        if intent_answers.answer_for_text("", t, tenant_id=tenant_id):
            return True
        if intent_answers.answer_for_menu_title("", t, tenant_id=tenant_id):
            return True
    except Exception:
        pass
    return False


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
        from shared.tenancy.schemas import is_valid_phone_input
        wanted = int(rule.split(":", 1)[1]) if ":" in rule else 10
        return is_valid_phone_input(value, wanted=wanted)
    if rule.startswith("name"):
        if is_likely_question_or_intent(value):
            return False
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
        cols = {c[1] for c in conn.execute("PRAGMA table_info(leads)").fetchall()}
        user_name_col = "user_name" if "user_name" in cols else "name"
        name_val = str(data.get("name") or "")
        phone_val = str(data.get("phone") or "")
        email_val = str(data.get("email") or "")
        collected_val = json.dumps(data, ensure_ascii=False)
        source_val = lead_source or flow_name

        fields = ["tenant_id", "wa_id", user_name_col, "phone", "email", "status"]
        vals = [str(tenant_id), wa_id, name_val, phone_val, email_val, "new"]

        if "name" in cols and user_name_col != "name":
            fields.append("name")
            vals.append(name_val)
        if "collected" in cols:
            fields.append("collected")
            vals.append(collected_val)
        if "source" in cols:
            fields.append("source")
            vals.append(source_val)
        if "flow" in cols:
            fields.append("flow")
            vals.append(flow_name)
        if "service_required" in cols:
            fields.append("service_required")
            vals.append(str(data.get("need") or data.get("package") or ""))

        placeholders = ", ".join(["?"] * len(vals))
        col_names = ", ".join(fields)
        cur = conn.execute(
            f"INSERT INTO leads ({col_names}) VALUES ({placeholders})",
            vals,
        )
        lead_id = cur.lastrowid
    logger.info("LEAD_SAVED | tenant=%s | flow=%s | lead_id=%s", tenant_id, flow_name, lead_id)

    # Complaint wrap: keep the legacy complaints admin surface alive while
    # the runner owns the conversation (see module docstring).
    if (lead_source or "").lower() in ("complaint", "ticket", "support_ticket"):
        t_id = _insert_complaint_row(tenant_id, wa_id, data)
        if t_id:
            collected["ticket_id"] = t_id

    # Callback & Google Meeting auto-scheduling
    if flow_name in ("book_callback", "callback_request") or (lead_source or "").lower() in ("callback", "appointment"):
        try:
            from services.callback_service import callback_service
            cb = callback_service.create_and_schedule_callback(
                tenant_id=tenant_id,
                wa_id=wa_id,
                customer_name=str(data.get("name") or "Customer"),
                customer_phone=str(data.get("phone") or wa_id),
                customer_email=str(data.get("email") or ""),
                preferred_time=str(data.get("preferred_time") or ""),
                purpose=str(data.get("need") or data.get("purpose") or "Callback & Google Meeting"),
                callback_type="general",
            )
            if cb:
                collected["meet_link"] = cb.meet_link
                collected["scheduled_time"] = cb.preferred_time
                collected["calendar_add_url"] = cb.metadata.get("calendar_add_url", "")
                collected["callback_id"] = cb.id
                logger.info("CALLBACK_SCHEDULED_WITH_MEET | tenant=%s | cb_id=%s | meet=%s",
                            tenant_id, cb.id, cb.meet_link)
        except Exception as exc:
            logger.error("Failed to auto-schedule callback meeting: %s", exc)
    # Customer directory: fill in the profile fields the customer volunteered.
    try:
        update_customer_profile = _db().update_customer_profile
        update_customer_profile(
            tenant_id, wa_id,
            name=data.get("name"), phone=data.get("phone"), email=data.get("email"),
            city=data.get("city"), state=data.get("state"),
            company=data.get("company") or data.get("organisation") or data.get("organization"),
        )
    except Exception as e:
        logger.debug("customer profile enrichment failed: %s", e)
    return lead_id


def _insert_complaint_row(tenant_id: str, wa_id: str, data: dict) -> str:
    now = datetime.now().isoformat()
    ticket_id = data.get("ticket_id") or f"CMP-{uuid.uuid4().hex[:8].upper()}"
    raw_urgency = str(data.get("urgency") or "normal").strip().lower()
    priority = "urgent" if ("urgent" in raw_urgency or "high" in raw_urgency) else "normal"
    issue_desc = str(data.get("issue") or data.get("need") or "").strip()
    description = issue_desc
    if data.get("urgency"):
        description = f"Urgency: {data.get('urgency')}\nDetails: {issue_desc}" if issue_desc else f"Urgency: {data.get('urgency')}"
    subject = (issue_desc or data.get("need") or "WhatsApp complaint")[:120]

    # Map complaint type from issue text if possible
    ctype = "Other"
    issue_lower = issue_desc.lower()
    if any(k in issue_lower for k in ("damage", "broken", "cracked", "defect", "leak", "tear")):
        ctype = "Damaged Product"
    elif any(k in issue_lower for k in ("wrong", "incorrect", "different")):
        ctype = "Wrong Item"
    elif any(k in issue_lower for k in ("delivery", "late", "delay", "not delivered", "shipping")):
        ctype = "Delivery Issue"
    elif any(k in issue_lower for k in ("bill", "payment", "charge", "refund", "paid")):
        ctype = "Billing & Payment"
    elif any(k in issue_lower for k in ("quality", "taste", "smell", "stale", "expired")):
        ctype = "Product Quality"

    try:
        with _db().get_db_context() as conn:
            conn.execute(
                """INSERT INTO complaints (ticket_id, wa_id, complaint_type, description,
                   status, priority, subject, updated_at, created_at, tenant_id)
                   VALUES (?, ?, ?, ?, 'open', ?, ?, ?, ?, ?)""",
                (
                    ticket_id, wa_id, ctype, description or "Complaint submitted via WhatsApp",
                    priority, subject, now, now, tenant_id,
                ),
            )
        logger.info("COMPLAINT_WRAPPED | tenant=%s | ticket=%s | priority=%s", tenant_id, ticket_id, priority)
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


def _escalate(tenant_id: str, wa_id: str, flow_name: str) -> bool:
    """Float the conversation to the top of the admin live inbox.

    The inbox queue sorts by ``human_handover DESC``, so setting the flag
    both stops the bot from auto-replying and pins the conversation to the
    top of the queue for an agent to pick up.
    """
    try:
        set_human_handover = _db().set_human_handover
    except Exception as e:
        logger.error("HANDOFF_ESCALATE_FAILED | tenant=%s | flow=%s | wa_id=%s | %s",
                     tenant_id, flow_name, wa_id, e)
        return False
    try:
        set_human_handover(wa_id, True)
        logger.info("HANDOFF_ESCALATED | tenant=%s | flow=%s | wa_id=%s",
                    tenant_id, flow_name, wa_id)
        return True
    except Exception as e:
        logger.error("HANDOFF_ESCALATE_FAILED | tenant=%s | flow=%s | wa_id=%s | %s",
                     tenant_id, flow_name, wa_id, e)
        return False


# ── the runner ─────────────────────────────────────────────────────────────

def is_running(wa_id: str) -> bool:
    return bool(_state().active_flow(wa_id))


def clear_flow(wa_id: str, *, reset_status: bool = True) -> bool:
    """Clear any running flow for a user."""
    return _state().clear_flow(wa_id, reset_status=reset_status)



_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]")


def _clean_title(text: str) -> str:
    if not text:
        return ""
    cleaned = _EMOJI_RE.sub("", str(text)).replace("…", "").replace("...", "")
    words = [w for w in cleaned.strip().lower().split() if w not in ("a", "an", "the")]
    return " ".join(words)


def flow_for_button(wa_id: str, button_id: str, tenant_id=None):
    """The flow a profile menu button starts, or None.

    Matches by button ID, clean ID, or button title (since WhatsApp delivers
    tapped list menu options as the row title text). Only returns flows whose
    feature flag is on.
    """
    try:
        profile = _profile(tenant_id, wa_id)
    except Exception as e:
        logger.debug("flow_for_button: profile unavailable: %s", e)
        return None
    raw_id = (button_id or "").strip()
    clean_id = raw_id.replace("flow:", "").replace("flow_", "").strip()
    clean_target = _clean_title(raw_id)

    for b in profile.menu.buttons:
        b_clean = _clean_title(b.title)
        matched = (
            b.id == raw_id
            or b.id == clean_id
            or (b_clean and b_clean == clean_target)
            or (len(clean_target) >= 4 and clean_target in b_clean)
            or (len(b_clean) >= 4 and b_clean in clean_target)
            or (getattr(b, "flow", None) and _clean_title(b.flow) == clean_target)
        )
        if matched and getattr(b, "flow", None):
            flow = profile.flow(b.flow)
            if flow and (not flow.requires_feature or profile.feature_on(flow.requires_feature)):
                return flow.name
            logger.info("Button %s wants flow %s but its feature is off — "
                        "falling through to the default pipeline", raw_id, b.flow)

    # Direct flow lookup by flow name
    direct_flow = profile.flow(clean_id) or profile.flow(raw_id)
    if direct_flow and (not direct_flow.requires_feature or profile.feature_on(direct_flow.requires_feature)):
        return direct_flow.name

    return None


def flow_for_text(wa_id: str, text: str, tenant_id=None):
    """The flow a typed text message starts, or None.

    Matches:
    1. Direct callback & Google Meeting triggers (e.g. 'book a callback', 'schedule meeting', 'callback').
    2. Appointment triggers (e.g. 'book appointment', 'doctor appointment').
    3. Quote & Proposal triggers (e.g. 'get a quote', 'request proposal').
    4. Complaint & Ticket triggers.
    5. Active profile intents declaring a flow (e.g. callback_request -> book_callback, quote_request -> get_quote).
    """
    raw = (text or "").strip().lower()
    if not raw:
        return None

    try:
        profile = _profile(tenant_id, wa_id)
    except Exception as e:
        logger.debug("flow_for_text: profile unavailable: %s", e)
        return None

    clean = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", raw).strip()

    # Appointment triggers (Healthcare & generic)
    appointment_phrases = (
        "book an appointment", "book appointment", "appointment", "schedule appointment",
        "doctor appointment", "see a doctor", "consult doctor", "meet doctor",
        "make an appointment", "make appointment",
    )
    if any(p in clean or clean == p for p in appointment_phrases):
        flow = profile.flow("book_appointment")
        if flow and (not flow.requires_feature or profile.feature_on(flow.requires_feature)):
            return "book_appointment"

    # Callback & Meeting triggers
    callback_phrases = (
        "book a callback", "book callback", "request a callback", "request callback",
        "call me back", "call back", "callback", "schedule a call", "schedule call",
        "schedule a meeting", "schedule meeting", "book a meeting", "book meeting",
        "google meet", "google meeting", "arrange a call", "arrange call",
        "callback request", "meeting request", "book a google meet", "need a callback",
    )
    if any(p in clean or clean == p for p in callback_phrases):
        flow = profile.flow("book_callback")
        if flow and (not flow.requires_feature or profile.feature_on(flow.requires_feature)):
            return "book_callback"

    # Quote & Proposal triggers (IT, Finance, Travel, etc.)
    quote_phrases = (
        "get a quote", "get quote", "request a quote", "request quote",
        "need a quote", "project quote", "quote",
        "request proposal", "request a proposal", "proposal", "get proposal",
    )
    if any(p in clean or clean == p for p in quote_phrases):
        flow = profile.flow("get_quote")
        if flow and (not flow.requires_feature or profile.feature_on(flow.requires_feature)):
            return "get_quote"

    # Human Handover triggers
    human_phrases = (
        "talk to human", "speak to human", "talk to agent", "connect to agent",
        "human agent", "talk to a human", "speak to a person", "talk to person",
    )
    if any(p in clean or clean == p for p in human_phrases):
        flow = profile.flow("book_callback") or profile.flow("human_handover")
        if flow and (not flow.requires_feature or profile.feature_on(flow.requires_feature)):
            return flow.name

    # Ticket / Complaint triggers
    ticket_phrases = (
        "raise a ticket", "raise ticket", "raise complaint", "raise a complaint",
        "create ticket", "log complaint", "support ticket", "file a complaint",
        "file complaint", "register complaint", "register a complaint",
        "have a complaint", "i have a complaint", "complaint", "complaints",
        "complain", "want to complain", "grievance", "shikayat",
        "bad experience", "bad service", "unacceptable service", "unacceptable",
        "report an issue", "report issue", "issue with order", "order issue",
        "damaged product", "damaged item", "wrong item", "wrong product",
    )
    if any(p in clean or clean == p for p in ticket_phrases):
        flow = profile.flow("raise_ticket") or profile.flow("register_complaint")
        if flow and (not flow.requires_feature or profile.feature_on(flow.requires_feature)):
            return flow.name

    # Profile intent flows
    for intent in profile.active_intents():
        flow_target = getattr(intent, "flow", None)
        if not flow_target:
            continue
        fl = profile.flow(flow_target)
        if not fl or (fl.requires_feature and not profile.feature_on(fl.requires_feature)):
            continue
        if raw == intent.name.lower() or clean == intent.name.lower():
            return fl.name
        for kw in (intent.keywords or []):
            k = kw.lower().strip()
            if k and (raw == k or clean == k or raw.startswith(k + " ") or f" {k} " in f" {raw} "):
                return fl.name
        for ex in (intent.examples or []):
            e = ex.lower().strip()
            if e and (raw == e or clean == e or raw.startswith(e + " ") or f" {e} " in f" {raw} "):
                return fl.name

    return None


def start_flow(wa_id: str, flow_name: str, tenant_id=None, seed: dict = None) -> dict:
    """Begin a flow for a user. Respects out-of-hours variants.

    ``seed`` pre-fills collected values (e.g. the tour package the user
    tapped). Ask steps marked ``prefill`` are skipped when their key is
    already known.

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

    # start_flow wipes collected, so the seed is written afterwards.
    collected = {str(k): v for k, v in (seed or {}).items()
                 if v is not None and str(v).strip() != ""}
    if collected:
        sm.merge_collected(wa_id, collected)

    messages = []
    if flow.start_message and flow.steps and flow.steps[0].type != "say":
        messages.append(flow.start_message)

    return _run_from(wa_id, profile, flow, flow.first_step_id(), collected, messages)


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
            # For name/phone/email fields, don't check for question intent to avoid
            # breaking forms when user's name is "Hi" or similar
            validation_key = (step.validate_rule or "").lower()
            is_name_or_contact = any(
                rule in validation_key for rule in ["name", "phone", "email", "digits"]
            )
            if not is_name_or_contact and is_likely_question_or_intent(answer, tenant_id=profile.tenant_id) and (
                key not in ("need", "issue", "project", "details", "subject")
                or _is_explicit_topic_switch(answer, profile.tenant_id)
            ):
                logger.info("FLOW_BREAK | wa_id=%s | user asked question during ask step %s: %r", wa_id, step.id, answer[:50])
                sm.clear_flow(wa_id)
                return {"handled": False, "switched_topic": True}
            collected[key] = answer
            collected.pop("_attempts", None)
        else:
            # For name/phone/email fields, don't check for question intent
            validation_key = (step.validate_rule or "").lower()
            is_name_or_contact = any(
                rule in validation_key for rule in ["name", "phone", "email", "digits"]
            )
            if not is_name_or_contact and is_likely_question_or_intent(answer, tenant_id=profile.tenant_id):
                logger.info("FLOW_BREAK | wa_id=%s | user asked question instead of flow input: %r", wa_id, answer[:50])
                sm.clear_flow(wa_id)
                return {"handled": False, "switched_topic": True}
            return _retry(wa_id, flow, step, collected,
                          step.invalid_message or "That doesn't look right — please try again (or type *cancel* to exit).")
        next_id = step.on.get(str(collected[key]).lower()) if step.on else None
        sm.merge_collected(wa_id, {key: collected[key]})
        return _run_from(wa_id, profile, flow, next_id or step.next, collected, messages)

    if step.type == "choice":
        match = _match_choice(answer, step.options)
        if match is None:
            if is_likely_question_or_intent(answer, tenant_id=profile.tenant_id):
                logger.info("FLOW_BREAK | wa_id=%s | user asked question instead of choice: %r", wa_id, answer[:50])
                sm.clear_flow(wa_id)
                return {"handled": False, "switched_topic": True}
            return _retry(wa_id, flow, step, collected,
                          step.invalid_message or
                          f"Please pick one of: {', '.join(step.options)} (or type *cancel* to exit)")
        key = step.key or step.id
        collected[key] = match
        sm.merge_collected(wa_id, {key: match})
        next_id = (step.on.get(match.lower()) or step.on.get(match)) if step.on else None
        return _run_from(wa_id, profile, flow, next_id or step.next, collected, messages)

    if step.type == "confirm":
        verdict = _yes_no(answer, step)
        if verdict is None:
            if is_likely_question_or_intent(answer, tenant_id=profile.tenant_id):
                logger.info("FLOW_BREAK | wa_id=%s | user asked question instead of confirm: %r", wa_id, answer[:50])
                sm.clear_flow(wa_id)
                return {"handled": False, "switched_topic": True}
            return _retry(wa_id, flow, step, collected,
                          step.invalid_message or
                          f"Please reply *{step.yes_label}* or *{step.no_label}* (or type *cancel* to exit).")
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


_CHOICE_FILLER = frozenset((
    "a", "an", "the", "for", "of", "to", "my", "me", "i", "want", "need",
    "would", "like", "please", "open", "opening", "new", "get", "have", "do",
    "is", "are", "am", "can", "you",
))


def _choice_tokens(text: str) -> set:
    """Comparable token set for a free-text answer or an option label.

    Lowercases, drops filler words, ignores single letters, and folds a trailing
    plural ``s`` (savings -> saving) so everyday phrasings such as
    "Saving account opening" still line up with the option "Savings Account".
    """
    out = set()
    for w in re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split():
        if len(w) < 2 or w in _CHOICE_FILLER:
            continue
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.add(w)
    return out


def _choice_button_id(option, index: int) -> str:
    """Stable, WhatsApp-safe id for a choice option row/button."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(option or "").lower()).strip("_")
    return f"flowopt_{index}_{slug or 'opt'}"[:256]


def message_to_text(msg) -> str:
    """Flatten a flow outcome message (str or interactive dict) to plain text."""
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        return msg.get("text") or ""
    return ""


def messages_text(messages) -> str:
    """Flatten a flow outcome message list to a single newline-joined string."""
    return "\n".join(message_to_text(m) for m in (messages or []))


def _match_choice(answer: str, options: list):
    a = (answer or "").strip().lower()
    if not a:
        return None
    a_tokens = _choice_tokens(a)
    for opt in options:
        o = (opt or "").strip().lower()
        if a == o or (len(a) >= 3 and a in o) or (len(o) >= 3 and o in a):
            return opt
        o_tokens = _choice_tokens(o)
        if a_tokens and o_tokens and (o_tokens <= a_tokens or a_tokens <= o_tokens):
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
            if step.type == "ask" and step.prefill:
                key = step.key or step.id
                if str(collected.get(key) or "").strip():
                    logger.info("FLOW_PREFILL_SKIP | wa_id=%s | flow=%s | step=%s | key=%s",
                                wa_id, flow.name, step.id, key)
                    step_id = _next_after(step)
                    continue
            prompt = step.prompt or step.message
            if step.type == "choice" and prompt and step.options:
                # Emit a tappable options message (the sender renders buttons as a
                # WhatsApp list menu) so the customer picks instead of typing.
                buttons = [
                    {"id": _choice_button_id(opt, i), "title": str(opt)[:24]}
                    for i, opt in enumerate(step.options)
                ]
                messages.append({"type": "buttons", "text": prompt, "buttons": buttons})
            elif prompt:
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

        elif step.type == "handoff":
            handoff_id = _handoff(profile.tenant_id, wa_id, flow.name, step, collected)
            paused = True
            if step.escalate:
                _escalate(profile.tenant_id, wa_id, flow.name)
            if step.prompt and step.prompt not in messages:
                messages.append(step.prompt)

        else:
            logger.error("FLOW_SKIP | unknown step type %r in flow %s", step.type, flow.name)

        step_id = _next_after(step)

    # Flow finished.
    sm.clear_flow(wa_id, reset_status=True)

    if (flow.name in ("book_callback", "callback_request") or collected.get("meet_link")) and collected.get("meet_link"):
        meet_link = collected.get("meet_link")
        sched_time = collected.get("scheduled_time") or collected.get("preferred_time") or "Shortly"
        cust_name = collected.get("name") or "there"
        topic = collected.get("need") or "Callback Discussion"
        cal_url = collected.get("calendar_add_url")

        meet_lines = [
            "📅 *Callback & Google Meeting Confirmed!*",
            f"👤 *Name:* {cust_name}",
            f"⏰ *Scheduled Time:* {sched_time}",
            f"🎯 *Topic:* {topic}",
            f"\n🔗 *Google Meet Link:*\n{meet_link}",
        ]
        if cal_url:
            meet_lines.append(f"\n📅 *Add to Google Calendar:*\n{cal_url}")
        meet_lines.append("\nOur team has scheduled this session. Please click the Google Meet link above at the scheduled time to join!")
        meet_confirmation = "\n".join(meet_lines)

        # Replace any generic "Done!" or "say" message or append
        if messages and any(kw in message_to_text(messages[-1]).lower() for kw in ("done", "callback", "office", "soon", "team")):
            messages[-1] = meet_confirmation
        else:
            messages.append(meet_confirmation)
    elif flow.name in ("book_callback", "callback_request"):
        sched_time = collected.get("scheduled_time") or collected.get("preferred_time") or "Shortly"
        cust_name = collected.get("name") or "there"
        topic = collected.get("need") or "Callback Discussion"
        cal_url = collected.get("calendar_add_url")

        cb_lines = [
            "📅 *Callback Request Confirmed!*",
            f"👤 *Name:* {cust_name}",
            f"⏰ *Preferred Time:* {sched_time}",
            f"🎯 *Topic:* {topic}",
            "\nOur team has received your request and will contact you at your preferred time to share the Google Meeting details.",
        ]
        if cal_url:
            cb_lines.append(f"\n📅 *Add to Calendar:*\n{cal_url}")
        cb_confirmation = "\n".join(cb_lines)
        if messages and any(kw in message_to_text(messages[-1]).lower() for kw in ("done", "callback", "office", "soon", "team")):
            messages[-1] = cb_confirmation
        else:
            messages.append(cb_confirmation)
    elif flow.name in ("raise_ticket", "register_complaint") or collected.get("ticket_id") or "issue" in collected:
        ticket_id = collected.get("ticket_id") or f"CMP-{uuid.uuid4().hex[:8].upper()}"
        cust_name = collected.get("name") or "there"
        phone = collected.get("phone") or wa_id
        issue = collected.get("issue") or collected.get("need") or "Complaint details logged"
        raw_urgency = str(collected.get("urgency") or "Normal").strip().title()

        cmp_lines = [
            "📝 *Complaint Registered Successfully!*",
            f"🎫 *Ticket ID:* `{ticket_id}`",
            f"👤 *Name:* {cust_name}",
            f"📞 *Contact:* {phone}",
            f"⚡ *Priority:* {raw_urgency}",
            f"📄 *Issue:* {issue}",
            "\nOur support team has logged your complaint and will review and address it shortly. Please keep this Ticket ID for your reference. 🙏",
        ]
        cmp_confirmation = "\n".join(cmp_lines)
        if messages and any(kw in message_to_text(messages[-1]).lower() for kw in ("ticket", "shortly", "done", "team", "complaint")):
            messages[-1] = cmp_confirmation
        else:
            messages.append(cmp_confirmation)
    elif flow.success_message and not emitted_done and flow.success_message not in messages:
        messages.append(flow.success_message)
    return _outcome(flow.name, messages, finished=True, lead_id=lead_id,
                    handoff_id=handoff_id,
                    status=_STATUS_PAUSED if paused else _STATUS_BOT)
