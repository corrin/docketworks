from apps.accounts.models import SYSTEM_AUTOMATION_EMAIL, Staff
from apps.testing import BaseTestCase


class GetAutomationUserTest(BaseTestCase):
    def test_returns_seeded_system_automation_user(self):
        user = Staff.get_automation_user()

        self.assertEqual(user.email, SYSTEM_AUTOMATION_EMAIL)
        self.assertEqual(user.first_name, "System")
        self.assertEqual(user.last_name, "Automation")
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_office_staff)
        self.assertFalse(user.is_workshop_staff)
        self.assertFalse(user.has_usable_password())

    def test_raises_runtime_error_when_row_missing(self):
        Staff.objects.filter(email=SYSTEM_AUTOMATION_EMAIL).delete()

        with self.assertRaises(RuntimeError) as ctx:
            Staff.get_automation_user()

        self.assertIn(SYSTEM_AUTOMATION_EMAIL, str(ctx.exception))
