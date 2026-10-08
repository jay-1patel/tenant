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

        # One approved template.
        res = self.client.post(
            f"{BASE}/templates",
            json={
                "name": "diwali_restock",
                "category": "MARKETING",
                "body": "Hi {{name}}, get 20% off on your Diwali restock.",
            },
            headers=self.headers,
        )
        assert res.status_code == 201, res.text

        # Distributors with states and tiers for the segments.
        with database.get_db_context() as conn:
            for wa, tier, region, city in (
                ("100012345678901", "Gold", "Gujarat", "Ahmedabad"),
                ("100012345678902", "Platinum", "Gujarat", "Surat"),
                ("100012345678903", "Bronze", "Maharashtra", "Pune"),
            ):
                conn.execute(
                    "INSERT INTO distributors (wa_id, tenant_id, name, tier, region, city) "
                    "VALUES (?, 'acme', ?, ?, ?, ?)",
                    (wa, wa, tier, region, city),
                )
            # Two chat contacts with different lifetime purchase values.
            for wa in ("919876543210", "919876543211"):
                conn.execute(
                    "INSERT INTO chat_history (wa_id, tenant_id, message, response, route) "
                    "VALUES (?, 'acme', 'hi', 'hello', 'faq')",
                    (wa,),
                )
            conn.execute(
                "INSERT INTO orders (order_number, wa_id, total_amount) VALUES ('O1', '919876543210', 15000)"
            )
            conn.execute(
                "INSERT INTO orders (order_number, wa_id, total_amount) VALUES ('O2', '919876543211', 2000)"
            )

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def _create(self, **overrides):
        return self.client.post(
            f"{BASE}", json={**VALID, **overrides}, headers=self.headers
        )

    def _create_segment(self, name, audience_type, criteria):
        res = self.client.post(
            f"{BASE}/segments",
            json={"name": name, "audience_type": audience_type, "criteria": criteria},
            headers=self.headers,
        )
        assert res.status_code == 201, res.text
        return res.json()["id"]

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

    def test_segments_are_stored_audiences_with_criteria(self):
        # Distributor segment: State = Gujarat.
        self._create_segment("Gujarat Distributors", "distributors", {"regions": ["Gujarat"]})
        # Customer segment: Total purchases > ₹10,000.
        self._create_segment("High-Value Customers", "customers", {"min_total_purchases": 10000})

        segments = self.client.get(f"{BASE}/segments", headers=self.headers).json()["segments"]
        by_name = {s["name"]: s for s in segments}

        gujarat = by_name["Gujarat Distributors"]
        self.assertEqual(gujarat["audience_type"], "distributors")
        self.assertEqual(gujarat["criteria"], {"regions": ["Gujarat"]})
        self.assertEqual(gujarat["target_count"], 2)

        high_value = by_name["High-Value Customers"]
        self.assertEqual(high_value["audience_type"], "customers")
        self.assertEqual(high_value["criteria"], {"min_total_purchases": 10000})
        self.assertEqual(high_value["target_count"], 1)  # only the ₹15,000 contact

    def test_segment_crud_validation(self):
        res = self.client.post(
            f"{BASE}/segments",
            json={"name": "", "audience_type": "distributors", "criteria": {}},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 422)

        res = self.client.post(
            f"{BASE}/segments",
            json={"name": "X", "audience_type": "aliens", "criteria": {}},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("audience type must be one of", res.json()["detail"])

        res = self.client.post(
            f"{BASE}/segments",
            json={"name": "X", "audience_type": "distributors", "criteria": {"min_total_purchases": 5}},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("not a valid criterion", res.json()["detail"])

        res = self.client.post(
            f"{BASE}/segments",
            json={"name": "X", "audience_type": "customers", "criteria": {"min_total_purchases": "lots"}},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("must be a number", res.json()["detail"])

        # Duplicate names collide per tenant.
        segment_id = self._create_segment("Gold tier", "distributors", {"tiers": ["Gold"]})
        res = self.client.post(
            f"{BASE}/segments",
            json={"name": "Gold tier", "audience_type": "distributors", "criteria": {}},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 409)

        # Update and delete work.
        res = self.client.put(
            f"{BASE}/segments/{segment_id}",
            json={"name": "Gold tier", "audience_type": "distributors", "criteria": {"tiers": ["Gold", "Platinum"]}},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200)
        segments = self.client.get(f"{BASE}/segments", headers=self.headers).json()["segments"]
        self.assertEqual(next(s for s in segments if s["id"] == segment_id)["target_count"], 2)

        res = self.client.delete(f"{BASE}/segments/{segment_id}", headers=self.headers)
        self.assertEqual(res.status_code, 200)
        res = self.client.delete(f"{BASE}/segments/{segment_id}", headers=self.headers)
        self.assertEqual(res.status_code, 404)

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
        template_id = self.client.get(f"{BASE}/templates", headers=self.headers).json()["templates"][0]["id"]
        self.client.put(
            f"{BASE}/templates/{template_id}", json={"status": "rejected"}, headers=self.headers
        )
        res = self._create()
        self.assertEqual(res.status_code, 422)
        self.client.put(
            f"{BASE}/templates/{template_id}", json={"status": "registered"}, headers=self.headers
        )

        # Segments audience needs a saved segment.
        res = self._create(audience_type="segments", segment_id=None)
        self.assertEqual(res.status_code, 422)
        self.assertIn("segment must be selected", res.json()["detail"])

        res = self._create(audience_type="segments", segment_id=99999)
        self.assertEqual(res.status_code, 422)
        self.assertIn("does not exist", res.json()["detail"])

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
        self.assertEqual(customer_campaign["target_count"], 2)

    def test_segments_audience_targets_only_the_segment(self):
        segment_id = self._create_segment("Gujarat Distributors", "distributors", {"regions": ["Gujarat"]})
        res = self._create(audience_type="segments", segment_id=segment_id)
        self.assertEqual(res.status_code, 200)

        listed = self.client.get(f"{BASE}", headers=self.headers).json()["campaigns"]
        campaign = next(c for c in listed if c["id"] == res.json()["id"])
        self.assertEqual(campaign["target_count"], 2)
        self.assertEqual(campaign["segment_id"], segment_id)
        # The criteria are snapshotted onto the campaign for the review trail.
        self.assertEqual(campaign["segment"], {"regions": ["Gujarat"]})

        # A customer segment counts by purchase value instead.
        high_value = self._create_segment("High-Value Customers", "customers", {"min_total_purchases": 10000})
        res = self._create(audience_type="segments", segment_id=high_value)
        self.assertEqual(res.status_code, 200)
        listed = self.client.get(f"{BASE}", headers=self.headers).json()["campaigns"]
        campaign = next(c for c in listed if c["id"] == res.json()["id"])
        self.assertEqual(campaign["target_count"], 1)

    def test_opt_out_excludes_contacts(self):
        """Consent: a STOP contact never appears in an audience count."""
        with database.get_db_context() as conn:
            conn.execute(
                "INSERT INTO campaign_opt_outs (tenant_id, wa_id) VALUES ('acme', '100012345678901')"
            )
        segment_id = self._create_segment("Gold tier", "distributors", {"tiers": ["Gold"]})
        segments = self.client.get(f"{BASE}/segments", headers=self.headers).json()["segments"]
        gold = next(s2 for s2 in segments if s2["id"] == segment_id)
        self.assertEqual(gold["target_count"], 0)  # the only Gold distributor opted out

    def test_distributor_criteria_purchase_and_exclusions(self):
        self._create_segment("Gujarat Gold", "distributors", {"regions": ["Gujarat"], "tiers": ["Gold"]})
        self._create_segment("Except Surat", "distributors", {"regions": ["Gujarat"], "exclude_city": "Surat"})
        self._create_segment("Outstanding credit", "distributors", {"credit_status": "outstanding"})
        self._create_segment("Gold or Platinum", "distributors", {"tiers": ["Gold", "Platinum"], "match": "any"})

        segments = {
            s2["name"]: s2
            for s2 in self.client.get(f"{BASE}/segments", headers=self.headers).json()["segments"]
        }
        self.assertEqual(segments["Gujarat Gold"]["target_count"], 1)  # Ahmedabad Gold
        self.assertEqual(segments["Except Surat"]["target_count"], 1)  # Gujarat minus Surat
        self.assertEqual(segments["Outstanding credit"]["target_count"], 0)  # nobody owes money
        # match: any — every Gujarat distributor is Gold or Platinum here.
        self.assertEqual(segments["Gold or Platinum"]["target_count"], 2)

        # Criteria validation rejects unknown keys and bad values.
        res = self.client.post(
            f"{BASE}/segments",
            json={"name": "Bad", "audience_type": "distributors", "criteria": {"credit_status": "maybe"}},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 422)

    def test_customer_purchase_criteria(self):
        self._create_segment("Repeat buyers", "customers", {"order_count_min": 1})
        self._create_segment("Big spenders", "customers", {"min_total_purchases": 5000, "max_total_purchases": 20000})

        segments = {
            s2["name"]: s2
            for s2 in self.client.get(f"{BASE}/segments", headers=self.headers).json()["segments"]
        }
        self.assertEqual(segments["Repeat buyers"]["target_count"], 2)  # both have one order
        self.assertEqual(segments["Big spenders"]["target_count"], 1)  # ₹15,000 only

    def test_campaign_type_must_match_template_category(self):
        res = self._create(campaign_type="transactional")  # template is MARKETING
        self.assertEqual(res.status_code, 422)
        self.assertIn("needs a UTILITY", res.json()["detail"])

    def test_variable_fallbacks_and_pause(self):
        campaign_id = self._create(variable_fallbacks={"name": "Friend"}).json()["id"]
        listed = self.client.get(f"{BASE}", headers=self.headers).json()["campaigns"]
        campaign = next(c for c in listed if c["id"] == campaign_id)
        self.assertEqual(campaign["variable_fallbacks"], {"name": "Friend"})

        # Pausing a scheduled campaign is an admin action.
        res = self.client.put(
            f"{BASE}/{campaign_id}", json={**VALID, "status": "paused"}, headers=self.headers
        )
        self.assertEqual(res.status_code, 200)

    def test_send_rejects_invalid_test_number(self):
        campaign_id = self._create().json()["id"]
        res = self.client.post(
            f"{BASE}/{campaign_id}/test-send", json={"wa_id": "12"}, headers=self.headers
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("digits-only", res.json()["detail"])

    def test_media_upload_and_campaign_attachment(self):
        """Media arrives as an upload: stored on disk, tracked per tenant."""
        upload_dir = os.path.join(self.temp.name, "uploads")
        with patch("routes.admin.UPLOAD_DIR", upload_dir):
            res = self.client.post(
                f"{BASE}/media",
                files={"file": ("offer.jpg", b"jpeg-bytes", "image/jpeg")},
                headers=self.headers,
            )
        self.assertEqual(res.status_code, 200, res.text)
        filename = res.json()["filename"]
        self.assertTrue(filename.startswith("campaign_acme_"), filename)
        self.assertTrue(filename.endswith(".jpg"))
        self.assertTrue(os.path.exists(os.path.join(upload_dir, filename)))

        # Wrong type and oversize files are refused.
        with patch("routes.admin.UPLOAD_DIR", upload_dir):
            res = self.client.post(
                f"{BASE}/media",
                files={"file": ("offer.pdf", b"pdf-bytes", "application/pdf")},
                headers=self.headers,
            )
        self.assertEqual(res.status_code, 422)

        res = self.client.post(
            f"{BASE}/media",
            files={"file": ("big.jpg", b"x" * (16 * 1024 * 1024 + 1), "image/jpeg")},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 413)

        # The uploaded filename attaches to a campaign.
        res = self._create(media_filename=filename)
        self.assertEqual(res.status_code, 200, res.text)

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
