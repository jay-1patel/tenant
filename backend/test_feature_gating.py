"""Feature gating: switching a capability off must remove it from the menu,
the intent list, and the runtime paths — not just hide a button in the editor.

Covers the bug where 'Talk to Human' and the contact_human intent stayed live
after a tenant disabled human handover in the registration wizard.
"""

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
from shared.tenancy import store as tenancy_store
from shared.tenancy.gating import is_enabled
from shared.tenancy.loader import get_tenant_profile, validate_merged_profile


class FeatureGatingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "gating.sqlite3")
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.resolver_patch = patch(
            "shared.tenancy.resolver.resolve_default_tenant", return_value="default"
        )
        self.db_patch.start()
        self.resolver_patch.start()
        database.init_db()
        # The profile cache is process-wide; without this the second test would
        # read the first test's cached (gate-test, v1) profile.
        from shared.tenancy import cache as tenancy_cache
        tenancy_cache.purge("gate-test")

        tenancy_store.ensure_tenant("gate-test", vertical="generic", display_name="Gate Test")
        tenancy_store.save_draft(
            "gate-test",
            {
                "display_name": "Gate Test",
                "features": {
                    "offerings": True,
                    "callback": True,
                    "complaints": True,
                    "handoff": False,
                    "faq": False,
                    "kb": False,
                    "human_handover": False,
                },
            },
        )

    def tearDown(self):
        self.db_patch.stop()
        self.resolver_patch.stop()
        self.temp.cleanup()

    def _publish(self):
        draft = tenancy_store.get_draft("gate-test")
        profile = validate_merged_profile("gate-test", draft)
        version = tenancy_store.publish_version("gate-test", draft, published_by="test")
        return profile, version

    def test_disabled_features_leave_the_menu_and_intents(self):
        profile, version = self._publish()
        live = get_tenant_profile("gate-test")

        visible = {b.id for b in live.menu.visible_buttons(live.features)}
        self.assertIn("menu_offerings", visible)
        self.assertIn("menu_callback", visible)
        self.assertIn("menu_complaint", visible)
        # The three the operator switched off disappear from the menu.
        self.assertNotIn("menu_faq", visible)
        self.assertNotIn("menu_human", visible)

        # The human-handover intent is gone from the classifier's live set.
        active = live.active_intent_names()
        self.assertNotIn("contact_human", active)
        self.assertIn("callback_request", active)

        # And the runtime gate refuses instead of answering from a disabled
        # substrate.
        self.assertFalse(is_enabled("gate-test", "faq"))
        self.assertFalse(is_enabled("gate-test", "kb"))
        self.assertFalse(is_enabled("gate-test", "human_handover"))

    def test_enabled_handover_keeps_the_button_and_intent(self):
        tenancy_store.save_draft(
            "gate-test",
            {"features": {"human_handover": True, "faq": True, "kb": True}},
        )
        profile, version = self._publish()
        live = get_tenant_profile("gate-test")

        visible = {b.id for b in live.menu.visible_buttons(live.features)}
        self.assertIn("menu_human", visible)
        self.assertIn("menu_faq", visible)
        self.assertIn("contact_human", live.active_intent_names())
        self.assertTrue(is_enabled("gate-test", "human_handover"))


if __name__ == "__main__":
    unittest.main()
