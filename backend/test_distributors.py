"""Validation coverage for the distributor directory API.

Compulsory fields (name, phone, email), their formats (country code + 10-digit
phone, proper email, 15-digit WhatsApp phone number id) and the new City /
Address / Service area columns.
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

from fastapi import FastAPI
from fastapi.testclient import TestClient

import database
from routes import auth as auth_routes
from routes import distributors as distributors_routes

PASSWORD = "RootPass123!"

VALID = {
    "wa_id": "100012345678901",
    "name": "Acme Traders",
    "phone": "+91 98765 43210",
    "email": "owner@acme.example",
    "region": "West",
    "city": "Ahmedabad",
    "address": "12, Ring Road",
    "service_area": "Navrangpura, Vastrapur",
    "tier": "Gold",
    "product_interests": ["chikki"],
}


class DistributorValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "dist.sqlite3")
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        database.init_db()

        self.app = FastAPI()
        if auth_routes.RATE_LIMIT_ENABLED:
            self.app.state.limiter = auth_routes.limiter
        self.app.include_router(auth_routes.router)
        self.app.include_router(distributors_routes.router)
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

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def _create(self, **overrides):
        payload = {**VALID, **overrides}
        return self.client.post(
            "/api/admin/tenants/acme/distributors", json=payload, headers=self.headers
        )

    def test_valid_distributor_round_trips_new_fields(self):
        res = self._create()
        self.assertEqual(res.status_code, 200, res.text)
        found = self.client.get(
            "/api/admin/tenants/acme/distributors/lookup/100012345678901",
            headers=self.headers,
        )
        self.assertEqual(found.status_code, 200, found.text)
        body = found.json()
        self.assertEqual(body["city"], "Ahmedabad")
        self.assertEqual(body["address"], "12, Ring Road")
        self.assertEqual(body["service_area"], "Navrangpura, Vastrapur")

    def test_compulsory_fields(self):
        res = self._create(name="", phone="", email="")
        self.assertEqual(res.status_code, 422)
        detail = res.json()["detail"]
        self.assertIn("name is required", detail)
        self.assertIn("phone is required", detail)
        self.assertIn("email is required", detail)

    def test_formats(self):
        res = self._create(phone="9876543210")
        self.assertEqual(res.status_code, 422)
        self.assertIn("country code", res.json()["detail"])

        res = self._create(phone="+91 1800 123 4567")
        self.assertEqual(res.status_code, 422)
        self.assertIn("10-digit number", res.json()["detail"])

        res = self._create(email="not-an-email")
        self.assertEqual(res.status_code, 422)
        self.assertIn("valid address", res.json()["detail"])

        res = self._create(wa_id="919876543210")
        self.assertEqual(res.status_code, 422)
        self.assertIn("exactly 15 digits", res.json()["detail"])

    def test_update_validates_only_sent_fields(self):
        self._create()
        base = "/api/admin/tenants/acme/distributors"
        res = self.client.put(
            f"{base}/100012345678901", json={"phone": "9876543210"}, headers=self.headers
        )
        self.assertEqual(res.status_code, 422)

        res = self.client.put(
            f"{base}/100012345678901",
            json={"city": "Surat", "service_area": "Adajan"},
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 200, res.text)

        found = self.client.get(
            f"{base}/lookup/100012345678901", headers=self.headers
        ).json()
        self.assertEqual(found["city"], "Surat")
        self.assertEqual(found["service_area"], "Adajan")
        # Untouched fields keep their values.
        self.assertEqual(found["name"], "Acme Traders")

    def test_migration_adds_columns_to_existing_table(self):
        """A database created before this change gets the three new columns."""
        import sqlite3

        with patch.object(database, "DB_PATH", self.db_path):
            database.init_db()
        conn = sqlite3.connect(self.db_path)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(distributors)").fetchall()}
        conn.close()
        self.assertIn("city", columns)
        self.assertIn("address", columns)
        self.assertIn("service_area", columns)


if __name__ == "__main__":
    unittest.main()
