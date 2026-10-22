"""Tour package browsing: catalogue -> package card -> booking -> lead + handoff.

The design of ``backend/services/package_flow.py`` is driven by three quirks
that are easy to break, so they are pinned here:

* send2.digital hands a tapped list row back as its TITLE, not its id — and
  WhatsApp truncates that title to 24 characters, so the truncated string is
  what comes back on the tap.
* the booking flow must not ask for the package again when the user already
  tapped one (the ``prefill`` flag on the ask step).
* "package prices" is on the tours ``never_state`` list, so no card may quote
  a number - it points at the team instead.
"""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import database
from shared.tenancy import cache as tenancy_cache
from shared.tenancy import lint as tenancy_lint
from shared.tenancy import store as tenancy_store
from shared.tenancy.loader import build_profile

from backend.services import package_flow

# The service imports these by their short names at call time, so the test has
# to reach for the very same module objects.
try:
    from services import flow_runner
    from services import state_manager
    from services import whatsapp_sender
except ImportError:  # pragma: no cover - depends on sys.path order
    from backend.services import flow_runner
    from backend.services import state_manager
    from backend.services import whatsapp_sender


TENANT = "tours-test"
OTHER_TENANT = "other-test"
EMPTY_TENANT = "empty-test"
WA = "919999999999"

LONG_NAME = "Kerala Backwaters & Beaches Escape"
SHORT_NAME = "Best of Gujarat"

PACKAGES = [
    {
        "name": SHORT_NAME,
        "slug": "best-of-gujarat",
        "destination": "Gujarat",
        "duration": "7 Days / 6 Nights",
        "price": "45000",
        "attrs": {
            "package_name": SHORT_NAME,
            "destination": "Gujarat",
            "duration": "7 Days / 6 Nights",
            "itinerary": "Day 01 : Arrival in Ahmedabad\nDay 02 : Old city of Ahmedabad",
            "includes": "Hotel\nBreakfast\nGuide",
            "excludes": "Airfare\nVisa",
            "terms_conditions": "Minimum two guests per booking. Subject to availability.",
        },
    },
    {
        "name": LONG_NAME,
        "slug": "kerala-backwaters",
        "destination": "Kerala",
        "duration": "5 Days / 4 Nights",
        "price": "38000",
        "attrs": {
            "package_name": LONG_NAME,
            "destination": "Kerala",
            "duration": "5 Days / 4 Nights",
            "itinerary": "Day 01 : Kochi arrival",
            "includes": "Houseboat stay",
            "excludes": "Airfare",
        },
    },
]


class PackageBrowsingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "packages.sqlite3")
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        database.init_db()

        tenancy_store.ensure_tenant(
            TENANT, vertical="tours_travel", display_name="Tours Test",
        )
        tenancy_store.ensure_tenant(
            OTHER_TENANT, vertical="generic", display_name="Other Test",
        )
        tenancy_store.ensure_tenant(
            EMPTY_TENANT, vertical="generic", display_name="Empty Test",
        )
        tenancy_cache.purge(TENANT)
        tenancy_cache.purge(OTHER_TENANT)
        tenancy_cache.purge(EMPTY_TENANT)

        for pkg in PACKAGES:
            database.save_product(
                name=pkg["name"], slug=pkg["slug"], price=pkg["price"],
                attrs_json=pkg["attrs"], tenant_id=TENANT,
            )
        # A package that belongs to somebody else must never show up.
        database.save_product(
            name="Someone Else Package", slug="someone-else",
            attrs_json={"package_name": "Someone Else Package", "destination": "Nowhere"},
            tenant_id=OTHER_TENANT,
        )

        self.capture_tokens = whatsapp_sender.begin_capture(capture_only=True)

    def tearDown(self):
        whatsapp_sender.end_capture(self.capture_tokens)
        tenancy_cache.purge(TENANT)
        tenancy_cache.purge(OTHER_TENANT)
        self.db_patch.stop()
        self.temp.cleanup()

    # ── helpers ────────────────────────────────────────────────────────────

    def _run(self, coro):
        return asyncio.run(coro)

    def _captured(self):
        return whatsapp_sender.drain_captured()

    @staticmethod
    def _of_type(messages, kind):
        return [m for m in messages if m.get("type") == kind]

    @staticmethod
    def _texts(messages):
        return [m.get("text", "") for m in messages if m.get("type") == "text"]

    def _row(self, package_id):
        with database.get_db_context() as conn:
            return conn.execute(
                "SELECT * FROM products WHERE id = ?", (package_id,)
            ).fetchone()

    # ── the profile side ───────────────────────────────────────────────────

    def test_tours_profile_carries_the_package_booking_flow(self):
        profile = build_profile(TENANT, file_layer={}, include_db=False)
        flow = profile.flow("book_package")
        self.assertIsNotNone(flow, "the tours vertical must ship book_package")
        self.assertEqual(flow.requires_feature, "offering_details")
        self.assertTrue(profile.feature_on("offering_details"))

        steps = {s.id: s for s in flow.steps}
        # The package is already known when the user taps "Book This Package",
        # so the step must not ask for it a second time.
        self.assertTrue(steps["ask_package"].prefill)
        self.assertEqual(steps["ask_package"].key, "package")
        # The handoff floats the conversation into the live inbox.
        self.assertTrue(steps["handoff"].escalate)
        self.assertEqual(steps["save"].lead_source, "package_booking")
        self.assertEqual(steps["save"].collect_keys, ["name", "package", "phone"])

    def test_tours_profile_passes_the_profile_linters(self):
        profile = build_profile(TENANT, file_layer={}, include_db=False)
        result = tenancy_lint.lint_profile(profile)
        self.assertTrue(result["ok"], result)

    def test_a_generic_tenant_never_gets_the_package_flow(self):
        profile = build_profile(
            OTHER_TENANT, db_layer={"vertical": "generic"}, file_layer={},
            include_db=False,
        )
        self.assertNotIn("book_package", [f.name for f in profile.flows])

    # ── the catalogue ──────────────────────────────────────────────────────

    def test_catalogue_is_a_list_menu_of_this_tenants_packages(self):
        result = self._run(
            package_flow.handle_package_action(
                WA, "Tour Packages", tenant_id=TENANT,
            )
        )
        self.assertEqual(result["action"], "package_list")

        lists = self._of_type(self._captured(), "list")
        self.assertEqual(len(lists), 1)
        rows = [row for section in lists[0]["sections"] for row in section["rows"]]
        titles = [row["title"] for row in rows]
        self.assertIn(SHORT_NAME, titles)
        self.assertIn(LONG_NAME[:24], titles)
        self.assertNotIn("Someone Else Package", titles)
        for row in rows:
            self.assertTrue(row["id"].startswith("pkg_"))
            self.assertLessEqual(len(row["title"]), 24)

    def test_a_tenant_without_packages_is_left_alone(self):
        result = self._run(
            package_flow.handle_package_action(
                WA, "Tour Packages", tenant_id=EMPTY_TENANT,
            )
        )
        self.assertIsNone(result)
        self.assertEqual(self._captured(), [])

    def test_an_unrelated_message_falls_through(self):
        result = self._run(
            package_flow.handle_package_action(
                WA, "what are your visa requirements?", tenant_id=TENANT,
            )
        )
        self.assertIsNone(result)
        self.assertEqual(self._captured(), [])

    # ── the package card ───────────────────────────────────────────────────

    def test_tapping_a_package_shows_the_card_and_the_booking_button(self):
        result = self._run(
            package_flow.handle_package_action(
                WA, SHORT_NAME, tenant_id=TENANT,
            )
        )
        self.assertEqual(result["action"], "package_details")
        self.assertEqual(result["package"], SHORT_NAME)

        messages = self._captured()
        card = self._texts(messages)[0]
        self.assertIn(SHORT_NAME, card)
        self.assertIn("Gujarat", card)
        self.assertIn("7 Days / 6 Nights", card)
        self.assertIn("Day 01", card)
        # "package prices" is on the never_state list - the card points at the
        # team, it never quotes a number.
        self.assertNotIn("45000", card)
        self.assertIn("varies by date", card)

        buttons = self._of_type(messages, "buttons")
        self.assertEqual(len(buttons), 1)
        reply = buttons[0]["buttons"][0]["reply"]
        self.assertEqual(reply["title"], "Book This Package")
        self.assertTrue(reply["id"].startswith("pkg_book_"))

    def test_the_truncated_row_title_still_matches(self):
        # WhatsApp truncates the row title to 24 characters and sends2 hands
        # the truncated string back on the tap.
        result = self._run(
            package_flow.handle_package_action(
                WA, LONG_NAME[:24], tenant_id=TENANT,
            )
        )
        self.assertEqual(result["action"], "package_details")
        self.assertEqual(result["package"], LONG_NAME)

    # ── the booking flow ───────────────────────────────────────────────────

    def _start_booking(self):
        """Show a card, then tap the booking button on it."""
        self._run(
            package_flow.handle_package_action(WA, SHORT_NAME, tenant_id=TENANT)
        )
        self._captured()
        result = self._run(
            package_flow.handle_package_action(
                WA, "Book This Package", tenant_id=TENANT,
            )
        )
        return result

    def test_the_booking_button_starts_the_flow_with_the_package_known(self):
        result = self._start_booking()
        self.assertEqual(result["action"], "booking")
        self.assertEqual(result["package"], SHORT_NAME)

        convo = state_manager.read_conversation(WA)
        self.assertEqual(convo["active_flow"], "book_package")
        self.assertEqual(convo["collected"].get("package"), SHORT_NAME)

        texts = self._texts(self._captured())
        self.assertTrue(any("name" in t.lower() for t in texts), texts)
        # The package is already known - the flow must not ask for it again.
        self.assertFalse(any("which tour package" in t.lower() for t in texts), texts)

    def test_a_named_package_with_a_book_verb_goes_straight_to_booking(self):
        result = self._run(
            package_flow.handle_package_action(
                WA, f"I want to book {SHORT_NAME}", tenant_id=TENANT,
            )
        )
        self.assertEqual(result["action"], "booking")
        convo = state_manager.read_conversation(WA)
        self.assertEqual(convo["active_flow"], "book_package")
        self.assertEqual(convo["collected"].get("package"), SHORT_NAME)

    def test_completing_the_booking_creates_a_lead_and_escalates(self):
        self._start_booking()
        self._captured()

        after_name = flow_runner.handle_reply(WA, "Aarav Sharma", tenant_id=TENANT)
        phone_prompt = self._outcome_text(after_name)
        self.assertIn("phone number", phone_prompt.lower())
        # The package step is pre-filled, so it was skipped.
        self.assertNotIn("which tour package", phone_prompt.lower())

        final = flow_runner.handle_reply(WA, "9876543210", tenant_id=TENANT)
        self.assertTrue(final.get("finished"))

        with database.get_db_context() as conn:
            lead = conn.execute(
                "SELECT * FROM leads WHERE wa_id = ?", (WA,)
            ).fetchone()
            handoff = conn.execute(
                "SELECT * FROM handoffs WHERE wa_id = ?", (WA,)
            ).fetchone()
        self.assertIsNotNone(lead, "the booking must create a lead")
        self.assertEqual(lead["tenant_id"], TENANT)
        self.assertEqual(lead["name"] if "name" in lead.keys() else lead["user_name"], "Aarav Sharma")
        self.assertEqual(lead["phone"], "9876543210")
        self.assertEqual(lead["source"], "package_booking")
        self.assertEqual(lead["flow"], "book_package")
        collected = json.loads(lead["collected"])
        self.assertEqual(collected.get("package"), SHORT_NAME)
        # service_required is a legacy column: it is only written when the
        # deployment has it, so the durable record of the package is `collected`.
        if "service_required" in lead.keys():
            self.assertEqual(lead["service_required"], SHORT_NAME)

        self.assertIsNotNone(handoff, "the booking must create a handoff")
        self.assertEqual(handoff["reason"], "package_booking")
        self.assertEqual(handoff["status"], "pending")

        # The conversation floats to the top of the admin live inbox.
        self.assertEqual(database.get_user_state(WA).get("human_handover"), 1)

    def test_specific_question_about_package_falls_through_and_remembers_package(self):
        result = self._run(
            package_flow.handle_package_action(
                WA, f"Where would be Pickup and drop-off of {SHORT_NAME}?", tenant_id=TENANT,
            )
        )
        self.assertIsNone(result, "Specific questions must fall through to FAQ/RAG")
        pending = package_flow.pending_package(WA)
        self.assertEqual(pending.get("name"), SHORT_NAME, "Package must still be remembered in context")

    def test_hotel_question_about_package_falls_through(self):
        result = self._run(
            package_flow.handle_package_action(
                WA, f"Which hotel is allocated to me in {SHORT_NAME}?", tenant_id=TENANT,
            )
        )
        self.assertIsNone(result, "Hotel question must fall through to FAQ/RAG")
        pending = package_flow.pending_package(WA)
        self.assertEqual(pending.get("name"), SHORT_NAME)

    @staticmethod
    def _outcome_text(outcome):
        messages = outcome.get("messages") or []
        parts = []
        for message in messages:
            if isinstance(message, dict):
                parts.append(str(message.get("text", "")))
            else:
                parts.append(str(message))
        return " ".join(parts)


if __name__ == "__main__":
    unittest.main()
