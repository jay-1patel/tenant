"""
End-to-End QA Test Suite for all Chatbot Tenants & Products.
Tests Menu, Buttons, Flows, FAQ/RAG, Validations, and Text Quality.
"""
import sys
import os
import asyncio
import json
import re
import sqlite3
from typing import List, Dict, Any

# Ensure backend and root are on sys.path
sys.path.insert(0, os.path.abspath('backend'))
sys.path.insert(0, os.path.abspath('.'))

import database as db
from shared.tenancy.loader import get_tenant_profile
from services.orchestrator import process_incoming_message
from services import flow_runner, intent_answers, state_manager

# Common typos dictionary to audit text
COMMON_TYPOS = [
    "eligibiluty", "eligiblity", "compalint", "complaintes", "repoding",
    "excpects", "recieved", "seperate", "untill", "definately", "accomodate",
    "occured", "truely", "refered", "succesful", "goverment", "enviroment",
    "calender", "whatapp", "whatsApp", "whats app", "teh", "recieve", "adn"
]

class QATestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.failures: List[str] = []
        self.warning_msgs: List[str] = []

    def assert_true(self, condition: bool, msg: str):
        if condition:
            self.passed += 1
        else:
            self.failed += 1
            self.failures.append(msg)
            print(f"  ❌ FAIL: {msg}")

    def warn(self, msg: str):
        self.warnings += 1
        self.warning_msgs.append(msg)
        print(f"  ⚠️ WARN: {msg}")

    def ok(self, msg: str):
        self.passed += 1
        print(f"  ✅ PASS: {msg}")


async def run_suite_1_menu_and_buttons(tenants: List[str]) -> QATestResult:
    """Suite 1: Inspect and trigger all menu buttons across all tenants."""
    res = QATestResult("Suite 1: Menu & Buttons Audit")
    print("\n" + "="*70)
    print("▶ RUNNING SUITE 1: MENU & BUTTONS AUDIT")
    print("="*70)

    for tid in tenants:
        db.set_active_test_tenant(tid)
        profile = get_tenant_profile(tid)
        res.assert_true(profile is not None, f"[{tid}] Profile loaded successfully")
        if not profile:
            continue

        # 1. Fetch menu
        test_wa = f"qa_menu_{tid}"
        state_manager.clear_flow(test_wa)
        menu_res = await process_incoming_message(test_wa, "menu", capture_only=True)
        msgs = menu_res.get("messages", [])
        res.assert_true(len(msgs) > 0, f"[{tid}] 'menu' returns response")

        # 2. Check each button
        buttons = profile.menu.buttons
        res.assert_true(len(buttons) > 0, f"[{tid}] Has at least 1 menu button (found {len(buttons)})")

        seen_ids = set()
        for btn in buttons:
            # Check unique ID
            res.assert_true(btn.id not in seen_ids, f"[{tid}] Button ID '{btn.id}' is unique")
            seen_ids.add(btn.id)

            # Check title
            res.assert_true(bool(btn.title and btn.title.strip()), f"[{tid}] Button '{btn.id}' has non-empty title")

            # Check action target
            has_flow = bool(btn.flow)
            has_intent = bool(btn.intent)
            if not has_flow and not has_intent:
                # Some FMCG/legacy buttons are handled in fallback
                res.warn(f"[{tid}] Button '{btn.id}' ({btn.title}) has neither flow nor intent in profile (handled via persona/legacy fallback)")

            # Click/trigger button
            state_manager.clear_flow(test_wa)
            btn_res = await process_incoming_message(test_wa, btn.id, capture_only=True)
            btn_msgs = btn_res.get("messages", [])
            has_reply = len(btn_msgs) > 0
            res.assert_true(has_reply, f"[{tid}] Clicking button '{btn.id}' produced a response")

            if has_reply:
                first_text = str(btn_msgs[0])
                res.assert_true("Internal Server Error" not in first_text and "Traceback" not in first_text,
                                f"[{tid}] Button '{btn.id}' response has no unhandled error")

    return res


