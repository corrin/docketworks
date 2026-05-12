from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core.management.base import CommandError
from django.test import TestCase

from apps.workflow.management.commands.xero import Command
from apps.workflow.models import XeroPayItem


class EnsureDemoXeroItemsExistTests(TestCase):
    def _earnings_names(self):
        return list(
            XeroPayItem.objects.filter(uses_leave_api=False)
            .order_by("name")
            .values_list("name", flat=True)
        )

    def _leave_names(self):
        return list(
            XeroPayItem.objects.filter(uses_leave_api=True)
            .order_by("name")
            .values_list("name", flat=True)
        )

    def _earnings_item(self, **overrides):
        name = overrides.pop("name", "Time and one half")
        item = XeroPayItem.objects.get(name=name, uses_leave_api=False)
        item.multiplier = overrides.pop("multiplier", Decimal("1.50"))
        item.xero_id = overrides.pop("xero_id", "prod-earnings-id")
        for field, value in overrides.items():
            setattr(item, field, value)
        item.save()
        return item

    def _leave_item(self, **overrides):
        name = overrides.pop("name", "Annual Leave")
        item = XeroPayItem.objects.get(name=name, uses_leave_api=True)
        item.multiplier = overrides.pop("multiplier", None)
        item.xero_id = overrides.pop("xero_id", "prod-leave-id")
        for field, value in overrides.items():
            setattr(item, field, value)
        item.save()
        return item

    @patch("apps.workflow.management.commands.xero.PayrollNzApi")
    @patch("apps.workflow.management.commands.xero.get_leave_types")
    @patch("apps.workflow.management.commands.xero.get_earnings_rates")
    def test_creates_missing_items_even_when_local_xero_ids_are_present(
        self,
        mock_get_earnings_rates,
        mock_get_leave_types,
        mock_payroll_api_cls,
    ):
        self._earnings_item()
        self._leave_item()
        mock_get_earnings_rates.return_value = [
            {"name": "Ordinary Time", "expense_account_id": "exp-123"}
        ]
        mock_get_leave_types.return_value = []
        mock_payroll_api = mock_payroll_api_cls.return_value

        cmd = Command()
        cmd._ensure_demo_xero_items_exist("", "tenant-123")

        created_earnings_rates = [
            call.kwargs["earnings_rate"]
            for call in mock_payroll_api.create_earnings_rate.call_args_list
        ]
        created_leave_types = [
            call.kwargs["leave_type"]
            for call in mock_payroll_api.create_leave_type.call_args_list
        ]

        self.assertEqual(
            mock_payroll_api.create_earnings_rate.call_count,
            len(self._earnings_names()) - 1,
        )
        self.assertEqual(
            mock_payroll_api.create_leave_type.call_count,
            len(self._leave_names()),
        )

        matched_earnings_rate = next(
            rate for rate in created_earnings_rates if rate.name == "Time and one half"
        )
        self.assertEqual(matched_earnings_rate.expense_account_id, "exp-123")
        self.assertEqual(
            matched_earnings_rate.multiple_of_ordinary_earnings_rate,
            float(Decimal("1.50")),
        )

        matched_leave_type = next(
            leave_type
            for leave_type in created_leave_types
            if leave_type.name == "Annual Leave"
        )
        self.assertTrue(matched_leave_type.is_paid_leave)

    @patch("apps.workflow.management.commands.xero.PayrollNzApi")
    @patch("apps.workflow.management.commands.xero.get_leave_types")
    @patch("apps.workflow.management.commands.xero.get_earnings_rates")
    def test_unpaid_leave_is_provisioned_as_unpaid(
        self,
        mock_get_earnings_rates,
        mock_get_leave_types,
        mock_payroll_api_cls,
    ):
        self._leave_item(name="Unpaid Leave")
        mock_get_earnings_rates.return_value = [
            {"name": "Ordinary Time", "expense_account_id": "exp-123"}
        ]
        mock_get_leave_types.return_value = []
        mock_payroll_api = mock_payroll_api_cls.return_value

        cmd = Command()
        cmd._ensure_demo_xero_items_exist("", "tenant-123")

        created_leave_types = [
            call.kwargs["leave_type"]
            for call in mock_payroll_api.create_leave_type.call_args_list
        ]

        matched_leave_type = next(
            leave_type
            for leave_type in created_leave_types
            if leave_type.name == "Unpaid Leave"
        )
        self.assertFalse(matched_leave_type.is_paid_leave)

    @patch("apps.workflow.management.commands.xero.PayrollNzApi")
    @patch("apps.workflow.management.commands.xero.get_leave_types")
    @patch("apps.workflow.management.commands.xero.get_earnings_rates")
    def test_skips_destination_items_that_already_exist_by_name(
        self,
        mock_get_earnings_rates,
        mock_get_leave_types,
        mock_payroll_api_cls,
    ):
        self._earnings_item(name="Ordinary Time", multiplier=Decimal("1.00"))
        self._leave_item(name="Annual Leave")
        mock_get_earnings_rates.return_value = [
            {"name": "Ordinary Time", "expense_account_id": "exp-123"}
        ]
        mock_get_leave_types.return_value = [{"name": "Annual Leave"}]
        mock_payroll_api = mock_payroll_api_cls.return_value

        cmd = Command()
        cmd._ensure_demo_xero_items_exist("", "tenant-123")

        created_earnings_names = {
            call.kwargs["earnings_rate"].name
            for call in mock_payroll_api.create_earnings_rate.call_args_list
        }
        created_leave_names = {
            call.kwargs["leave_type"].name
            for call in mock_payroll_api.create_leave_type.call_args_list
        }

        self.assertNotIn("Ordinary Time", created_earnings_names)
        self.assertNotIn("Annual Leave", created_leave_names)
        self.assertEqual(
            mock_payroll_api.create_earnings_rate.call_count,
            len(self._earnings_names()) - 1,
        )
        self.assertEqual(
            mock_payroll_api.create_leave_type.call_count,
            len(self._leave_names()) - 1,
        )


