from django.test import SimpleTestCase

from apps.workflow.api.xero.constants import XERO_SCOPES


class XeroScopesTests(SimpleTestCase):
    def test_payroll_read_scopes_are_requested_for_get_endpoints(self) -> None:
        """Setup and restore flows read payroll settings before creating data."""
        required = {
            "payroll.timesheets.read",
            "payroll.payruns.read",
            "payroll.payslip.read",
            "payroll.employees.read",
            "payroll.settings.read",
        }

        self.assertTrue(required.issubset(set(XERO_SCOPES)))