async def run_suite_2_validation(tenants: List[str]) -> QATestResult:
    """Suite 2: Strict Phone Number, Email, and Name Validations in Flow Forms."""
    res = QATestResult("Suite 2: Form Validations & Constraints")
    print("\n" + "="*70)
    print("▶ RUNNING SUITE 2: STRICT FORM VALIDATIONS")
    print("="*70)

    from shared.tenancy.schemas import is_valid_phone_input, is_valid_email
    from services.flow_runner import validate_answer

    # 1. Phone number test vectors
    phone_vectors = [
        # (input_val, expected_valid, reason)
        ("9876543210", True, "Standard 10-digit mobile"),
        ("+91 9876543210", True, "+91 format with space"),
        ("+919876543210", True, "+91 format no space"),
        ("09876543210", True, "Trunk 0 + 10 digits"),
        ("919876543210", True, "91 prefix + 10 digits"),
        ("+1 2125551234", True, "US 10-digit number with +1"),
        # Rejections:
        ("98765432101", False, "11 digits without country code"),
        ("987654321012", False, "12 digits without country code"),
        ("987654321012345", False, "15 digits"),
        ("+9198765432101", False, "+91 followed by 11 digits"),
        ("+91987654321012", False, "+91 followed by 12 digits"),
        ("98765", False, "Only 5 digits (too short)"),
        ("abcdefghij", False, "Letters instead of digits"),
        ("", False, "Empty phone string"),
        ("98765-43210-99", False, "Dashed 12 digits"),
    ]

    for val, expected, reason in phone_vectors:
        actual = is_valid_phone_input(val, wanted=10)
        res.assert_true(actual == expected, f"Phone check '{val}' ({reason}) -> got {actual}, expected {expected}")

        # Also verify validate_answer("phone:10", val)
        val_rule = validate_answer("phone:10", val)
        res.assert_true(val_rule == expected, f"validate_answer('phone:10', '{val}') -> got {val_rule}, expected {expected}")

    # 2. Email test vectors
    email_vectors = [
        ("user@example.com", True, "Standard email"),
        ("support@meridianbank.com", True, "Corporate email"),
        ("invalid-email", False, "No @ or domain"),
        ("user@", False, "Missing domain"),
        ("@domain.com", False, "Missing user"),
        ("", False, "Empty email"),
    ]
    for val, expected, reason in email_vectors:
        actual = is_valid_email(val)
        res.assert_true(actual == expected, f"Email check '{val}' ({reason}) -> got {actual}, expected {expected}")

    return res


