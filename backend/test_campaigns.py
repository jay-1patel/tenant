"""Coverage for the campaign builder: templates, segments and validation."""

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

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
from routes import auth as auth_routes
from routes import campaigns as campaigns_routes

PASSWORD = "RootPass123!"

BASE = "/api/admin/tenants/acme/campaigns"

VALID = {
    "name": "Diwali restock offer",
    "status": "scheduled",
    "campaign_type": "promotional",
    "audience_type": "distributors",
    "whatsapp_template": "diwali_restock",
    "template_variables": {"name": "{name}"},
    "buttons": [],
    "schedule_mode": "now",
    "timezone": "Asia/Kolkata",
}


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            database, "DB_PATH", os.path.join(self.temp.name, "camp.sqlite3")
        )
        self.db_patch.start()
        database.init_db()

        self.app = FastAPI()
        if auth_routes.RATE_LIMIT_ENABLED:
            self.app.state.limiter = auth_routes.limiter
        self.app.include_router(auth_routes.router)
        self.app.include_router(campaigns_routes.router)
        self.client = TestClient(self.app)

        first = self.client.post(
            "/api/auth/first-admin", json={"username": "root", "password": PASSWORD}
        )
        assert first.status_code == 200, first.text
        res = self.client.post(
            "/api/auth/login", json={"username": "root", "password": PASSWORD}
        )
        assert res.status_code == 200, res.text
        self.headers = {"Authorization": f"Bearer {res.json()['token']}"}

        # One approved template + a few distributors for the derived segments.
        res = self.client.post(
            f"{BASE}/templates",
            json={
                "name": "diwali_restock",
                "category": "promotional",
                "body": "Hi {{name}}, get 20% off on your Diwali restock.",
            },
            headers=self.headers,
        )
        assert res.status_code == 201, res.text
        with database.get_db_context() as conn:
            for wa, tier, region in (
                ("100012345678901", "Gold", "West"),
                ("100012345678902", "Platinum", "East"),
                ("100012345678903", "Bronze", "West"),
            ):
                conn.execute(
                    "INSERT INTO distributors (wa_id, tenant_id, name, tier, region) "
                    "VALUES (?, 'acme', ?, ?, ?)",
                    (wa, wa, tier, region),
                )
            conn.execute(
                "INSERT INTO chat_history (wa_id, tenant_id, message, response, route) "
                "VALUES ('919876543210', 'acme', 'hi', 'hello', 'faq')"
            )

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def _create(self, **overrides):
        return self.client.post(
            f"{BASE}", json={**VALID, **overrides}, headers=self.headers
        )

    def test_template_registry(self):
        listed = self.client.get(f"{BASE}/templates", headers=self.headers).json()
        assert any(t["name"] == "diwali_restock" and t["status"] == "registered" for t in listed["templates"])

        dup = self.client.post(
            f"{BASE}/templates",
            json={"name": "diwali_restock", "body": "x"},
            headers=self.headers,
        )
        self.assertEqual(dup.status_code, 409)

        bad = self.client.post(f"{BASE}/templates", json={"name": "", "body": "x"}, headers=self.headers)
        self.assertEqual(bad.status_code, 422)

    def test_segments_derived_from_distributors(self):
        segments = self.client.get(f"{BASE}/segments", headers=self.headers).json()["segments"]
        ids = [s["id"] for s in segments]
        self.assertIn("all", ids)
        self.assertIn("high_value", ids)
        self.assertIn("tier:Gold", ids)
        self.assertIn("region:West", ids)
        high = next(s for s in segments if s["id"] == "high_value")
        self.assertEqual(set(high["segment"]["tiers"]), {"Gold", "Platinum"})

    def test_create_requires_valid_fields(self):
        res = self._create(name="")
        self.assertEqual(res.status_code, 422)
        self.assertIn("campaign name is required", res.json()["detail"])

        res = self._create(campaign_type="blast")
        self.assertEqual(res.status_code, 422)
        self.assertIn("campaign type must be one of", res.json()["detail"])

        res = self._create(whatsapp_template="")
        self.assertEqual(res.status_code, 422)
        self.assertIn("approved WhatsApp template must be selected", res.json()["detail"])

        res = self._create(whatsapp_template="not_a_template")
        self.assertEqual(res.status_code, 422)
        self.assertIn("does not exist or is not approved", res.json()["detail"])

        # A non-approved template cannot be used either.
        self.client.put(
            f"{BASE}/templates/1", json={"status": "rejected"}, headers=self.headers
        )
        res = self._create()
        self.assertEqual(res.status_code, 422)
        self.client.put(
            f"{BASE}/templates/1", json={"status": "registered"}, headers=self.headers
        )

        res = self._create(audience_type="segments", segment=None)
        self.assertEqual(res.status_code, 422)
        self.assertIn("segment must be selected", res.json()["detail"])

        res = self._create(schedule_mode="scheduled", scheduled_at=None)
        self.assertEqual(res.status_code, 422)
        self.assertIn("schedule date and time are required", res.json()["detail"])

        res = self._create(media_filename="flyer.pdf")
        self.assertEqual(res.status_code, 422)
        self.assertIn("JPG, PNG or MP4", res.json()["detail"])

        res = self._create(buttons=[{"type": "url", "text": "Shop", "url": "http://x.io"}])
        self.assertEqual(res.status_code, 422)
        self.assertIn("HTTPS", res.json()["detail"])

        res = self._create(buttons=[{"type": "url", "text": "Shop", "url": ""}])
        self.assertEqual(res.status_code, 422)
        self.assertIn("CTA button needs a URL", res.json()["detail"])

    def test_create_is_scheduled_and_counts_the_audience(self):
        res = self._create()
        self.assertEqual(res.status_code, 200, res.text)
        campaign_id = res.json()["id"]

        listed = self.client.get(f"{BASE}", headers=self.headers).json()["campaigns"]
        campaign = next(c for c in listed if c["id"] == campaign_id)
        self.assertEqual(campaign["status"], "scheduled")  # engine-owned, auto-managed
        self.assertEqual(campaign["campaign_type"], "promotional")
        self.assertEqual(campaign["whatsapp_template"], "diwali_restock")
        # The message is the approved template's body, not free-typed text.
        self.assertIn("20% off", campaign["message_template"])
        self.assertEqual(campaign["target_count"], 3)  # all distributors

        # Customers audience counts chat contacts instead.
        res = self._create(audience_type="customers")
        self.assertEqual(res.status_code, 200)
        listed = self.client.get(f"{BASE}", headers=self.headers).json()["campaigns"]
        customer_campaign = next(c for c in listed if c["id"] == res.json()["id"])
        self.assertEqual(customer_campaign["target_count"], 1)

    def test_segments_audience_targets_only_the_segment(self):
        res = self._create(
            audience_type="segments", segment={"tiers": ["Gold", "Platinum"]}
        )
        self.assertEqual(res.status_code, 200)
        listed = self.client.get(f"{BASE}", headers=self.headers).json()["campaigns"]
        campaign = next(c for c in listed if c["id"] == res.json()["id"])
        self.assertEqual(campaign["target_count"], 2)

    def test_status_is_engine_owned_on_update(self):
        campaign_id = self._create().json()["id"]
        res = self.client.put(
            f"{BASE}/{campaign_id}",
            json={**VALID, "status": "completed"},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("engine-managed", res.json()["detail"])

        res = self.client.put(
            f"{BASE}/{campaign_id}",
            json={**VALID, "status": "cancelled"},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)


if __name__ == "__main__":
    unittest.main()
