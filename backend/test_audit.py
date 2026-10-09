"""Tests for durable admin audit history."""

import json
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
from routes import audit, auth


class AuditHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "audit.sqlite3")
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE admins (
                id INTEGER PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                permissions TEXT DEFAULT '{}',
                email TEXT,
                updated_at TEXT,
                tenant_id TEXT
            );
            INSERT INTO admins (id, username, password_hash, role, tenant_id)
                VALUES (2, 'staff', 'hash', 'sub_admin', 'tenant-a');
            """
        )
        database._init_admin_audit_tables(conn)
        conn.commit()
        conn.close()

        self.current_admin = {"id": 1, "username": "root", "role": "super_admin", "tenant_id": None}
        app = FastAPI()
        app.include_router(audit.router)
        app.include_router(auth.router)
        app.dependency_overrides[audit.get_current_admin] = lambda: self.current_admin
        self.client = TestClient(app)
        self.audit_db_patch = patch.object(audit, "get_db", side_effect=self._connect)
        self.auth_db_patch = patch.object(auth, "get_db_context", self._db_context)
        self.audit_db_patch.start()
        self.auth_db_patch.start()

    def tearDown(self):
        self.audit_db_patch.stop()
        self.auth_db_patch.stop()
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

    def _insert(self, *, action, actor="staff", role="sub_admin", outcome="success", tenant="tenant-a", details=None, created_at="2026-10-07 12:00:00"):
        with self._db_context() as conn:
            conn.execute(
                """INSERT INTO admin_audit_events
                   (created_at, actor_id, actor_username, actor_role, action, outcome,
                    resource_type, resource_id, target_username, tenant_id, details_json)
                   VALUES (?, 2, ?, ?, ?, ?, 'tenant', 'tenant-a', NULL, ?, ?)""",
                (created_at, actor, role, action, outcome, tenant, json.dumps(details or {})),
            )

    def test_schema_initialization_is_idempotent_and_prunes_old_events(self):
        conn = self._connect()
        conn.execute(
            "INSERT INTO admin_audit_events (created_at, action) VALUES ('2024-01-01 00:00:00', 'old')"
        )
        conn.commit()
        database._init_admin_audit_tables(conn)
        database._init_admin_audit_tables(conn)
        count = conn.execute("SELECT COUNT(*) FROM admin_audit_events").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_event_write_is_atomic_with_mutation(self):
        conn = self._connect()
        conn.execute("CREATE TABLE audit_test_mutations (id INTEGER PRIMARY KEY, value TEXT)")
        conn.commit()
        conn.close()
        conn = self._connect()
        conn.execute("BEGIN")
        conn.execute("INSERT INTO audit_test_mutations (id, value) VALUES (1, 'changed')")
        with patch.object(database, "safe_audit_details", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                database.record_admin_audit_event(conn, action="test_mutation", actor=self.current_admin)
        conn.rollback()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_test_mutations").fetchone()[0], 0)
        conn.close()

    def test_audit_endpoint_is_superadmin_only(self):
        self.current_admin = {"id": 2, "username": "staff", "role": "admin", "tenant_id": "tenant-a"}
        response = self.client.get("/api/admin/audit-history")
        self.assertEqual(response.status_code, 403)

    def test_filters_and_pagination_return_safe_event_fields(self):
        self._insert(action="login", outcome="failure", details={"reason": "invalid_credentials"})
        self._insert(action="tenant_profile_published", details={"version": 3}, created_at="2026-10-06 12:00:00")
        self._insert(action="tenant_deleted", actor="another", tenant="tenant-b", created_at="2026-10-05 12:00:00")

        response = self.client.get(
            "/api/admin/audit-history",
            params={"action": "login", "outcome": "failure", "tenant_id": "tenant-a", "limit": 1},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 1)
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["action"], "login")
        self.assertEqual(payload["events"][0]["details"], {"reason": "invalid_credentials"})
        self.assertNotIn("details_json", payload["events"][0])

        search = self.client.get("/api/admin/audit-history", params={"search": "published", "start_date": "2026-10-06", "end_date": "2026-10-06"})
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["total"], 1)

    def test_invalid_date_range_and_outcome_are_rejected(self):
        self.assertEqual(
            self.client.get("/api/admin/audit-history", params={"start_date": "2026-10-08", "end_date": "2026-10-07"}).status_code,
            422,
        )
        self.assertEqual(self.client.get("/api/admin/audit-history", params={"outcome": "maybe"}).status_code, 422)

    def test_first_admin_creation_is_audited_without_password_material(self):
        with patch.object(auth, "_admin_count", return_value=0), patch.object(auth, "_validate_password_strength"), patch.object(auth, "_hash_password", return_value="stored-hash"):
            response = self.client.post(
                "/api/auth/first-admin",
                json={"username": "bootstrap", "password": "BootstrapPassword!123", "email": "root@example.test"},
            )
        self.assertEqual(response.status_code, 200)
        conn = self._connect()
        admin = conn.execute("SELECT id, role FROM admins WHERE username = 'bootstrap'").fetchone()
        event = conn.execute("SELECT actor_username, action, details_json FROM admin_audit_events ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()
        self.assertEqual(admin["role"], "super_admin")
        self.assertEqual(event["actor_username"], "bootstrap")
        self.assertEqual(event["action"], "first_admin_created")
        self.assertNotIn("BootstrapPassword!123", event["details_json"])

    def test_login_success_and_failure_are_recorded_without_credentials(self):
        with patch.object(auth, "_verify_password", side_effect=lambda supplied, hashed: supplied == "correct"):
            with patch.object(auth, "_create_token", return_value="test-jwt"):
                failed = self.client.post("/api/auth/login", json={"username": "staff", "password": "wrong"})
                success = self.client.post("/api/auth/login", json={"username": "staff", "password": "correct"})
        self.assertEqual(failed.status_code, 401)
        self.assertEqual(success.status_code, 200)

        conn = self._connect()
        rows = conn.execute(
            "SELECT action, outcome, actor_username, tenant_id, details_json FROM admin_audit_events ORDER BY id"
        ).fetchall()
        conn.close()
        self.assertEqual([(row["action"], row["outcome"]) for row in rows], [("login", "failure"), ("login", "success")])
        self.assertEqual(rows[0]["actor_username"], "staff")
        self.assertEqual(rows[0]["tenant_id"], "tenant-a")
        self.assertNotIn("wrong", " ".join(row["details_json"] for row in rows))
        self.assertNotIn("test-jwt", " ".join(row["details_json"] for row in rows))

    def test_admin_role_change_records_before_after_and_changed_fields(self):
        target = {
            "id": 2,
            "username": "staff",
            "role": "sub_admin",
            "permissions": {"manage_operations": True},
            "tenant_id": "tenant-a",
            "email": None,
        }
        with patch.object(auth, "get_admin_record", return_value=target):
            response = self.client.patch("/api/auth/admins/staff", json={"role": "admin"})
        self.assertEqual(response.status_code, 200)
        conn = self._connect()
        row = conn.execute("SELECT action, details_json FROM admin_audit_events ORDER BY id DESC LIMIT 1").fetchone()
        updated = conn.execute("SELECT role FROM admins WHERE username = 'staff'").fetchone()
        conn.close()
        self.assertEqual(updated["role"], "admin")
        self.assertEqual(row["action"], "admin_updated")
        details = json.loads(row["details_json"])
        self.assertEqual(details["role_before"], "sub_admin")
        self.assertEqual(details["role_after"], "admin")
        self.assertIn("role", details["changed_fields"])

    def test_login_history_is_available_through_superadmin_endpoint(self):
        self._insert(action="login", outcome="failure")
        response = self.client.get("/api/admin/audit-history", params={"category": "authentication"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["total"], 1)
        self.assertEqual(response.json()["events"][0]["outcome"], "failure")

    def test_sensitive_detail_keys_are_removed(self):
        conn = self._connect()
        event_id = database.record_admin_audit_event(
            conn,
            action="test_redaction",
            actor=self.current_admin,
            details={"changed_fields": ["role"], "password": "never-store", "nested": {"token": "never-store"}},
        )
        conn.commit()
        details = conn.execute("SELECT details_json FROM admin_audit_events WHERE id = ?", (event_id,)).fetchone()[0]
        conn.close()
        self.assertEqual(json.loads(details), {"changed_fields": ["role"], "nested": {}})
        self.assertNotIn("never-store", details)

    def test_audit_context_captures_ip_user_agent_and_safe_tenant_metadata(self):
        tenancy = self._connect()
        tenancy.execute("CREATE TABLE tenants (id TEXT PRIMARY KEY, display_name TEXT, slug TEXT)")
        tenancy.execute("INSERT INTO tenants VALUES ('tenant-a', 'Leeway Softech', 'leeway')")
        tenancy.commit()
        tenancy.close()

        database.set_audit_request_context(ip_address="203.0.113.9", user_agent="AuditTest/1")
        conn = self._connect()
        event_id = database.record_admin_audit_event(
            conn,
            action="file_uploaded",
            actor={"id": 3, "username": "uploader", "role": "admin", "tenant_id": "tenant-a"},
            tenant_id="tenant-a",
            details={"file_name": "services.pdf", "file_path": "C:\\private\\services.pdf", "source_url": "https://example.test/signed?secret=x"},
        )
        conn.commit()
        row = conn.execute("SELECT ip_address, user_agent, tenant_name, tenant_slug, actor_kind, details_json FROM admin_audit_events WHERE id = ?", (event_id,)).fetchone()
        conn.close()
        database.clear_audit_request_context()
        self.assertEqual(row["ip_address"], "203.0.113.9")
        self.assertEqual(row["user_agent"], "AuditTest/1")
        self.assertEqual(row["tenant_name"], "Leeway Softech")
        self.assertEqual(row["tenant_slug"], "leeway")
        details = json.loads(row["details_json"])
        self.assertEqual(details, {"file_name": "services.pdf"})
        self._insert(action="legacy_sensitive", details={"auth_token_value": "legacy-secret", "visible": "safe"})
        response = self.client.get("/api/admin/audit-history", params={"action": "legacy_sensitive"})
        self.assertNotIn("legacy-secret", response.text)
        self.assertEqual(response.json()["events"][0]["details"], {"visible": "safe"})


if __name__ == "__main__":
    unittest.main()
