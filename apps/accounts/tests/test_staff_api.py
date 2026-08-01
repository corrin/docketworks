import datetime
import io
import os
import tempfile
from typing import Any, ClassVar

from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext, override_settings
from PIL import Image
from rest_framework.response import Response
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.testing import BaseTestCase


def _png_bytes(size: int = 8) -> bytes:
    """Build a real PNG so ImageField validation has something to accept."""
    buffer = io.BytesIO()
    Image.new("RGB", (size, size), color="red").save(buffer, format="PNG")
    return buffer.getvalue()


class StaffListCreateAPIViewTests(BaseTestCase):
    def test_staff_list_prefetches_groups_for_serializer(self) -> None:
        office_user = Staff.objects.create_user(
            email="office@example.test",
            password="testpass",
            first_name="Office",
            last_name="User",
            is_office_staff=True,
        )
        group = Group.objects.create(name="Workshop Team")
        first = Staff.objects.create_user(
            email="first@example.test",
            password="testpass",
            first_name="First",
            last_name="Person",
        )
        second = Staff.objects.create_user(
            email="second@example.test",
            password="testpass",
            first_name="Second",
            last_name="Person",
        )
        first.groups.add(group)
        second.groups.add(group)

        client = APIClient()
        client.force_authenticate(user=office_user)

        with CaptureQueriesContext(connection) as captured:
            response = client.get("/api/accounts/staff/")

        self.assertEqual(response.status_code, 200)
        by_email = {row["email"]: row for row in response.json()}
        self.assertEqual(by_email["first@example.test"]["groups"], [group.id])
        self.assertEqual(by_email["second@example.test"]["groups"], [group.id])

        group_queries = [
            query["sql"]
            for query in captured
            if "auth_group" in query["sql"].lower()
            and "accounts_staff_groups" in query["sql"].lower()
        ]
        self.assertEqual(len(group_queries), 1)


class StaffDetailAPIViewTests(BaseTestCase):
    def test_staff_cannot_be_deleted_via_api(self) -> None:
        """Staff are offboarded by setting date_left, never deleted. The detail
        endpoint must reject DELETE so a hard delete (which would orphan or be
        blocked by protected time entries) can't be reintroduced."""
        office_user = Staff.objects.create_user(
            email="office@example.test",
            password="testpass",
            first_name="Office",
            last_name="User",
            is_office_staff=True,
        )
        target = Staff.objects.create_user(
            email="leaver@example.test",
            password="testpass",
            first_name="Depa",
            last_name="Rting",
        )

        client = APIClient()
        client.force_authenticate(user=office_user)

        response = client.delete(f"/api/accounts/staff/{target.id}/")

        self.assertEqual(response.status_code, 405)


