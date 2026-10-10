import re

# 1. Update config
with open("bots/distributor_b2b/config.py", "r", encoding="utf-8") as f:
    config_content = f.read()

config_target = """B2B_AWAITING_INVOICE_ORDER_ID = "B2B_AWAITING_INVOICE_ORDER_ID\""""
config_repl = """B2B_AWAITING_INVOICE_ORDER_ID = "B2B_AWAITING_INVOICE_ORDER_ID"
B2B_AWAITING_CALLBACK_TYPE = "B2B_AWAITING_CALLBACK_TYPE"
B2B_AWAITING_CALLBACK_DETAILS = "B2B_AWAITING_CALLBACK_DETAILS" """

config_content = config_content.replace(config_target, config_repl)
with open("bots/distributor_b2b/config.py", "w", encoding="utf-8") as f:
    f.write(config_content)

# 2. Update workflows
with open("bots/distributor_b2b/workflows.py", "r", encoding="utf-8") as f:
    wf_content = f.read()

wf_target1 = """    if state == cfg.B2B_AWAITING_ORDER_ID:"""
wf_repl1 = """    if state == cfg.B2B_AWAITING_CALLBACK_TYPE:
        sel = _clean(message)
        if sel in ("virtual", "b2b_callback_virtual"):
            from database import get_db_context
            tenant_id = None
            with get_db_context() as conn:
                row = conn.execute("SELECT tenant_id FROM customers WHERE wa_id = ?", (wa_id,)).fetchone()
                if row:
                    tenant_id = row[0]
                else:
                    row = conn.execute("SELECT tenant_id FROM distributors WHERE wa_id = ?", (wa_id,)).fetchone()
                    if row:
                        tenant_id = row[0]
            if not tenant_id:
                tenant_id = "default"
                
            from services.google_meet_service import create_meeting
            from datetime import datetime, timedelta, timezone
            now = datetime.now(timezone.utc)
            start_time = now.isoformat()
            end_time = (now + timedelta(hours=1)).isoformat()
            
            meet_result = await create_meeting(
                tenant_id=tenant_id,
                title="Virtual Meeting",
                start_time=start_time,
                end_time=end_time
            )
            if meet_result.get("ok"):
                from services.whatsapp_sender import send_text_message
                await send_text_message(wa_id, f"Here is your Google Meet link: {meet_result['meet_link']}")
            else:
                from services.whatsapp_sender import send_text_message
                await send_text_message(wa_id, "Sorry, I couldn't create a Google Meet link right now. A human agent will contact you shortly.")
            return {"new_state": cfg.B2B_MAIN_MENU_STATE}
        elif sel in ("personal", "b2b_callback_personal"):
            from services.whatsapp_sender import send_text_message
            await send_text_message(wa_id, "Please provide the details for your personal meeting (preferred date, time, and topic).")
            return {"new_state": cfg.B2B_AWAITING_CALLBACK_DETAILS}
        else:
            from services.whatsapp_sender import send_button_message
            buttons = [
                {"id": "b2b_callback_virtual", "title": "Virtual"},
                {"id": "b2b_callback_personal", "title": "Personal"},
            ]
            await send_button_message(wa_id, "Please select an option:\n\nHow would you like to meet?", buttons)
            return {"new_state": cfg.B2B_AWAITING_CALLBACK_TYPE}

    if state == cfg.B2B_AWAITING_CALLBACK_DETAILS:
        details = message
        from database import get_db_context
        import json
        import secrets
        tenant_id = None
        with get_db_context() as conn:
            row = conn.execute("SELECT tenant_id FROM customers WHERE wa_id = ?", (wa_id,)).fetchone()
            if row:
                tenant_id = row[0]
            else:
                row = conn.execute("SELECT tenant_id FROM distributors WHERE wa_id = ?", (wa_id,)).fetchone()
                if row:
                    tenant_id = row[0]
            if tenant_id:
                try:
                    cb_id = secrets.token_hex(8)
                    cb_data = json.dumps({
                        "customer_name": "Distributor",
                        "wa_id": wa_id,
                        "purpose": f"Personal meeting details: {details}",
                        "callback_type": "personal"
                    })
                    conn.execute(
                        "INSERT INTO callbacks (id, tenant_id, wa_id, data, status) VALUES (?, ?, ?, ?, ?)",
                        (cb_id, tenant_id, wa_id, cb_data, "pending")
                    )
                except Exception as e:
                    pass
        from services.whatsapp_sender import send_text_message
        await send_text_message(wa_id, "Thank you. Your request for a personal meeting has been received. Our team will contact you shortly to confirm.")
        return {"new_state": cfg.B2B_MAIN_MENU_STATE}

    if state == cfg.B2B_AWAITING_ORDER_ID:"""

wf_content = wf_content.replace(wf_target1, wf_repl1)

wf_target2 = """    if sel in ("place order", "b2b_order"):"""
wf_repl2 = """    if sel in ("book a callback", "menu_callback", "callback", "request a callback", "book appointment"):
        from services.whatsapp_sender import send_button_message
        buttons = [
            {"id": "b2b_callback_virtual", "title": "Virtual"},
            {"id": "b2b_callback_personal", "title": "Personal"},
        ]
        await send_button_message(wa_id, "How would you like to meet?", buttons)
        return {"new_state": cfg.B2B_AWAITING_CALLBACK_TYPE}

    if sel in ("place order", "b2b_order"):"""

wf_content = wf_content.replace(wf_target2, wf_repl2)

with open("bots/distributor_b2b/workflows.py", "w", encoding="utf-8") as f:
    f.write(wf_content)

