"""Tests for /api/workflow/notebook-lm-links/ — menu filtering + CRUD permissions."""

from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import Staff
from apps.workflow.enums import NotebookLmRestriction
from apps.workflow.models import NotebookLmLink

LIST_URL = "/api/workflow/notebook-lm-links/"
MENU_URL = "/api/workflow/notebook-lm-links/menu/"


def _staff(email: str, *, office: bool = False, superuser: bool = False) -> Staff:
    return Staff.objects.create_user(
        email=email,
        password="x",
        first_name="Test",
        last_name="User",
        is_office_staff=office,
        is_superuser=superuser,
    )


def _link(
    name: str,
    *,
    enabled: bool = True,
    restriction: str = NotebookLmRestriction.NONE,
    order: int = 0,
) -> NotebookLmLink:
    return NotebookLmLink.objects.create(
        name=name,
        url=f"https://nb.test/{name}",
        enabled=enabled,
        restriction=restriction,
        order=order,
    )


class NotebookLmMenuTests(APITestCase):
    def setUp(self) -> None:
        _link("Training", order=1)
        _link("HS", order=2)
        _link("Admin", restriction=NotebookLmRestriction.SUPERUSER, order=3)
        _link("Disabled", enabled=False, order=0)

    def test_menu_hides_restricted_and_disabled_for_regular_staff(self) -> None:
        client = APIClient()
        client.force_authenticate(_staff("worker@example.test"))
        resp = client.get(MENU_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in resp.json()]
        self.assertEqual(names, ["Training", "HS"])

    def test_menu_includes_restricted_for_superuser(self) -> None:
        client = APIClient()
        client.force_authenticate(_staff("root@example.test", superuser=True))
        resp = client.get(MENU_URL)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [row["name"] for row in resp.json()]
        self.assertEqual(names, ["Training", "HS", "Admin"])

    def test_menu_requires_authentication(self) -> None:
        resp = self.client.get(MENU_URL)
        self.assertIn(resp.status_code, (401, 403))


class NotebookLmCrudPermissionTests(APITestCase):
    def test_non_office_staff_cannot_create(self) -> None:
        client = APIClient()
        client.force_authenticate(_staff("worker@example.test"))
        resp = client.post(
            LIST_URL, {"name": "X", "url": "https://nb.test/x"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(NotebookLmLink.objects.filter(name="X").exists())

    def test_office_staff_can_create(self) -> None:
        client = APIClient()
        client.force_authenticate(_staff("office@example.test", office=True))
        resp = client.post(
            LIST_URL, {"name": "X", "url": "https://nb.test/x"}, format="json"
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(NotebookLmLink.objects.filter(name="X").exists())
