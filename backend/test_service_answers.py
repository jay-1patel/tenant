"""Regression tests for deterministic, tenant-scoped service answers."""

import os
import sys
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.services import service_answers


class _Features:
    def __init__(self, offerings=True):
        self.offerings = offerings

    def is_on(self, flag):
        return bool(getattr(self, flag, False))


class _Intent:
    name = "service_enquiry"
    enabled = True
    keywords = ["service", "services", "what do you do", "offerings"]
    examples = ["what services do you offer"]


class _Profile:
    def __init__(self, offerings=True):
        self.features = _Features(offerings)
        self.intent_spec = _Intent()

    def intent(self, name):
        return self.intent_spec if name == "service_enquiry" else None

    def feature_on(self, name):
        return self.features.is_on(name)


class ServiceAnswersTests(unittest.TestCase):
    def setUp(self):
        self.profiles = {
            "tenant-a": _Profile(),
            "tenant-b": _Profile(),
        }
        self.records = {
            "tenant-a": [
                {"name": "Web Development", "short_description": "Websites and portals", "is_active": 1},
                {"name": "Mobile Apps", "short_description": "iOS and Android apps", "is_active": 1},
            ],
            "tenant-b": [
                {"name": "Tax Advisory", "short_description": "Tax planning", "is_active": 1},
            ],
        }
        self.loader = patch(
            "shared.tenancy.loader.get_tenant_profile",
            side_effect=lambda tid: self.profiles[tid],
        )
        self.resolver = patch(
            "shared.tenancy.resolver.resolve_tenant_for_user", return_value="tenant-a"
        )
        self.products = patch(
            "backend.database.list_products",
            side_effect=lambda active_only, limit, tenant_id: list(self.records[tenant_id]),
        )
        self.loader.start()
        self.resolver.start()
        self.products.start()

    def tearDown(self):
        self.loader.stop()
        self.resolver.stop()
        self.products.stop()

    def test_general_services_query_returns_only_current_tenant_offerings(self):
        answer = service_answers.answer_for_text("wa-1", "what services do you offer", tenant_id="tenant-a")
        self.assertIn("Web Development", answer)
        self.assertIn("Mobile Apps", answer)
        self.assertNotIn("Tax Advisory", answer)

    def test_specific_service_query_returns_only_matching_offering(self):
        answer = service_answers.answer_for_text("wa-1", "Tell me about Web Development", tenant_id="tenant-a")
        self.assertIn("Web Development", answer)
        self.assertNotIn("Mobile Apps", answer)

    def test_unrelated_queries_are_not_claimed_by_service_handler(self):
        self.assertIsNone(service_answers.answer_for_text("wa-1", "What is your refund policy?", tenant_id="tenant-a"))

    def test_empty_tenant_catalog_returns_deterministic_no_services_answer(self):
        self.records["tenant-a"] = []
        answer = service_answers.answer_for_text("wa-1", "what services do you offer", tenant_id="tenant-a")
        self.assertIn("don't have any services listed", answer)


if __name__ == "__main__":
    unittest.main()