class StaffJSONContractTests(BaseTestCase):
    """The staff resource is JSON-only.

    These pin the shapes the admin staff form actually sends. They exist
    because the endpoints previously accepted only multipart, which cannot
    express null, numbers, or arrays — every value arrived as a string and a
    serializer mixin hand-rebuilt the types. A blank Date Left was serialised
    as the literal text "null" and rejected, breaking staff create and edit.
    """

    def setUp(self) -> None:
        super().setUp()
        self.admin = Staff.objects.create_user(
            email="admin@example.test",
            password="testpass",
            first_name="Admin",
            last_name="User",
            is_office_staff=True,
        )
        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.admin)

    def test_create_leaves_a_new_staff_member_active(self) -> None:
        """A new staff member has no leaving date, so they are current."""
        response = self.client_api.post(
            "/api/accounts/staff/",
            {
                "email": "newstarter@example.test",
                "first_name": "New",
                "last_name": "Starter",
                "password": "TestPassword123!",
                "base_wage_rate": 32.5,
                "date_left": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        created = Staff.objects.get(email="newstarter@example.test")
        self.assertIsNone(created.date_left)
        self.assertTrue(created.is_currently_active)

    def test_create_ignores_a_client_supplied_last_login(self) -> None:
        """`last_login` is not part of the write contract.

        Authentication is JWT-only and nothing ever stamps the inherited
        `AbstractBaseUser` column, so an API client must not be able to forge a
        login time. The create serializer once listed only `wage_rate` as
        read-only, which let this value through.
        """
        response = self.client_api.post(
            "/api/accounts/staff/",
            {
                "email": "forger@example.test",
                "first_name": "For",
                "last_name": "Ger",
                "password": "TestPassword123!",
                "base_wage_rate": 32.5,
                "date_left": None,
                "last_login": "2026-07-01T09:00:00Z",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertNotIn("last_login", response.json())
        created = Staff.objects.get(email="forger@example.test")
        self.assertIsNone(created.last_login)

    def test_setting_date_left_offboards_a_staff_member(self) -> None:
        target = Staff.objects.create_user(
            email="leaving@example.test",
            password="testpass",
            first_name="Going",
            last_name="Away",
        )

        response = self.client_api.patch(
            f"/api/accounts/staff/{target.id}/",
            {"date_left": "2026-07-01"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        target.refresh_from_db()
        self.assertEqual(target.date_left, datetime.date(2026, 7, 1))

    def test_clearing_date_left_reinstates_an_offboarded_staff_member(self) -> None:
        """Clearing the Date Left field brings someone back onto the books.

        This is why date_left is always sent rather than omitted — omitting a
        field cannot clear it on a PATCH.
        """
        target = Staff.objects.create_user(
            email="returning@example.test",
            password="testpass",
            first_name="Back",
            last_name="Again",
        )
        target.date_left = datetime.date(2026, 1, 31)
        target.save(update_fields=["date_left"])

        response = self.client_api.patch(
            f"/api/accounts/staff/{target.id}/",
            {"date_left": None},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        target.refresh_from_db()
        self.assertIsNone(target.date_left)
        self.assertTrue(target.is_currently_active)

    def test_groups_round_trip_as_a_json_array(self) -> None:
        """Permissions arrive as a real array, not a comma-joined string."""
        group = Group.objects.create(name="Estimators")
        target = Staff.objects.create_user(
            email="grouped@example.test",
            password="testpass",
            first_name="Group",
            last_name="Member",
        )

        response = self.client_api.patch(
            f"/api/accounts/staff/{target.id}/",
            {"groups": [group.id]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(list(target.groups.values_list("id", flat=True)), [group.id])

    def test_empty_groups_array_clears_membership(self) -> None:
        group = Group.objects.create(name="Temporary")
        target = Staff.objects.create_user(
            email="ungrouped@example.test",
            password="testpass",
            first_name="No",
            last_name="Groups",
        )
        target.groups.add(group)

        response = self.client_api.patch(
            f"/api/accounts/staff/{target.id}/",
            {"groups": []},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(list(target.groups.all()), [])


class StaffIconAPIViewTests(BaseTestCase):
    """Profile pictures upload through their own endpoint.

    The staff resource is JSON, which cannot carry a file, so the icon has a
    dedicated multipart endpoint — the same split already used for company
    logos and job files.

    MEDIA_ROOT is redirected to a temporary directory: these tests write real
    files, and the default root is the developer's own mediafiles/ tree.
    """

    _media: ClassVar[tempfile.TemporaryDirectory]  # type: ignore[type-arg]  # py3.12 stub is ungeneric
    _media_override: ClassVar[Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls._media = tempfile.TemporaryDirectory(prefix="staff-icons-test-")
        cls._media_override = override_settings(MEDIA_ROOT=cls._media.name)
        # Enabled before super() so the base fixture copying also lands in the
        # temporary tree rather than the real one.
        cls._media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls._media_override.disable()
        cls._media.cleanup()

    def setUp(self) -> None:
        super().setUp()
        self.admin = Staff.objects.create_user(
            email="iconadmin@example.test",
            password="testpass",
            first_name="Icon",
            last_name="Admin",
            is_office_staff=True,
        )
        self.target = Staff.objects.create_user(
            email="photographed@example.test",
            password="testpass",
            first_name="Photo",
            last_name="Subject",
        )
        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.admin)

    def _upload(self, upload: SimpleUploadedFile, staff_id: object = None) -> Response:
        return self.client_api.post(
            f"/api/accounts/staff/{staff_id or self.target.id}/icon/",
            {"file": upload},
            format="multipart",
        )

    def test_upload_sets_the_icon_and_returns_its_url(self) -> None:
        response = self._upload(
            SimpleUploadedFile("face.png", _png_bytes(), content_type="image/png")
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.target.refresh_from_db()
        self.assertTrue(self.target.icon)

        # Relative on purpose: the browser resolves it against its own origin.
        # An absolute URL built from the request would embed the internal host
        # and be blocked as a cross-origin request wherever the app is proxied.
        icon_url = response.data["icon_url"]
        self.assertTrue(icon_url.startswith("/"), icon_url)

    def test_replacing_an_icon_removes_the_previous_file(self) -> None:
        """Repeated uploads must not leave orphaned images on disk."""
        self._upload(
            SimpleUploadedFile("first.png", _png_bytes(), content_type="image/png")
        )
        self.target.refresh_from_db()
        first_path = self.target.icon.path
        self.assertTrue(os.path.exists(first_path))

        self._upload(
            SimpleUploadedFile("second.png", _png_bytes(16), content_type="image/png")
        )
        self.target.refresh_from_db()

        self.assertNotEqual(self.target.icon.path, first_path)
        self.assertFalse(os.path.exists(first_path))
        self.assertTrue(os.path.exists(self.target.icon.path))

    def test_upload_rejects_a_non_image_extension(self) -> None:
        response = self._upload(
            SimpleUploadedFile("resume.txt", b"not an image", content_type="text/plain")
        )

        self.assertEqual(response.status_code, 400)
        self.target.refresh_from_db()
        self.assertFalse(self.target.icon)

    def test_upload_rejects_a_file_over_the_size_limit(self) -> None:
        oversized = SimpleUploadedFile(
            "huge.png", b"x" * (5 * 1024 * 1024 + 1), content_type="image/png"
        )

        response = self._upload(oversized)

        self.assertEqual(response.status_code, 400)

    def test_upload_requires_a_file(self) -> None:
        response = self.client_api.post(
            f"/api/accounts/staff/{self.target.id}/icon/", {}, format="multipart"
        )

        self.assertEqual(response.status_code, 400)

    def test_removing_a_picture_clears_it_and_deletes_the_file(self) -> None:
        """Removing a photo must not leave the image behind on disk."""
        self._upload(
            SimpleUploadedFile("face.png", _png_bytes(), content_type="image/png")
        )
        self.target.refresh_from_db()
        path = self.target.icon.path
        self.assertTrue(os.path.exists(path))

        response = self.client_api.delete(f"/api/accounts/staff/{self.target.id}/icon/")

        self.assertEqual(response.status_code, 200, response.content)
        self.target.refresh_from_db()
        self.assertFalse(self.target.icon)
        self.assertFalse(os.path.exists(path))
        self.assertIsNone(response.data["icon_url"])

    def test_removing_an_absent_picture_succeeds(self) -> None:
        """Idempotent: the requested end state (no photo) already holds."""
        response = self.client_api.delete(f"/api/accounts/staff/{self.target.id}/icon/")

        self.assertEqual(response.status_code, 200, response.content)
        self.target.refresh_from_db()
        self.assertFalse(self.target.icon)

    def test_removing_a_picture_for_an_unknown_staff_member_is_not_found(self) -> None:
        response = self.client_api.delete(
            "/api/accounts/staff/00000000-0000-0000-0000-000000000000/icon/"
        )

        self.assertEqual(response.status_code, 404)

    def test_upload_to_an_unknown_staff_member_is_not_found(self) -> None:
        response = self._upload(
            SimpleUploadedFile("face.png", _png_bytes(), content_type="image/png"),
            staff_id="00000000-0000-0000-0000-000000000000",
        )

        self.assertEqual(response.status_code, 404)
