"""The finalize_instance_onboarding command: leg ordering, refusals, the sync gate.

Every Xero-touching seam is faked where the command bound it at import; the
shop-jobs leg is forwarded to the real ``create_shop_jobs`` command so the
completion validation counts real rows. The staff leg is stubbed like the
others — it reaches real payroll employees through the provider, which these
tests have no business standing up; what it does is tested at its owner
(``apps/timesheet/tests/test_payroll_employee_sync.py``).
"""

import uuid
from io import StringIO

import pytest
from django.core.management import call_command as real_call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.core.models import AppError, CompanyDefaults
from apps.job.management.commands.create_shop_jobs import SHOP_JOBS
from apps.job.models import Job
from apps.xero.management.commands import finalize_instance_onboarding as onboarding_module
from apps.xero.models import XeroAccount

pytestmark = pytest.mark.django_db

THEME_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
CALENDAR_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _run(*args: str) -> str:
    out = StringIO()
    real_call_command("finalize_instance_onboarding", *args, stdout=out)
    return out.getvalue()


def _sync_enabled() -> bool:
    """Read the gate straight from the row, dodging django-solo's cache."""
    return CompanyDefaults.objects.get(pk=CompanyDefaults.singleton_instance_id).enable_xero_sync


def _sync_event(*, severity: str, message: str) -> dict[str, str]:
    """An account-sync event with every key XeroSyncEvent declares required."""
    return {
        "datetime": "2026-08-15T00:00:00+00:00",
        "entity": "accounts",
        "severity": severity,
        "message": message,
    }


def _make_account() -> XeroAccount:
    return XeroAccount.objects.create(
        xero_id=uuid.uuid4(),
        account_name="Sales",
        xero_last_modified=timezone.now(),
        raw_json={},
    )


def _configure_xero_defaults() -> None:
    """Set the four values the Xero setup leg would have bound."""
    defaults = CompanyDefaults.get_solo()
    defaults.xero_tenant_id = "tenant-1"
    defaults.xero_shortcode = "!abcde"
    defaults.xero_sales_branding_theme_id = THEME_ID
    defaults.xero_payroll_calendar_id = CALENDAR_ID
    defaults.save(
        update_fields=[
            "xero_tenant_id",
            "xero_shortcode",
            "xero_sales_branding_theme_id",
            "xero_payroll_calendar_id",
        ]
    )


