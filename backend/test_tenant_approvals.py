"""Coverage for tenant change requests and the superadmin approval flow.

Admins can prepare tenant registrations and profile publishes, but the
endpoints refuse to apply them directly; everything lands in the
``tenant_change_requests`` queue and only a super admin decision applies it.
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
from routes import tenant_approvals
from routes import tenants as tenants_routes
from shared.tenancy import store as tenancy_store

PASSWORD = "RootPass123!"


class TenantApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp.name, "approvals.sqlite3")
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.resolver_patch = patch(
            "shared.tenancy.resolver.resolve_default_tenant", return_value="default"
        )
        self.db_patch.start()
        self.resolver_patch.start()
        database.init_db()

        self.app = FastAPI()
        if auth_routes.RATE_LIMIT_ENABLED:
            self.app.state.limiter = auth_routes.limiter
        self.app.include_router(auth_routes.router)
        self.app.include_router(tenants_routes.router)
        self.app.include_router(tenant_approvals.router)
        self.client = TestClient(self.app)

        first = self.client.post(
            "/api/auth/first-admin", json={"username": "root", "password": PASSWORD}
        )
        assert first.status_code == 200, first.text

    def tearDown(self):
        self.db_patch.stop()
        self.resolver_patch.stop()
        self.temp.cleanup()

    # ── helpers ────────────────────────────────────────────────────────

    def _login(self, username):
        res = self.client.post(
            "/api/auth/login", json={"username": username, "password": PASSWORD}
        )
        assert res.status_code == 200, res.text
        return {"Authorization": f"Bearer {res.json()['token']}"}

    def _create_admin(self, username, role="admin", tenant_id=None):
        # Mirrors the Team screen's payload: explicit nulls for permissions
        # (admins get the server default), email and unused tenant scope.
        payload = {
            "username": username,
            "password": PASSWORD,
            "role": role,
            "permissions": None,
            "email": None,
            "tenant_id": tenant_id,
        }
        res = self.client.post(
            "/api/auth/create",
            json=payload,
            headers=self._login("root"),
        )
        assert res.status_code == 200, res.text
        return self._login(username)

    def _submit_create(self, headers, tenant_id="acme", **extra):
        return self.client.post(
            "/api/tenant-change-requests",
            json={
                "request_type": "create_tenant",
                "tenant_id": tenant_id,
                "tenant": {
                    "slug": tenant_id,
                    "vertical": "generic",
                    "display_name": "Acme Ltd",
                    "waba_phone_id": "",
                    "status": "active",
                },
                "snapshot": {},
                **extra,
            },
            headers=headers,
        )

    def _submit_publish(self, headers, tenant_id):
        return self.client.post(
            "/api/tenant-change-requests",
            json={"request_type": "publish_profile", "tenant_id": tenant_id},
            headers=headers,
        )

    def _decide(self, request_id, decision, note=""):
        return self.client.post(
            f"/api/admin/tenant-change-requests/{request_id}/decision",
            json={"decision": decision, "note": note},
            headers=self._login("root"),
        )

    def _current_version(self, tenant_id):
        res = self.client.get("/api/admin/tenants", headers=self._login("root"))
        for row in res.json()["tenants"]:
            if row["id"] == tenant_id:
                return row["current_version"]
        return None

    # ── registration flow ──────────────────────────────────────────────

    def test_admin_cannot_create_tenants_or_publish_directly(self):
        # Registering a tenant is the super admin's step; the approval queue
        # exists for the wizard the admin completes afterwards.
        admin = self._create_admin("plain-admin")
        blocked = self.client.post(
            "/api/admin/tenants",
            json={"tenant_id": "acme", "vertical": "generic"},
            headers=admin,
        )
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("super admin approval", blocked.json()["detail"])

        # The super admin still creates tenants directly.
        direct = self.client.post(
            "/api/admin/tenants",
            json={"tenant_id": "acme", "vertical": "generic"},
            headers=self._login("root"),
        )
        self.assertEqual(direct.status_code, 200)

        # An admin's profile edit never goes live directly either: the publish
        # endpoint queues it for super admin approval, like a registration.
        # A draft missing the compulsory contact fields is refused outright.
        tenancy_store.save_draft("acme", {})
        res = self.client.post("/api/admin/tenants/acme/publish", headers=admin)
        self.assertEqual(res.status_code, 422)
        self.assertIn("Missing required profile fields", res.json()["detail"])

        tenancy_store.save_draft(
            "acme",
            {"brand": {"support_email": "care@acme.example", "support_phone": "+91 98765 43210"}},
        )
        res = self.client.post("/api/admin/tenants/acme/publish", headers=admin)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "pending_approval")
        self.assertEqual(body["request"]["status"], "pending")
        self.assertEqual(self._current_version("acme"), 0)

        # Only the super admin's approval makes it live.
        approved = self._decide(body["request"]["id"], "approved", "Ship it")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(self._current_version("acme"), 1)

        # The super admin still publishes directly.
        tenancy_store.save_draft(
            "acme",
            {"brand": {"support_email": "care@acme.example", "support_phone": "+91 98765 43210"}},
        )
        direct_pub = self.client.post(
            "/api/admin/tenants/acme/publish", headers=self._login("root")
        )
        self.assertEqual(direct_pub.status_code, 200)
        self.assertIn("version", direct_pub.json())
        self.assertEqual(self._current_version("acme"), 2)

    # ── contact-detail validation ───────────────────────────────

    def test_registration_rejects_invalid_contact_details(self):
        admin = self._create_admin("contact-admin")
        # Phone without a country code.
        res = self._submit_create(
            admin, snapshot={"brand": {"support_phone": "9876543210"}}
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("country code", res.json()["detail"])
        # Website that is not a URL.
        res = self._submit_create(
            admin, snapshot={"brand": {"website": "not a website"}}
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("website URL", res.json()["detail"])
        # Email that is not an email.
        res = self._submit_create(
            admin, snapshot={"notifications": {"sales_email": "nope"}}
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("email address", res.json()["detail"])
        # waba_phone_id must be digits only.
        res = self.client.post(
            "/api/tenant-change-requests",
            json={
                "request_type": "create_tenant",
                "tenant_id": "acme",
                "tenant": {
                    "slug": "acme",
                    "vertical": "generic",
                    "display_name": "Acme Ltd",
                    "waba_phone_id": "12345",
                    "status": "active",
                },
            },
            headers=admin,
        )
        self.assertEqual(res.status_code, 422)
        self.assertIn("10-16 digits", res.json()["detail"])
        # Valid contact details queue fine.
        res = self._submit_create(
            admin,
            snapshot={
                "brand": {
                    "website": "https://acme.example",
                    "support_email": "care@acme.example",
                    "support_phone": "+91 98765 43210",
                }
            },
        )
        self.assertEqual(res.status_code, 201)

    def test_profile_rejects_invalid_contact_details(self):
        admin = self._create_admin("profile-admin")
        self.client.post(
            "/api/admin/tenants",
            json={"tenant_id": "acme", "vertical": "generic"},
            headers=self._login("root"),
        )
        # Saving a broken draft is allowed; the problem comes back as a
        # validation warning.
        res = self.client.put(
            "/api/admin/tenants/acme/profile",
            json={"snapshot": {"brand": {"website": "not a url"}}},
            headers=admin,
        )
        self.assertEqual(res.status_code, 200)
        self.assertTrue(any("website URL" in w for w in res.json()["validation"]))
        # A publish of that draft is refused outright instead of queueing.
        res = self.client.post("/api/admin/tenants/acme/publish", headers=admin)
        self.assertEqual(res.status_code, 422)
        # Fix the contact details and the publish queues for approval.
        res = self.client.put(
            "/api/admin/tenants/acme/profile",
            json={
                "snapshot": {
                    "brand": {
                        "website": "https://acme.example",
                        "support_email": "care@acme.example",
                        "support_phone": "+91 98765 43210",
                    }
                }
            },
            headers=admin,
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["validation"], [])
        res = self.client.post("/api/admin/tenants/acme/publish", headers=admin)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["status"], "pending_approval")

    def test_registration_submission_and_approval(self):
        admin = self._create_admin("reg-admin")
        created = self._submit_create(admin)
        self.assertEqual(created.status_code, 201)
        request = created.json()["request"]
        self.assertEqual(request["status"], "pending")
        self.assertEqual(request["tenant_id"], "acme")
        self.assertIsNone(tenancy_store.get_tenant("acme"))

        # One pending registration per tenant id.
        self.assertEqual(self._submit_create(admin).status_code, 409)

        # The admin sees their own submission.
        mine = self.client.get("/api/tenant-change-requests", headers=admin)
        self.assertEqual([r["id"] for r in mine.json()["requests"]], [request["id"]])

        # Super admins do not submit, they decide.
        self.assertEqual(self._submit_create(self._login("root")).status_code, 403)
        self.assertEqual(
            self.client.get(
                "/api/admin/tenant-change-requests", headers=admin
            ).status_code,
            403,
        )

        queue = self.client.get(
            "/api/admin/tenant-change-requests", headers=self._login("root")
        ).json()["requests"]
        self.assertEqual(len(queue), 1)

        approved = self._decide(request["id"], "approved", "Go ahead")
        self.assertEqual(approved.status_code, 200)
        body = approved.json()
        self.assertEqual(body["request"]["status"], "approved")
        self.assertEqual(body["request"]["applied_version"], 1)
        self.assertIsNotNone(tenancy_store.get_tenant("acme"))
        self.assertEqual(self._current_version("acme"), 1)

        events = self.client.get(
            f"/api/admin/tenant-change-requests/{request['id']}/events",
            headers=self._login("root"),
        ).json()["events"]
        self.assertEqual([e["event_type"] for e in events], ["submitted", "decision"])

        # A decided request cannot be decided twice.
        self.assertEqual(self._decide(request["id"], "rejected").status_code, 409)

    def test_registration_approval_conflict_when_tenant_appeared(self):
        admin = self._create_admin("reg-admin-2")
        created = self._submit_create(admin, tenant_id="acme")
        request_id = created.json()["request"]["id"]

        # Someone (a super admin) registers the same id before review.
        self.client.post(
            "/api/admin/tenants",
            json={"tenant_id": "acme", "vertical": "generic"},
            headers=self._login("root"),
        )
        conflict = self._decide(request_id, "approved")
        self.assertEqual(conflict.status_code, 409)
        # The request stays pending so the super admin can reject it instead.
        row = self.client.get(
            "/api/admin/tenant-change-requests", headers=self._login("root")
        ).json()["requests"][0]
        self.assertEqual(row["status"], "pending")

    def test_registration_rejection_creates_nothing(self):
        admin = self._create_admin("reg-admin-3")
        created = self._submit_create(admin, tenant_id="ghost")
        request_id = created.json()["request"]["id"]

        rejected = self._decide(request_id, "rejected", "Not now")
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(rejected.json()["request"]["status"], "rejected")
        self.assertIsNone(tenancy_store.get_tenant("ghost"))

        # After a rejection a fresh request can be submitted.
        self.assertEqual(self._submit_create(admin, tenant_id="ghost").status_code, 201)

    # ── publish flow ────────────────────────────────────────────────────

    def _register_tenant(self, tenant_id="acme"):
        res = self.client.post(
            "/api/admin/tenants",
            json={"tenant_id": tenant_id, "vertical": "generic"},
            headers=self._login("root"),
        )
        assert res.status_code == 200, res.text

    def test_publish_submission_requires_tenant_and_draft(self):
        admin = self._create_admin("pub-admin")
        self.assertEqual(self._submit_publish(admin, "nope").status_code, 404)

        self._register_tenant()
        self.assertEqual(self._submit_publish(admin, "acme").status_code, 400)

        tenancy_store.save_draft(
            "acme",
            {"brand": {"name": "Acme", "support_email": "care@acme.example", "support_phone": "+91 98765 43210"}},
        )
        submitted = self._submit_publish(admin, "acme")
        self.assertEqual(submitted.status_code, 201)
        self.assertEqual(submitted.json()["request"]["status"], "pending")
        self.assertEqual(self._submit_publish(admin, "acme").status_code, 409)

    def test_publish_is_tenant_scoped_and_applies_submitted_snapshot(self):
        self._register_tenant("acme")
        tenancy_store.save_draft(
            "acme",
            {"brand": {"name": "Acme", "support_email": "care@acme.example", "support_phone": "+91 98765 43210"}},
        )

        # One admin per company: the cross-tenant scoping check uses a
        # sub admin, since a second admin for acme is rejected.
        other = self._create_admin("other-sub", role="sub_admin", tenant_id="acme")
        self._register_tenant("rival")
        self.assertEqual(self._submit_publish(other, "rival").status_code, 403)

        scoped = self._create_admin("scoped-admin", tenant_id="acme")
        created = self._submit_publish(scoped, "acme")
        self.assertEqual(created.status_code, 201)
        request_id = created.json()["request"]["id"]

        # The draft keeps moving after submission; approval applies the
        # snapshot captured at submission time, not the newer one.
        tenancy_store.save_draft("acme", {"brand": {"name": "Moved On"}})

        approved = self._decide(request_id, "approved")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(self._current_version("acme"), 1)

        from shared.tenancy.loader import get_tenant_profile

        profile = get_tenant_profile("acme")
        self.assertEqual(profile.brand.name, "Acme")

    # ── the split registration flow ─────────────────────────────────────

    def test_superadmin_registers_company_admin_completes_for_approval(self):
        """Super admin registers only the company; the admin adds the rest and
        the super admin's approval makes it live — the flow the wizard drives."""
        # 1. Super admin creates the tenant with the company basics only.
        created = self.client.post(
            "/api/admin/tenants",
            json={"tenant_id": "acme", "vertical": "generic", "display_name": "Acme Ltd"},
            headers=self._login("root"),
        )
        self.assertEqual(created.status_code, 200)
        self.assertEqual(self._current_version("acme"), 0)

        # 2. Admin fills WhatsApp onwards: binds the phone, saves the draft.
        admin = self._create_admin("completer")
        snapshot = {
            "display_name": "Acme Ltd",
            "brand": {
                "name": "Acme Ltd",
                "bot_name": "Asha",
                "support_email": "care@acme.example",
                "support_phone": "+91 98765 43210",
            },
            "business_hours": {"timezone": "Asia/Kolkata", "always_open": True},
        }
        bound = self.client.post(
            "/api/admin/tenants/acme/phone-id",
            json={"waba_phone_id": "100012345678901"},
            headers=admin,
        )
        self.assertEqual(bound.status_code, 200)
        saved = self.client.put(
            "/api/admin/tenants/acme/profile",
            json={"snapshot": snapshot},
            headers=admin,
        )
        self.assertEqual(saved.status_code, 200)

        # 3. Admin queues the publish; nothing is live yet.
        submitted = self._submit_publish(admin, "acme")
        self.assertEqual(submitted.status_code, 201)
        self.assertEqual(self._current_version("acme"), 0)

        # 4. Super admin sees everything the admin added, then approves.
        queue = self.client.get(
            "/api/admin/tenant-change-requests", headers=self._login("root")
        ).json()["requests"]
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]["payload"]["snapshot"]["brand"]["bot_name"], "Asha")
        # The review queue carries the tenant registry data too, so the
        # reviewer sees the phone the admin bound, not just the profile.
        self.assertEqual(queue[0]["tenant_display_name"], "Acme Ltd")
        self.assertEqual(queue[0]["tenant_vertical"], "generic")
        self.assertEqual(queue[0]["tenant_waba_phone_id"], "100012345678901")

        request_id = queue[0]["id"]
        approved = self._decide(request_id, "approved")
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(self._current_version("acme"), 1)

        from shared.tenancy.loader import get_tenant_profile

        profile = get_tenant_profile("acme")
        self.assertEqual(profile.brand.bot_name, "Asha")

        # The registry picked up the admin's phone binding too.
        tenant_row = tenancy_store.get_tenant("acme")
        self.assertEqual(tenant_row["waba_phone_id"], "100012345678901")

    def test_publish_rejection_keeps_live_version(self):
        self._register_tenant("acme")
        tenancy_store.save_draft(
            "acme",
            {"brand": {"name": "Acme", "support_email": "care@acme.example", "support_phone": "+91 98765 43210"}},
        )

        # Publish once so the tenant has a live version.
        self.client.post("/api/admin/tenants/acme/publish", headers=self._login("root"))
        self.assertEqual(self._current_version("acme"), 1)

        tenancy_store.save_draft(
            "acme",
            {"brand": {"name": "Changed", "support_email": "care@acme.example", "support_phone": "+91 98765 43210"}},
        )
        scoped = self._create_admin("scoped-admin-2", tenant_id="acme")
        request_id = self._submit_publish(scoped, "acme").json()["request"]["id"]

        rejected = self._decide(request_id, "rejected")
        self.assertEqual(rejected.status_code, 200)
        self.assertEqual(self._current_version("acme"), 1)

        from shared.tenancy.loader import get_tenant_profile

        self.assertEqual(get_tenant_profile("acme").brand.name, "Acme")


if __name__ == "__main__":
    unittest.main()