async def run_suite_3_complaint_flow(tenants: List[str]) -> QATestResult:
    """Suite 3: End-to-end complaint registration for each tenant."""
    res = QATestResult("Suite 3: Complaint Flow E2E")
    print("\n" + "="*70)
    print("▶ RUNNING SUITE 3: COMPLAINT FLOW END-TO-END")
    print("="*70)

    for tid in tenants:
        db.set_active_test_tenant(tid)
        test_wa = f"qa_complaint_{tid}"
        state_manager.clear_flow(test_wa)

        # Trigger complaint
        r1 = await process_incoming_message(test_wa, "I want to raise a complaint", capture_only=True)
        msgs1 = r1.get("messages", [])
        res.assert_true(len(msgs1) > 0, f"[{tid}] Complaint trigger initiated response")
        if not msgs1:
            continue

        r1_text = " ".join(str(m.get("text") or m.get("body") or "") for m in msgs1).lower()
        res.assert_true("name" in r1_text or "help" in r1_text or "issue" in r1_text or "complaint" in r1_text,
                        f"[{tid}] Complaint flow started asking for details")

        # Step 1: Provide Name
        r2 = await process_incoming_message(test_wa, "QA Tester", capture_only=True)
        msgs2 = r2.get("messages", [])
        r2_text = " ".join(str(m.get("text") or m.get("body") or "") for m in msgs2).lower()
        res.assert_true("phone" in r2_text or "number" in r2_text or "contact" in r2_text,
                        f"[{tid}] Flow advances to asking for phone number")

        # Step 2: Test Invalid Phone (>10 digits) - MUST REJECT
        r3_invalid = await process_incoming_message(test_wa, "9876543210999", capture_only=True)
        msgs3_inv = r3_invalid.get("messages", [])
        r3_inv_text = " ".join(str(m.get("text") or m.get("body") or "") for m in msgs3_inv).lower()
        res.assert_true("10" in r3_inv_text or "invalid" in r3_inv_text or "valid" in r3_inv_text,
                        f"[{tid}] Phone rejection triggered for >10 digits")

        # Step 3: Provide Valid Phone (10 digits) - MUST ACCEPT
        r3_valid = await process_incoming_message(test_wa, "9876543210", capture_only=True)
        msgs3_val = r3_valid.get("messages", [])
        r3_val_text = " ".join(str(m.get("text") or m.get("body") or "") for m in msgs3_val).lower()
        res.assert_true("email" in r3_val_text or "detail" in r3_val_text or "issue" in r3_val_text or "describe" in r3_val_text or "need" in r3_val_text,
                        f"[{tid}] Phone accepted and advanced to next question")

        # Step 4: Complete remaining steps until finished
        max_steps = 5
        finished = False
        step_inputs = ["qa.test@example.com", "Delayed service and incorrect billing transaction", "urgent"]
        for inp in step_inputs:
            r_next = await process_incoming_message(test_wa, inp, capture_only=True)
            r_next_msgs = r_next.get("messages", [])
            r_next_text = " ".join(str(m.get("text") or m.get("body") or "") for m in r_next_msgs).lower()
            if "ticket" in r_next_text or "thank" in r_next_text or "registered" in r_next_text or "logged" in r_next_text or "recorded" in r_next_text:
                finished = True
                res.ok(f"[{tid}] Complaint successfully logged with confirmation!")
                break

        res.assert_true(finished or not flow_runner.is_running(test_wa), f"[{tid}] Complaint flow concluded properly")

        # Verify DB record
        with db.get_db_context() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM leads WHERE wa_id = ? ORDER BY id DESC LIMIT 1", (test_wa,))
            lead_row = cur.fetchone()
            cur.execute("SELECT id FROM complaints WHERE wa_id = ? ORDER BY id DESC LIMIT 1", (test_wa,))
            comp_row = cur.fetchone()
            res.assert_true(lead_row is not None or comp_row is not None, f"[{tid}] DB persisted complaint/lead record")

    return res


async def run_suite_4_callback_flow(tenants: List[str]) -> QATestResult:
    """Suite 4: End-to-end callback booking and scheduling for each tenant."""
    res = QATestResult("Suite 4: Callback Flow E2E")
    print("\n" + "="*70)
    print("▶ RUNNING SUITE 4: CALLBACK FLOW END-TO-END")
    print("="*70)

    for tid in tenants:
        db.set_active_test_tenant(tid)
        test_wa = f"qa_cb_{tid}"
        state_manager.clear_flow(test_wa)

        # Trigger callback
        r1 = await process_incoming_message(test_wa, "book a callback", capture_only=True)
        msgs1 = r1.get("messages", [])
        res.assert_true(len(msgs1) > 0, f"[{tid}] Callback trigger returned response")
        if not msgs1:
            continue

        # Provide Name
        r2 = await process_incoming_message(test_wa, "Callback Customer", capture_only=True)
        msgs2 = r2.get("messages", [])
        res.assert_true(len(msgs2) > 0, f"[{tid}] Callback step 1 accepted name")

        # Test Phone Validation: Enter 13 digits - MUST REJECT
        r3_bad = await process_incoming_message(test_wa, "9876543210123", capture_only=True)
        msgs3_bad = r3_bad.get("messages", [])
        bad_text = " ".join(str(m.get("text") or m.get("body") or "") for m in msgs3_bad).lower()
        res.assert_true("10" in bad_text or "invalid" in bad_text or "valid" in bad_text,
                        f"[{tid}] Callback rejected 13-digit phone")

        # Enter Valid 10-digit phone - MUST ACCEPT
        r3_good = await process_incoming_message(test_wa, "9876543210", capture_only=True)
        msgs3_good = r3_good.get("messages", [])
        res.assert_true(len(msgs3_good) > 0, f"[{tid}] Callback accepted 10-digit phone")

        # Complete purpose/time
        r4 = await process_incoming_message(test_wa, "Discuss loan and business account options tomorrow afternoon", capture_only=True)
        msgs4 = r4.get("messages", [])
        r4_text = " ".join(str(m.get("text") or m.get("body") or "") for m in msgs4).lower()
        res.assert_true("callback" in r4_text or "scheduled" in r4_text or "thank" in r4_text or "touch" in r4_text or "agent" in r4_text or len(msgs4) > 0,
                        f"[{tid}] Callback confirmed to user")

    return res


