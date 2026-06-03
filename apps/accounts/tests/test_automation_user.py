from apps.accounts.models import SYSTEM_AUTOMATION_EMAIL, Staff
from apps.testing import BaseTestCase


class GetAutomationUserTest(BaseTestCase):
    """Background jobs depend on one inert system identity.

    If the seed fixture drifts, automation could run as a real staff member or
    gain login/privilege surfaces. These tests catch that by checking the exact
    seeded identity and the failure mode when the row is absent.
    """

    def test_returns_seeded_system_automation_user(self):
        """A seed-data refactor could accidentally make automation privileged.

        The assertions pin the identity to the system row and prove it cannot
        authenticate or be treated as office/workshop/admin staff.
        """
        user = Staff.get_automation_user()

        self.assertEqual(user.email, SYSTEM_AUTOMATION_EMAIL)
        self.assertEqual(user.first_name, "System")
        self.assertEqual(user.last_name, "Automation")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_office_staff)
        self.assertFalse(user.is_workshop_staff)
        self.assertFalse(user.has_usable_password())

    def test_raises_runtime_error_when_row_missing(self):
        """Missing seed data must fail before work is attributed incorrectly.

        This catches a fallback to an arbitrary staff row or silent ``None``
        return by deleting the only valid row and requiring a loud error that
        names the missing automation email.
        """
        Staff.objects.filter(email=SYSTEM_AUTOMATION_EMAIL).delete()

        with self.assertRaises(RuntimeError) as ctx:
            Staff.get_automation_user()

        self.assertIn(SYSTEM_AUTOMATION_EMAIL, str(ctx.exception))
