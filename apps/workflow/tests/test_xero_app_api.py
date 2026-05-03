"""Tests for /api/workflow/xero-apps/ — list, create, patch, delete, activate."""

import uuid
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import Staff
from apps.workflow.models import XeroApp


def _row(**overrides):
    defaults = {
        "label": "Primary",
        "client_id": "c-a",
        "client_secret": "s",
        "redirect_uri": "https://example.test/cb",
        "is_active": False,
    }
    defaults.update(overrides)
    return XeroApp.objects.create(**defaults)


def _office_staff(email="office@example.test"):
    return Staff.objects.create_user(
        email=email,
        password="x",
        first_name="Office",
        last_name="Staff",
        is_office_staff=True,
    )


class XeroAppApiPermissionTests(APITestCase):
    def test_anonymous_forbidden_on_list(self):
        response = self.client.get("/api/workflow/xero-apps/")
        self.assertIn(response.status_code, (401, 403))

    def test_anonymous_forbidden_on_create(self):
        response = self.client.post(
            "/api/workflow/xero-apps/",
            {
                "label": "X",
                "client_id": "x",
                "client_secret": "s",
                "redirect_uri": "https://e/cb",
            },
            format="json",
        )
        self.assertIn(response.status_code, (401, 403))

    def test_non_office_staff_forbidden(self):
        worker = Staff.objects.create_user(
            email="worker@example.test",
            password="x",
            first_name="W",
            last_name="X",
            is_office_staff=False,
        )
        client = APIClient()
        client.force_authenticate(user=worker)
        response = client.get("/api/workflow/xero-apps/")
        self.assertEqual(response.status_code, 403)


class XeroAppApiListTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _office_staff()
        self.client.force_authenticate(self.user)

    def test_list_returns_safe_fields_only(self):
        expires = datetime.now(dt_timezone.utc) + timedelta(hours=1)
        _row(
            client_id="c-a",
            is_active=True,
            access_token="SECRET-DO-NOT-LEAK",
            refresh_token="ALSO-SECRET",
            tenant_id="tenant-a",
            expires_at=expires,
            day_remaining=4321,
            minute_remaining=55,
        )
        response = self.client.get("/api/workflow/xero-apps/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(len(body), 1)
        row = body[0]
        # Safe surface fields:
        self.assertEqual(row["label"], "Primary")
        self.assertEqual(row["client_id"], "c-a")
        self.assertTrue(row["is_active"])
        self.assertTrue(row["has_tokens"])
        self.assertEqual(row["tenant_id"], "tenant-a")
        self.assertEqual(row["day_remaining"], 4321)
        self.assertEqual(row["minute_remaining"], 55)
        # Forbidden surface — none of these may appear in the response:
        self.assertNotIn("client_secret", row)
        self.assertNotIn("access_token", row)
        self.assertNotIn("refresh_token", row)


class XeroAppApiCreateTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _office_staff()
        self.client.force_authenticate(self.user)

    def test_create_minimal_row(self):
        payload = {
            "label": "Backup",
            "client_id": "c-b",
            "client_secret": "s-b",
            "redirect_uri": "https://example.test/cb",
        }
        response = self.client.post("/api/workflow/xero-apps/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        row = XeroApp.objects.get(client_id="c-b")
        self.assertEqual(row.label, "Backup")
        self.assertFalse(row.is_active)
        self.assertEqual(row.client_secret, "s-b")

    def test_create_duplicate_client_id_returns_400(self):
        _row(client_id="c-a")
        payload = {
            "label": "Dup",
            "client_id": "c-a",
            "client_secret": "s",
            "redirect_uri": "https://e/cb",
        }
        response = self.client.post("/api/workflow/xero-apps/", payload, format="json")
        self.assertEqual(response.status_code, 400)

    def test_create_without_secret_rejected(self):
        # A row created without client_secret can never complete OAuth —
        # serializer must reject it on create even though secret is
        # write-only and otherwise tolerated as missing.
        payload = {
            "label": "NoSecret",
            "client_id": "c-no-secret",
            "redirect_uri": "https://example.test/cb",
        }
        response = self.client.post("/api/workflow/xero-apps/", payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("client_secret", response.data)
        self.assertFalse(XeroApp.objects.filter(client_id="c-no-secret").exists())

    def test_patch_without_secret_allowed(self):
        # PATCH must NOT require client_secret — the secret is already
        # persisted, and forcing operators to re-supply it on every label
        # tweak would be punitive.
        existing = _row(client_id="c-patch", client_secret="s-original")
        response = self.client.patch(
            f"/api/workflow/xero-apps/{existing.id}/",
            {"label": "RenamedLabel"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        existing.refresh_from_db()
        self.assertEqual(existing.label, "RenamedLabel")
        self.assertEqual(existing.client_secret, "s-original")


class XeroAppApiPatchTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _office_staff()
        self.client.force_authenticate(self.user)

    def test_patch_label_only_does_not_wipe_tokens(self):
        expires = datetime.now(dt_timezone.utc) + timedelta(hours=1)
        row = _row(
            client_id="c-a",
            access_token="aaa",
            refresh_token="rrr",
            tenant_id="t",
            expires_at=expires,
            day_remaining=42,
        )
        response = self.client.patch(
            f"/api/workflow/xero-apps/{row.id}/", {"label": "Renamed"}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.label, "Renamed")
        self.assertEqual(row.access_token, "aaa")
        self.assertEqual(row.refresh_token, "rrr")
        self.assertEqual(row.day_remaining, 42)

    def test_patch_client_id_wipes_tokens_and_quota(self):
        expires = datetime.now(dt_timezone.utc) + timedelta(hours=1)
        row = _row(
            client_id="c-a",
            access_token="aaa",
            refresh_token="rrr",
            tenant_id="t",
            expires_at=expires,
            day_remaining=42,
            minute_remaining=10,
            snapshot_at=datetime.now(dt_timezone.utc),
        )
        response = self.client.patch(
            f"/api/workflow/xero-apps/{row.id}/",
            {"client_id": "c-a-new"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.client_id, "c-a-new")
        self.assertIsNone(row.access_token)
        self.assertIsNone(row.refresh_token)
        self.assertIsNone(row.tenant_id)
        self.assertIsNone(row.day_remaining)
        self.assertIsNone(row.snapshot_at)


class XeroAppApiDeleteTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _office_staff()
        self.client.force_authenticate(self.user)

    def test_delete_inactive_row_succeeds(self):
        row = _row(client_id="c-a", is_active=False)
        response = self.client.delete(f"/api/workflow/xero-apps/{row.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(XeroApp.objects.filter(id=row.id).exists())

    def test_delete_active_row_refused(self):
        row = _row(client_id="c-a", is_active=True)
        response = self.client.delete(f"/api/workflow/xero-apps/{row.id}/")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(XeroApp.objects.filter(id=row.id).exists())


class XeroAppApiActivateTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = _office_staff()
        self.client.force_authenticate(self.user)

    def test_activate_swaps(self):
        a = _row(client_id="c-a", is_active=True)
        b = _row(client_id="c-b", is_active=False)
        response = self.client.post(f"/api/workflow/xero-apps/{b.id}/activate/")
        self.assertEqual(response.status_code, 200)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertFalse(a.is_active)
        self.assertTrue(b.is_active)

    def test_activate_unknown_id_404(self):
        response = self.client.post(f"/api/workflow/xero-apps/{uuid.uuid4()}/activate/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