async def run_suite_5_faq_and_knowledge(tenants: List[str]) -> QATestResult:
    """Suite 5: FAQ & RAG Knowledge Base Retrieval Accuracy."""
    res = QATestResult("Suite 5: FAQ & Knowledge Retrieval")
    print("\n" + "="*70)
    print("▶ RUNNING SUITE 5: FAQ & KNOWLEDGE RETRIEVAL")
    print("="*70)

    # Tenant specific queries
    queries = {
        "meridianbank": [
            ("What is the home loan interest rate?", ["8.50%", "loan", "home"]),
            ("What documents are needed for personal loan?", ["kyc", "pan", "salary", "document", "statement"]),
            ("Can I prepay my loan without charges?", ["prepay", "floating", "charge", "yes"]),
        ],
        "leeway-softech": [
            ("What services do you offer?", ["software", "development", "web", "mobile", "services"]),
            ("Do you build mobile apps?", ["mobile", "app", "ios", "android", "development"]),
        ],
        "troogood": [
            ("What products do you offer?", ["millet", "chikki", "snack", "bar", "product"]),
        ],
        "ltfinance": [
            ("What loans do you offer?", ["loan", "finance", "two-wheeler", "farm", "housing"]),
        ],
        "99destinations": [
            ("What tour packages do you have?", ["tour", "package", "destination", "holiday", "travel"]),
        ],
        "wanderly": [
            ("What travel destinations do you cover?", ["tour", "package", "destination", "trip", "travel"]),
        ],
        "northwindcapital": [
            ("What wealth management services do you offer?", ["wealth", "investment", "portfolio", "capital", "fund"]),
        ]
    }

    for tid, q_list in queries.items():
        if tid not in tenants:
            continue
        db.set_active_test_tenant(tid)
        test_wa = f"qa_faq_{tid}"
        for q_text, expected_terms in q_list:
            state_manager.clear_flow(test_wa)
            reply_res = await process_incoming_message(test_wa, q_text, capture_only=True)
            msgs = reply_res.get("messages", [])
            res.assert_true(len(msgs) > 0, f"[{tid}] FAQ query '{q_text}' returned response")
            if msgs:
                full_reply = " ".join(str(m.get("text") or m.get("body") or "") for m in msgs).lower()
                matches = [t for t in expected_terms if t in full_reply]
                res.assert_true(len(matches) > 0,
                                f"[{tid}] FAQ query '{q_text}' response contains expected keywords {expected_terms} (found {matches})")

    return res