class Seams:
    """Records every Xero-touching call the command makes, in order."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.command_args: list[tuple[str, ...]] = []
        self.account_events: list[dict[str, str]] = []
        self.import_accounts = True
        self.forward_shop_jobs = True

    def call_command(self, name: str, *args: str) -> None:
        self.calls.append(name)
        self.command_args.append((name, *args))
        if name == "create_shop_jobs" and self.forward_shop_jobs:
            real_call_command("create_shop_jobs", stdout=StringIO())

    def sync_pay_items(self) -> None:
        self.calls.append("sync_xero_pay_items")

    def sync_all(self, *, entities: list[str], force: bool) -> list[dict[str, str]]:
        self.calls.append(f"sync_accounts:{','.join(entities)}:force={force}")
        if "accounts" in entities and self.import_accounts:
            _make_account()
        return self.account_events


@pytest.fixture
def seams(monkeypatch: pytest.MonkeyPatch) -> Seams:
    seams = Seams()
    monkeypatch.setattr(onboarding_module, "get_valid_token", lambda: {"access_token": "tok"})
    monkeypatch.setattr(onboarding_module, "call_command", seams.call_command)
    monkeypatch.setattr(onboarding_module, "sync_xero_pay_items", seams.sync_pay_items)
    monkeypatch.setattr(onboarding_module, "one_way_sync_all_xero_data", seams.sync_all)
    return seams


def _unblock_staff_leg(monkeypatch: pytest.MonkeyPatch, seams: Seams) -> None:
    """Stand in for the payroll-employee leg, recording it like the others."""

    def _staff_leg(*, seed_xero: bool) -> None:
        seams.calls.append(f"sync_staff:seed_xero={seed_xero}")

    monkeypatch.setattr(onboarding_module, "_sync_staff", _staff_leg)


class TestRefusals:
    """Any failure leaves sync disabled; expected refusals persist nothing."""

    def test_missing_token_refused_before_any_leg(
        self, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CompanyDefaults.set_xero_sync_enabled(enabled=True)
        monkeypatch.setattr(onboarding_module, "get_valid_token", lambda: None)

        with pytest.raises(CommandError, match="Complete Xero OAuth"):
            _run()

        assert seams.calls == []
        assert not _sync_enabled()

    def test_employee_sync_runs_last_and_enables_sync(self, seams: Seams) -> None:
        CompanyDefaults.set_xero_sync_enabled(enabled=True)

        _run()

        assert seams.calls == [
            "xero",
            "sync_xero_pay_items",
            "sync_accounts:accounts:force=True",
            "create_shop_jobs",
            "sync_accounts:employees:force=True",
        ]
        assert _sync_enabled()

    def test_account_sync_errors_abort_before_shop_jobs(self, seams: Seams) -> None:
        # A mixed stream: every event carries a severity and a message (the
        # sync event type declares both required), so the error events are
        # selected by reading those keys, not by defaulting the missing ones
        # to "Unknown account sync error".
        seams.account_events = [
            _sync_event(severity="info", message="Processed 3 accounts"),
            _sync_event(severity="error", message="quota floor reached"),
        ]

        with pytest.raises(CommandError, match="Xero account sync failed: quota floor reached"):
            _run()

        assert "create_shop_jobs" not in seams.calls
        assert not _sync_enabled()

    def test_account_sync_importing_nothing_is_refused(self, seams: Seams) -> None:
        seams.import_accounts = False

        with pytest.raises(CommandError, match="without importing any accounts"):
            _run()

        assert not _sync_enabled()

    @pytest.mark.usefixtures("seams")
    def test_unexpected_failure_disables_sync_and_persists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        CompanyDefaults.set_xero_sync_enabled(enabled=True)

        def _broken() -> None:
            raise RuntimeError("pay item sync exploded")

        monkeypatch.setattr(onboarding_module, "sync_xero_pay_items", _broken)

        with pytest.raises(RuntimeError, match="pay item sync exploded"):
            _run()

        assert not _sync_enabled()
        assert AppError.objects.count() == 1

    def test_seed_xero_flag_is_forwarded_to_the_setup_leg(
        self, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unblock_staff_leg(monkeypatch, seams)
        _configure_xero_defaults()

        _run("--seed-xero")

        assert seams.command_args[0] == ("xero", "--setup", "--seed-xero")
        assert seams.calls[-1] == "sync_staff:seed_xero=True"

    def test_a_run_without_seed_xero_imports_staff_through_normal_sync(self, seams: Seams) -> None:
        _run()
        assert seams.command_args[0] == ("xero", "--setup")
        assert "sync_accounts:employees:force=True" in seams.calls
        assert _sync_enabled()


class TestCompletion:
    """Sync is enabled only after every onboarding output verifiably exists."""

    def test_full_sequence_enables_sync_last(
        self, seams: Seams, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _unblock_staff_leg(monkeypatch, seams)
        _configure_xero_defaults()

        output = _run()

        assert seams.calls[-1] == "sync_staff:seed_xero=False"
        assert "Instance onboarding complete; automated Xero sync is enabled." in output
        assert _sync_enabled()
        shop_company = CompanyDefaults.get_solo().shop_company
        jobs = Job.objects.filter(company=shop_company, status="special")
        # SHOP_JOBS is create_shop_jobs' own contract — no local name copy,
        # and no completion re-validation tests: each leg's contract is
        # enforced and tested at its owner (ADR 0039, exclusivity).
        assert {job.name for job in jobs} == {spec["name"] for spec in SHOP_JOBS}
