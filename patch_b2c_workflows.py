import re
with open("bots/customer_b2c/workflows.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add new states in handle_b2c_message
target1 = """    # -- Complaint: awaiting type """
replacement1 = """    # -- Callback --------------------------------------------------------
    if state == cfg.B2C_AWAITING_CALLBACK_TYPE:
        sel = _clean(message)
        if sel in ("virtual", "b2c_callback_virtual"):
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
                await send_text_message(wa_id, f"Here is your Google Meet link: {meet_result['meet_link']}")
            else:
                await send_text_message(wa_id, "Sorry, I couldn't create a Google Meet link right now. A human agent will contact you shortly.")
            
            return {"new_state": cfg.B2C_MAIN_MENU_STATE}
        elif sel in ("personal", "b2c_callback_personal"):
            await send_text_message(wa_id, "Please provide the details for your personal meeting (preferred date, time, and topic).")
            return {"new_state": cfg.B2C_AWAITING_CALLBACK_DETAILS}
        else:
            buttons = [
                {"id": "b2c_callback_virtual", "title": "Virtual"},
                {"id": "b2c_callback_personal", "title": "Personal"},
            ]
            await send_button_message(wa_id, "Please select an option:\n\nHow would you like to meet?", buttons)
            return {"new_state": cfg.B2C_AWAITING_CALLBACK_TYPE}

    if state == cfg.B2C_AWAITING_CALLBACK_DETAILS:
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
                        "customer_name": "Customer",
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
        
        await send_text_message(wa_id, "Thank you. Your request for a personal meeting has been received. Our team will contact you shortly to confirm.")
        return {"new_state": cfg.B2C_MAIN_MENU_STATE}

    # -- Complaint: awaiting type """

content = content.replace(target1, replacement1)

# 2. Add trigger in _handle_main_selection
target2 = """    # Anything else while in the main menu: answer via the RAG pipeline."""
replacement2 = """    if sel in ("book a callback", "menu_callback", "callback", "request a callback", "book appointment"):
        buttons = [
            {"id": "b2c_callback_virtual", "title": "Virtual"},
            {"id": "b2c_callback_personal", "title": "Personal"},
        ]
        await send_button_message(wa_id, "How would you like to meet?", buttons)
        return {"new_state": cfg.B2C_AWAITING_CALLBACK_TYPE}

    # Anything else while in the main menu: answer via the RAG pipeline."""

content = content.replace(target2, replacement2)

with open("bots/customer_b2c/workflows.py", "w", encoding="utf-8") as f:
    f.write(content)