def run_suite_6_spelling_and_grammar_lint(tenants: List[str]) -> QATestResult:
    """Suite 6: Scan all configuration files and knowledge markdown for typos and broken markup."""
    res = QATestResult("Suite 6: Spelling, Grammar & Markdown Quality")
    print("\n" + "="*70)
    print("▶ RUNNING SUITE 6: SPELLING & MARKDOWN LINTING")
    print("="*70)

    for tid in tenants:
        # Check clients/<tid>/config.json
        cfg_path = os.path.join("clients", tid, "config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 1. Check for known typos
            for typo in COMMON_TYPOS:
                pattern = re.compile(rf"\b{re.escape(typo)}\b", re.IGNORECASE)
                found = pattern.findall(content)
                if found:
                    res.warn(f"[{tid}] Found potential typo '{typo}' in clients/{tid}/config.json ({len(found)} instances)")

            # 2. Check for unclosed formatting marks in strings
            # Look for odd counts of asterisks in single lines
            lines = content.splitlines()
            for line_idx, line in enumerate(lines, 1):
                if '"' in line and '*' in line:
                    asterisks = line.count('*')
                    # Odd number of asterisks may indicate unclosed bold/italic
                    if asterisks % 2 != 0:
                        res.warn(f"[{tid}] Odd number of asterisks in clients/{tid}/config.json:L{line_idx}")

        # Check knowledge files
        kb_dir = os.path.join("clients", tid, "knowledge")
        if os.path.exists(kb_dir):
            for fname in os.listdir(kb_dir):
                if fname.endswith((".md", ".txt")):
                    fpath = os.path.join(kb_dir, fname)
                    with open(fpath, "r", encoding="utf-8") as f:
                        kb_content = f.read()
                    for typo in COMMON_TYPOS:
                        pattern = re.compile(rf"\b{re.escape(typo)}\b", re.IGNORECASE)
                        found = pattern.findall(kb_content)
                        if found:
                            res.warn(f"[{tid}] Found potential typo '{typo}' in {fname} ({len(found)} instances)")

    return res


async def main():
    sys.stdout.reconfigure(encoding='utf-8')
    print("======================================================================")
    print("         COMPREHENSIVE END-TO-END QA TEST SUITE — ALL TENANTS         ")
    print("======================================================================")

    # Fetch active tenants
    with db.get_db_context() as conn:
        cur = conn.cursor()
        cur.execute("SELECT slug FROM tenants WHERE is_active = 1")
        tenants = [r[0] for r in cur.fetchall()]

    print(f"Targeting {len(tenants)} active tenants: {tenants}\n")

    # Run all test suites
    s1 = await run_suite_1_menu_and_buttons(tenants)
    s2 = await run_suite_2_validation(tenants)
    s3 = await run_suite_3_complaint_flow(tenants)
    s4 = await run_suite_4_callback_flow(tenants)
    s5 = await run_suite_5_faq_and_knowledge(tenants)
    s6 = run_suite_6_spelling_and_grammar_lint(tenants)

    # Reset active tenant back to leeway-softech
    db.set_active_test_tenant("leeway-softech")

    # Generate Summary Matrix
    all_suites = [s1, s2, s3, s4, s5, s6]
    total_passed = sum(s.passed for s in all_suites)
    total_failed = sum(s.failed for s in all_suites)
    total_warns = sum(s.warnings for s in all_suites)

    print("\n" + "="*70)
    print("📊 FINAL QA TEST EXECUTION REPORT")
    print("="*70)
    for s in all_suites:
        status_sym = "✅ PASS" if s.failed == 0 else "❌ FAIL"
        print(f"{status_sym} | {s.name:<40} | Passed: {s.passed:<4} | Failed: {s.failed:<3} | Warnings: {s.warnings:<3}")

    print("-" * 70)
    print(f"OVERALL SUMMARY: Total Passed: {total_passed} | Total Failed: {total_failed} | Warnings: {total_warns}")
    print("="*70)

    if total_failed > 0:
        print("\n🚨 DETAILED FAILURE BREAKDOWN:")
        for s in all_suites:
            if s.failures:
                print(f"\n--- {s.name} ---")
                for f in s.failures:
                    print(f"  ❌ {f}")

    if total_warns > 0:
        print("\n🔍 ADVISORY NOTICES / LINT WARNINGS:")
        for s in all_suites:
            if s.warning_msgs:
                print(f"\n--- {s.name} ---")
                for w in s.warning_msgs:
                    print(f"  ⚠️ {w}")

if __name__ == "__main__":
    asyncio.run(main())
