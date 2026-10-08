"""Tenant mutation audit attribution and transaction coverage."""

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

import database
from routes import tenants


class TenantAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "tenant-audit.sqlite3")
        self.tenant_db_patch = patch.object(tenants.tenancy_store._db(), "DB_PATH", self.db_path)
        self.tenant_db_patch.start()
        conn = self._connect()
        conn.executescript(
            """
            CREATE TABLE tenants (
                id TEXT PRIMARY KEY,
                slug TEXT,
                waba_phone_id TEXT,
                vertical TEXT,
                status TEXT,
                display_name TEXT,
                webhook_secret TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE tenant_profile_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                published_by TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_current INTEGER DEFAULT 0,
                UNIQUE(tenant_id, version)
            );
            CREATE TABLE draft_config (
                scope TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                updated_by TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE published_config (
                scope TEXT PRIMARY KEY,
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                published_by TEXT DEFAULT '',
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE publish_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scope TEXT NOT NULL,
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                published_by TEXT DEFAULT '',
                published_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE tenant_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                label TEXT DEFAULT '',
                created_by TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                revoked_at TIMESTAMP
            );
            """
        )
        database._init_admin_audit_tables(conn)
        conn.commit()
        conn.close()
        self.db_patch = patch.object(database, "get_db_context", self._db_context)
        self.db_patch.start()
        self.admin = {"id": 1, "username": "root", "role": "super_admin", "tenant_id": None}

    def tearDown(self):
        self.db_patch.stop()
        self.tenant_db_patch.stop()
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

    def test_tenant_creation_records_actor_and_tenant(self):
        body = tenants.TenantCreate(tenant_id="tenant-new", slug="new", vertical="generic", display_name="New")
        with patch.object(tenants.tenancy_cache, "purge"), patch("shared.tenancy.loader.build_profile", return_value={}):
            result = tenants.create_tenant(body, current_admin=self.admin)
        self.assertEqual(result["tenant"]["id"], "tenant-new")
        conn = self._connect()
        row = conn.execute("SELECT actor_username, actor_role, tenant_id, action FROM admin_audit_events").fetchone()
        conn.close()
        self.assertEqual(tuple(row), ("root", "super_admin", "tenant-new", "tenant_created"))

    def test_tenant_creation_rolls_back_if_audit_insert_fails(self):
        body = tenants.TenantCreate(tenant_id="tenant-new", slug="new", vertical="generic", display_name="New")
        with patch.object(tenants.tenancy_cache, "purge"), \
             patch("shared.tenancy.loader.build_profile", return_value={}), \
             patch.object(tenants, "record_admin_audit_event", side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError):
                tenants.create_tenant(body, current_admin=self.admin)
        conn = self._connect()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0], 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
