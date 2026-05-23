from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.testing import BaseTestCase


class StaffListCreateAPIViewTests(BaseTestCase):
    def test_staff_list_prefetches_groups_for_serializer(self):
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
