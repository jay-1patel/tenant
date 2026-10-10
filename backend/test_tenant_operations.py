"""Isolated tenant-scope regression tests for Customers and Orders."""

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

from fastapi import HTTPException

from routes import tenant_operations
from routes.auth import require_tenant_admin_permission, require_super_admin_permission
from routes.orders import OrderUpdate


class TenantOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "tenant-ops.sqlite3")
        conn = sqlite3.connect(self.db_path)
        conn.executescript(
            """
            CREATE TABLE tenants (id TEXT PRIMARY KEY);
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT UNIQUE NOT NULL,
                wa_id TEXT,
                items TEXT DEFAULT '[]',
                total_amount REAL DEFAULT 0,
                status TEXT DEFAULT 'placed',
                payment_status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                order_type TEXT,
                customer_name TEXT,
                customer_mobile TEXT,
                tenant_id TEXT
            );
            CREATE TABLE complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id TEXT,
                wa_id TEXT,
                status TEXT,
                created_at TEXT,
                tenant_id TEXT
            );
            CREATE TABLE chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wa_id TEXT,
                sender_name TEXT,
                message TEXT,
                response TEXT,
                created_at TEXT,
                tenant_id TEXT
            );
            CREATE TABLE user_states (
                wa_id TEXT PRIMARY KEY,
                updated_at TEXT,
                tenant_id TEXT
            );
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT,
                wa_id TEXT,
                name TEXT,
                phone TEXT,
                email TEXT,
                city TEXT,
                state TEXT,
                company TEXT,
                language TEXT,
                message_count INTEGER DEFAULT 0,
                first_seen TEXT,
                last_seen TEXT,
                UNIQUE (tenant_id, wa_id)
            );
            INSERT INTO tenants (id) VALUES ('tenant-a'), ('tenant-b');
            INSERT INTO orders (order_number, wa_id, items, total_amount, status, created_at,
                                customer_name, customer_mobile, tenant_id)
                VALUES ('A-1', 'shared-wa', '[]', 50, 'placed', '2026-01-01', 'A Name', '111', 'tenant-a'),
                       ('B-1', 'shared-wa', '[]', 900, 'delivered', '2026-02-01', 'B Name', '222', 'tenant-b'),
                       ('OLD-1', 'old-wa', '[]', 12, 'placed', '2026-03-01', 'Legacy', '333', NULL);
            INSERT INTO complaints (ticket_id, wa_id, status, created_at, tenant_id)
                VALUES ('A-C1', 'shared-wa', 'open', '2026-01-02', 'tenant-a'),
                       ('B-C1', 'shared-wa', 'closed', '2026-02-02', 'tenant-b');
            INSERT INTO chat_history (wa_id, sender_name, message, response, created_at, tenant_id)
                VALUES ('shared-wa', 'A Chat Name', 'A message', '', '2026-01-03', 'tenant-a'),
                       ('shared-wa', 'B Chat Name', 'B message', '', '2026-02-03', 'tenant-b');
            INSERT INTO user_states (wa_id, updated_at, tenant_id)
                VALUES ('shared-wa', '2026-02-04', 'tenant-a');
            """
        )
        conn.commit()
        conn.close()
        self.db_patch = patch.object(tenant_operations, "get_db", side_effect=self._connect)
        self.context_patch = patch.object(tenant_operations, "get_db_context", self._db_context)
        self.db_patch.start()
        self.context_patch.start()

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
        finally:
            conn.close()

    @staticmethod
    def _admin(tenant_id, role="admin", **permissions):
        return {
            "username": "operator",
            "role": role,
            "tenant_id": tenant_id,
            "permissions": permissions,
        }

    def test_customers_are_scoped_across_all_sources_and_aggregates(self):
        a = tenant_operations.list_tenant_customers(
            "tenant-a", q="", limit=200, current_admin=self._admin("tenant-a", view_customers=True)
        )
        b = tenant_operations.list_tenant_customers(
            "tenant-b", q="", limit=200, current_admin=self._admin("tenant-b", view_customers=True)
        )

        self.assertEqual(a["count"], 1)
        self.assertEqual(a["customers"][0]["name"], "A Name")
        self.assertEqual(a["customers"][0]["mobile"], "111")
        self.assertEqual(a["customers"][0]["total_orders"], 1)
        self.assertEqual(a["customers"][0]["total_spent"], 50)
        self.assertEqual(a["customers"][0]["total_complaints"], 1)
        self.assertEqual(a["customers"][0]["open_complaints"], 1)

        self.assertEqual(b["count"], 1)
        self.assertEqual(b["customers"][0]["name"], "B Name")
        self.assertEqual(b["customers"][0]["mobile"], "222")
        self.assertEqual(b["customers"][0]["total_orders"], 1)
        self.assertEqual(b["customers"][0]["total_spent"], 900)
        self.assertEqual(b["customers"][0]["total_complaints"], 1)
        self.assertEqual(b["customers"][0]["open_complaints"], 0)

    def test_customer_search_matches_name_mobile_and_wa_id(self):
        by_name = tenant_operations.list_tenant_customers(
            "tenant-a", q="A Name", limit=200, current_admin=self._admin("tenant-a", view_customers=True)
        )
        by_mobile = tenant_operations.list_tenant_customers(
            "tenant-a", q="111", limit=200, current_admin=self._admin("tenant-a", view_customers=True)
        )
        self.assertEqual(by_name["count"], 1)
        self.assertEqual(by_mobile["count"], 1)
        self.assertEqual(
            tenant_operations.list_tenant_customers(
                "tenant-a", q="B Name", limit=200, current_admin=self._admin("tenant-a", view_customers=True)
            )["count"],
            0,
        )

    def test_orders_and_aggregates_exclude_other_and_unowned_rows(self):
        a = tenant_operations.list_tenant_orders(
            "tenant-a", status=None, order_type=None, payment_status=None, q="", limit=200,
            current_admin=self._admin("tenant-a", view_orders=True)
        )
        b = tenant_operations.list_tenant_orders(
            "tenant-b", status=None, order_type=None, payment_status=None, q="", limit=200,
            current_admin=self._admin("tenant-b", view_orders=True)
        )
        self.assertEqual([row["order_number"] for row in a["orders"]], ["A-1"])
        self.assertEqual(a["counts"]["total"], 1)
        self.assertEqual(a["counts"]["revenue"], 50)
        self.assertEqual([row["order_number"] for row in b["orders"]], ["B-1"])
        self.assertEqual(b["counts"]["total"], 1)
        self.assertEqual(b["counts"]["revenue"], 900)
        self.assertEqual(
            tenant_operations.tenant_order_stats(
                "tenant-a", current_admin=self._admin("tenant-a", view_orders=True)
            )["total"],
            1,
        )

    def test_cross_tenant_order_read_update_delete_are_not_found(self):
        admin_a = self._admin("tenant-a", view_orders=True, manage_orders=True)
        with self.assertRaises(HTTPException) as read_error:
            tenant_operations.get_tenant_order("tenant-a", "B-1", current_admin=admin_a)
        self.assertEqual(read_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as update_error:
            tenant_operations.update_tenant_order(
                "tenant-a", "B-1", OrderUpdate(status="cancelled"), current_admin=admin_a
            )
        self.assertEqual(update_error.exception.status_code, 404)
        with self.assertRaises(HTTPException) as delete_error:
            tenant_operations.delete_tenant_order("tenant-a", "B-1", current_admin=admin_a)
        self.assertEqual(delete_error.exception.status_code, 404)

        conn = self._connect()
        row = conn.execute("SELECT status FROM orders WHERE order_number = 'B-1'").fetchone()
        conn.close()
        self.assertEqual(row["status"], "delivered")

    def test_tenant_scope_dependency_rejects_wrong_or_missing_assignment(self):
        dependency = require_tenant_admin_permission("view_orders")
        matching = self._admin("tenant-a", view_orders=True)
        self.assertEqual(dependency(tenant_id="tenant-a", current_admin=matching), matching)
        with self.assertRaises(HTTPException) as wrong_tenant:
            dependency(tenant_id="tenant-b", current_admin=matching)
        self.assertEqual(wrong_tenant.exception.status_code, 403)
        with self.assertRaises(HTTPException) as unassigned:
            dependency(tenant_id="tenant-a", current_admin=self._admin(None, view_orders=True))
        self.assertEqual(unassigned.exception.status_code, 403)
        with self.assertRaises(HTTPException) as missing_permission:
            dependency(tenant_id="tenant-a", current_admin=self._admin("tenant-a"))
        self.assertEqual(missing_permission.exception.status_code, 403)

    def test_only_super_admin_can_use_global_order_dependency(self):
        dependency = require_super_admin_permission("view_orders")
        super_admin = self._admin(None, role="super_admin", view_orders=True)
        self.assertEqual(dependency(current_admin=super_admin), super_admin)
        with self.assertRaises(HTTPException) as denied:
            dependency(current_admin=self._admin("tenant-a", view_orders=True))
        self.assertEqual(denied.exception.status_code, 403)

    def test_new_order_records_explicit_tenant(self):
        order_db = os.path.join(self.temp.name, "order-create.sqlite3")
        conn = sqlite3.connect(order_db)
        conn.executescript(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_number TEXT UNIQUE NOT NULL,
                wa_id TEXT,
                items TEXT DEFAULT '[]',
                total_amount REAL DEFAULT 0,
                status TEXT DEFAULT 'placed',
                payment_status TEXT DEFAULT 'pending',
                source TEXT,
                tier TEXT,
                discount_applied REAL,
                idempotency_key TEXT,
                tenant_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE products (id INTEGER PRIMARY KEY, tenant_id TEXT, name TEXT, stock_quantity INTEGER);
            CREATE TABLE carts (wa_id TEXT);
            CREATE TABLE checkout_sessions (id TEXT, status TEXT, wa_id TEXT, confirmed_order_number TEXT);
            """
        )
        conn.commit()
        conn.close()

        from backend.services import order_service

        def get_order_db():
            db_conn = sqlite3.connect(order_db)
            db_conn.row_factory = sqlite3.Row
            return db_conn

        with patch.object(order_service, "_db", return_value=type("DB", (), {"get_db": staticmethod(get_order_db)})()):
            result = order_service.create_order(
                wa_id="shared-wa",
                items=[{"name": "Service", "qty": 1, "price": 50}],
                tenant_id="tenant-b",
            )
        self.assertTrue(result["ok"])
        conn = sqlite3.connect(order_db)
        row = conn.execute("SELECT tenant_id FROM orders WHERE order_number = ?", (result["order_number"],)).fetchone()
        conn.close()
        self.assertEqual(row[0], "tenant-b")


if __name__ == "__main__":
    unittest.main()
