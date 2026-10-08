"""The draft working copy is a 7-day lease.

Saving a draft refreshes ``updated_at``; publishing (or re-saving) within the
window keeps it alive. A draft nobody published for 7 days is discarded the
next time anything reads it, so the pending view and the publish path treat it
as gone instead of resurrecting stale configuration.
"""

import os
import sqlite3
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


class DraftTtlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "ttl.sqlite3")
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.resolver_patch = patch(
            "shared.tenancy.resolver.resolve_default_tenant", return_value="default"
        )
        self.db_patch.start()
        self.resolver_patch.start()
        database.init_db()
        tenancy_store.ensure_tenant("lease", vertical="generic", display_name="Lease")

    def tearDown(self):
        self.db_patch.stop()
        self.resolver_patch.stop()
        self.temp.cleanup()

    def _exec(self, sql, params=()):
        """Run raw SQL against the test DB, closing the handle (Windows)."""
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def _backdate(self, days):
        """Age the tenant's draft row as if it was saved ``days`` days ago."""
        return self._exec(
            "UPDATE draft_config SET updated_at = datetime('now', ?) WHERE scope = ?",
            (f"-{days} days", tenancy_store.profile_scope("lease")),
        )

    def test_fresh_draft_is_returned(self):
        tenancy_store.save_draft("lease", {"brand": {"name": "Lease"}}, updated_by="t")
        self.assertEqual(tenancy_store.get_draft("lease"), {"brand": {"name": "Lease"}})

    def test_draft_within_seven_days_still_returned(self):
        tenancy_store.save_draft("lease", {"brand": {"name": "Lease"}})
        self.assertEqual(self._backdate(6), 1)
        self.assertEqual(tenancy_store.get_draft("lease"), {"brand": {"name": "Lease"}})

    def test_expired_draft_is_discarded_on_read(self):
        tenancy_store.save_draft("lease", {"brand": {"name": "Lease"}})
        self.assertEqual(self._backdate(8), 1)

        self.assertIsNone(tenancy_store.get_draft("lease"))

        # The row is gone, not just filtered: a re-read stays empty and the
        # next save starts from a clean slate.
        conn = sqlite3.connect(self.db_path)
        try:
            remaining = conn.execute(
                "SELECT COUNT(*) FROM draft_config WHERE scope = ?",
                (tenancy_store.profile_scope("lease"),),
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(remaining, 0)

        tenancy_store.save_draft("lease", {"brand": {"name": "Fresh"}})
        self.assertEqual(tenancy_store.get_draft("lease"), {"brand": {"name": "Fresh"}})

    def test_resaving_extends_the_lease(self):
        tenancy_store.save_draft("lease", {"brand": {"name": "Lease"}})
        self.assertEqual(self._backdate(8), 1)
        # A new save refreshes updated_at, so the draft survives again.
        tenancy_store.save_draft("lease", {"brand": {"name": "Lease 2"}})
        self.assertEqual(tenancy_store.get_draft("lease"), {"brand": {"name": "Lease 2"}})

    def test_other_scopes_do_not_expire(self):
        # The lease applies to tenant profile drafts only; other draft_config
        # scopes keep the legacy never-expire behaviour.
        database.save_draft_config("some_other_scope", {"a": 1}, updated_by="t")
        self._exec(
            "UPDATE draft_config SET updated_at = datetime('now', '-30 days') "
            "WHERE scope = 'some_other_scope'"
        )
        self.assertEqual(database.get_draft_config("some_other_scope"), {"a": 1})


if __name__ == "__main__":
    unittest.main()
