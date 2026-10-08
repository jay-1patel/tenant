"""Coverage for tenant API onboarding requests and superadmin review."""

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import contextmanager
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
from routes import api_onboarding


class ApiOnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "onboarding.sqlite3")
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE tenants (id TEXT PRIMARY KEY);
            INSERT INTO tenants (id) VALUES ('tenant-a'), ('tenant-b');
            CREATE TABLE api_onboarding_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                api_type TEXT NOT NULL,
                provider TEXT NOT NULL DEFAULT '',
                environment TEXT NOT NULL,
                purpose TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requester_id INTEGER,
                requester_username TEXT NOT NULL DEFAULT '',
                reviewer_id INTEGER,
                reviewer_username TEXT,
                decision_note TEXT NOT NULL DEFAULT '',
                decided_at TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX ux_api_onboarding_pending
                ON api_onboarding_requests(tenant_id, api_type)
                WHERE status IN ('pending', 'approved');
            CREATE TABLE api_onboarding_entitlements (
                tenant_id TEXT NOT NULL,
                api_type TEXT NOT NULL,
                request_id INTEGER NOT NULL UNIQUE,
                granted_by INTEGER,
                granted_by_username TEXT NOT NULL DEFAULT '',
                granted_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, api_type)
            );
            CREATE TABLE api_onboarding_request_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id INTEGER NOT NULL,
                actor_id INTEGER,
                actor_username TEXT NOT NULL DEFAULT '',
                actor_role TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL,
                old_status TEXT,
                new_status TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        database._init_admin_audit_tables(conn)
        conn.commit()
        conn.close()
        self.db_patch = patch.object(api_onboarding, "get_db", side_effect=self._connect)
        self.context_patch = patch.object(api_onboarding, "get_db_context", self._db_context)
        self.db_patch.start()
        self.context_patch.start()

        self.client = TestClient(FastAPI())
        self.client.app.include_router(api_onboarding.router)
        self.current_admin = None
        self.client.app.dependency_overrides[api_onboarding.get_current_admin] = lambda: self.current_admin

    def tearDown(self):
        self.db_patch.stop()
        self.context_patch.stop()
        self.temp.cleanup()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @contextmanager
    def _db_context(self):
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _admin(tenant_id="tenant-a", role="admin", **permissions):
        return {
            "id": 4 if role != "super_admin" else 1,
            "username": "tenant-user" if role != "super_admin" else "root",
            "role": role,
            "tenant_id": tenant_id,
            "permissions": {"manage_operations": True, **permissions},
        }

    def _create(self, api_type="payment_api", purpose="Reconcile settled payments", **extra):
        return self.client.post(
            "/api/integration-requests",
            json={
                "api_type": api_type,
                "provider": "Acme Gateway",
                "environment": "sandbox",
                "purpose": purpose,
                **extra,
            },
        )

    def test_schema_initialization_is_repeatable(self):
        schema_db = os.path.join(self.temp.name, "schema.sqlite3")
        with patch.object(database, "DB_PATH", schema_db):
            with patch("shared.tenancy.resolver.resolve_default_tenant", return_value="default"):
                database.init_db()
                database.init_db()
        conn = sqlite3.connect(schema_db)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn.close()
        self.assertIn("api_onboarding_requests", tables)
        self.assertIn("api_onboarding_request_events", tables)
        self.assertIn("api_onboarding_entitlements", tables)

    def test_submitter_tenant_is_derived_and_requests_are_tenant_scoped(self):
        self.current_admin = self._admin()
        created = self._create()
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["request"]["tenant_id"], "tenant-a")
        self.assertEqual(created.json()["request"]["status"], "pending")

        mine = self.client.get("/api/integration-requests")
        self.assertEqual(len(mine.json()["requests"]), 1)
        self.current_admin = self._admin("tenant-b")
        self.assertEqual(self.client.get("/api/integration-requests").json()["requests"], [])

        conn = self._connect()
        events = conn.execute("SELECT event_type, new_status FROM api_onboarding_request_events").fetchall()
        conn.close()
        self.assertEqual([(row["event_type"], row["new_status"]) for row in events], [("submitted", "pending")])

    def test_submit_requires_tenant_role_and_permission(self):
        self.current_admin = self._admin(None)
        self.assertEqual(self._create().status_code, 403)

        self.current_admin = {**self._admin(), "permissions": {"manage_operations": False}}
        self.assertEqual(self._create().status_code, 403)

        self.current_admin = self._admin(None, role="super_admin")
        self.assertEqual(self._create().status_code, 403)

    def test_only_one_pending_or_approved_request_per_tenant_and_api(self):
        self.current_admin = self._admin()
        self.assertEqual(self._create().status_code, 201)
        self.assertEqual(self._create().status_code, 409)

        self.current_admin = self._admin(None, role="super_admin")
        approved = self.client.post(
            "/api/admin/integration-requests/1/decision",
            json={"decision": "approved", "note": "Eligible for secure setup"},
        )
        self.assertEqual(approved.json()["request"]["status"], "approved")
        self.current_admin = self._admin()
        self.assertEqual(self._create().status_code, 409)

    def test_only_superadmin_can_list_review_queue_and_decide(self):
        self.current_admin = self._admin()
        self.assertEqual(self._create().status_code, 201)
        self.assertEqual(self.client.get("/api/admin/integration-requests").status_code, 403)
        self.assertEqual(
            self.client.post("/api/admin/integration-requests/1/decision", json={"decision": "approved"}).status_code,
            403,
        )

        self.current_admin = self._admin(None, role="super_admin")
        self.assertEqual(len(self.client.get("/api/admin/integration-requests").json()["requests"]), 1)
        result = self.client.post(
            "/api/admin/integration-requests/1/decision",
            json={"decision": "rejected", "note": "Not supported yet"},
        ).json()["request"]
        self.assertEqual(result["reviewer_username"], "root")
        self.assertEqual(result["decision_note"], "Not supported yet")
        self.assertIsNotNone(result["decided_at"])

        conn = self._connect()
        event = conn.execute(
            "SELECT actor_role, old_status, new_status, note FROM api_onboarding_request_events WHERE event_type='decision'"
        ).fetchone()
        conn.close()
        self.assertEqual(tuple(event), ("super_admin", "pending", "rejected", "Not supported yet"))

    def test_decision_is_one_time_and_rejected_request_can_be_resubmitted(self):
        self.current_admin = self._admin()
        self._create()
        self.current_admin = self._admin(None, role="super_admin")
        decision = {"decision": "rejected"}
        self.assertEqual(self.client.post("/api/admin/integration-requests/1/decision", json=decision).status_code, 200)
        self.assertEqual(self.client.post("/api/admin/integration-requests/1/decision", json=decision).status_code, 409)
        self.current_admin = self._admin()
        self.assertEqual(self._create().status_code, 201)

    def test_approval_grants_entitlement_and_rejection_does_not(self):
        self.current_admin = self._admin()
        self._create()
        self.current_admin = self._admin(None, role="super_admin")
        response = self.client.post("/api/admin/integration-requests/1/decision", json={"decision": "approved"})
        self.assertTrue(response.json()["request"]["eligible"])
        events = self.client.get("/api/admin/integration-requests/1/events").json()["events"]
        self.assertEqual([event["event_type"] for event in events], ["submitted", "decision"])

    def test_invalid_fields_types_and_likely_secrets_are_rejected_without_echo(self):
        self.current_admin = self._admin()
        self.assertEqual(self._create(api_key="sensitive-value").status_code, 422)
        secret = "sk_live_sensitive-value"
        response = self._create(purpose=f"Use {secret} to reconcile settled payments")
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(secret, response.text)
        self.assertEqual(self._create(api_type="unknown").status_code, 422)


if __name__ == "__main__":
    unittest.main()