class RunSetupTests(TestCase):
    @patch("apps.workflow.management.commands.xero.cache.set")
    @patch("apps.workflow.management.commands.xero.get_payroll_calendars")
    @patch("apps.workflow.management.commands.xero.AccountingApi")
    @patch("apps.workflow.management.commands.xero.IdentityApi")
    @patch("apps.workflow.management.commands.xero.CompanyDefaults.get_solo")
    def test_run_setup_always_calls_demo_item_provisioning(
        self,
        mock_get_solo,
        mock_identity_api_cls,
        mock_accounting_api_cls,
        mock_get_payroll_calendars,
        _mock_cache_set,
    ):
        company = SimpleNamespace(
            xero_tenant_id=None,
            xero_payroll_calendar_name="Weekly Testing",
            xero_shortcode=None,
            xero_payroll_calendar_id=None,
            save=Mock(),
        )
        mock_get_solo.return_value = company

        mock_identity_api = mock_identity_api_cls.return_value
        mock_identity_api.get_connections.return_value = [
            SimpleNamespace(tenant_id="tenant-123", tenant_name="Demo Company")
        ]

        mock_accounting_api = mock_accounting_api_cls.return_value
        mock_accounting_api.get_organisations.return_value = SimpleNamespace(
            organisations=[SimpleNamespace(short_code="SC123")]
        )
        mock_get_payroll_calendars.return_value = [
            {"name": "Weekly Testing", "id": "calendar-123"}
        ]

        cmd = Command()
        cmd._ensure_demo_xero_items_exist = Mock()

        cmd.run_setup()

        cmd._ensure_demo_xero_items_exist.assert_called_once_with(
            "Weekly Testing", "tenant-123"
        )

    def test_removed_create_missing_xero_items_flag_is_rejected(self):
        parser = Command().create_parser("manage.py", "xero")
        with self.assertRaises(CommandError):
            parser.parse_args(["--setup", "--create-missing-xero-items"])
