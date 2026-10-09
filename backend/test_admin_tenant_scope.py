"""Tenant isolation tests for the Team & Manage admin APIs."""

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
from fastapi import HTTPException
from routes import auth


class AdminTenantScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(database, "DB_PATH", os.path.join(self.temp.name, "admins.sqlite3"))
        self.db_patch.start()
        database.init_db()
        self._create_admin("admin-a", "admin", "tenant-a")
        self._create_admin("sub-a", "sub_admin", "tenant-a")
        self._create_admin("admin-b", "admin", "tenant-b")
        self._create_admin("sub-b", "sub_admin", "tenant-b")

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    @staticmethod
    def _admin(username, role, tenant_id):
        return {
            "username": username,
            "role": role,
            "tenant_id": tenant_id,
            "permissions": {"manage_admins": True},
        }

    def _create_admin(self, username, role, tenant_id):
        return database.create_admin(
            username=username,
            password_hash=f"hash-{username}",
            role=role,
            permissions={"manage_admins": True},
            tenant_id=tenant_id,
        )

    def test_tenant_admin_list_is_scoped_and_unassigned_fails_closed(self):
        listed = auth.list_admins(current_admin=self._admin("admin-a", "admin", "tenant-a"))
        self.assertEqual({row["username"] for row in listed["admins"]}, {"admin-a", "sub-a"})
        self.assertEqual(
            auth.list_admins(current_admin=self._admin("root", "admin", None))["admins"],
            [],
        )

    def test_tenant_admin_cannot_update_delete_or_reset_other_tenant(self):
        actor = self._admin("admin-a", "admin", "tenant-a")
        with self.assertRaises(HTTPException) as update_error:
            auth.update_admin("sub-b", auth.UpdateAdminRequest(email="changed@example.test"), actor)
        self.assertEqual(update_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as delete_error:
            auth.delete_admin_endpoint("sub-b", actor)
        self.assertEqual(delete_error.exception.status_code, 404)

        with self.assertRaises(HTTPException) as reset_error:
            auth.reset_admin_password("sub-b", auth.ResetAdminPasswordRequest(new_password="test-password"), actor)
        self.assertEqual(reset_error.exception.status_code, 404)

        self.assertEqual(database.get_admin_record("sub-b")["password_hash"], "hash-sub-b")
        self.assertIsNone(database.get_admin_record("sub-b")["email"])

    def test_same_tenant_management_and_super_admin_global_access(self):
        actor = self._admin("admin-a", "admin", "tenant-a")
        updated = auth.update_admin("sub-a", auth.UpdateAdminRequest(email="new@example.test"), actor)
        self.assertEqual(updated["username"], "sub-a")
        self.assertEqual(database.get_admin_record("sub-a")["email"], "new@example.test")

        root = self._admin("root", "super_admin", None)
        self.assertEqual(
            {row["username"] for row in auth.list_admins(current_admin=root)["admins"]},
            {"admin-a", "sub-a", "admin-b", "sub-b"},
        )
        auth.update_admin("sub-b", auth.UpdateAdminRequest(email="root@example.test"), root)
        self.assertEqual(database.get_admin_record("sub-b")["email"], "root@example.test")


if __name__ == "__main__":
    unittest.main()
