from unittest.mock import Mock, patch

from django.core.management import call_command

from apps.job.models import Job
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.instance_onboarding import finalize_instance_onboarding


class FinalizeInstanceOnboardingTests(BaseTestCase):
    @patch("apps.workflow.services.instance_onboarding._validate_completion")
    @patch("apps.workflow.services.instance_onboarding._sync_staff")
    @patch("apps.workflow.services.instance_onboarding._sync_accounts")
    @patch("apps.workflow.services.instance_onboarding.sync_xero_pay_items")
    @patch("apps.workflow.services.instance_onboarding.call_command")
    @patch(
        "apps.workflow.services.instance_onboarding.get_valid_token",
        return_value={"access_token": "token"},
    )
    def test_enables_sync_only_after_every_onboarding_step_succeeds(
        self,
        _mock_token: Mock,
        _mock_call_command: Mock,
        _mock_pay_items: Mock,
        _mock_accounts: Mock,
        _mock_staff: Mock,
        mock_validate: Mock,
    ) -> None:
        company = CompanyDefaults.get_solo()
        company.enable_xero_sync = False
        company.save(update_fields=["enable_xero_sync"])
        mock_validate.return_value = company

        finalize_instance_onboarding(seed_xero=True)

        company.refresh_from_db()
        self.assertTrue(company.enable_xero_sync)
        _mock_call_command.assert_any_call("xero", "--setup", "--seed-xero")
        _mock_staff.assert_called_once_with(seed_xero=True)

    @patch("apps.workflow.services.instance_onboarding._sync_accounts")
    @patch("apps.workflow.services.instance_onboarding.sync_xero_pay_items")
    @patch("apps.workflow.services.instance_onboarding.call_command")
    @patch(
        "apps.workflow.services.instance_onboarding.get_valid_token",
        return_value={"access_token": "token"},
    )
    def test_failure_leaves_sync_disabled(
        self,
        _mock_token: Mock,
        _mock_call_command: Mock,
        _mock_pay_items: Mock,
        mock_accounts: Mock,
    ) -> None:
        company = CompanyDefaults.get_solo()
        company.enable_xero_sync = True
        company.save(update_fields=["enable_xero_sync"])
        mock_accounts.side_effect = RuntimeError("account sync failed")

        with self.assertRaisesRegex(RuntimeError, "account sync failed"):
            finalize_instance_onboarding()

        company.refresh_from_db()
        self.assertFalse(company.enable_xero_sync)


class CreateShopJobsTests(BaseTestCase):
    def test_command_is_idempotent(self) -> None:
        call_command("create_shop_jobs", verbosity=0)
        call_command("create_shop_jobs", verbosity=0)

        company = CompanyDefaults.get_solo()
        jobs = Job.objects.filter(company=company.shop_company, status="special")
        self.assertEqual(jobs.count(), 9)
        self.assertEqual(jobs.filter(name="Training").count(), 1)
