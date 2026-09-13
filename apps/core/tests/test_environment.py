"""The production refusal every destructive tool shares (ADR 0048).

Business risk covered: the seed commands, the dev-login script and the
integration pre-flight all write data that must never reach a customer's
live database. They ask this one function; a hole here is a hole in all of
them at once.
"""

import pytest
from django.test import override_settings

from apps.core.environment import (
    ProductionDatabaseError,
    assert_not_production_database,
    database_class,
    required_flag,
    validate_xero_fake_flag,
)


class TestAssertNotProductionDatabase:
    @override_settings(DATABASES={"default": {"NAME": "dw_msm_prod"}})
    def test_a_production_name_is_refused_with_the_consequence(self) -> None:
        with pytest.raises(ProductionDatabaseError) as refusal:
            assert_not_production_database("this would delete every invoice.")
        message = str(refusal.value)
        assert "dw_msm_prod" in message
        assert "this would delete every invoice." in message

    @override_settings(DATABASES={"default": {"NAME": "dw_msm_prod"}})
    def test_the_refusal_is_a_value_error(self) -> None:
        # The command shells convert a service ValueError into CommandError;
        # a refusal that sat outside that hierarchy would reach the operator
        # as a traceback instead of a message.
        with pytest.raises(ValueError):
            assert_not_production_database("this would delete every invoice.")

    @override_settings(DATABASES={"default": {"NAME": "dw_msm_dev"}})
    def test_a_nonprod_name_is_allowed(self) -> None:
        assert_not_production_database("this would delete every invoice.")

    @override_settings(DATABASES={"default": {"NAME": "test_dw_msm_prod"}})
    def test_the_test_prefix_wins_over_prod(self) -> None:
        # Django's test runner prefixes the configured name, so the suite runs
        # against test_dw_msm_prod on a production-credentialled instance.
        assert database_class("test_dw_msm_prod") == "test"
        assert_not_production_database("this would delete every invoice.")


class TestRequiredFlag:
    def test_only_the_two_spellings_parse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("XERO_FAKE", "False")
        assert required_flag("XERO_FAKE") is False
        monkeypatch.setenv("XERO_FAKE", "TRUE")
        assert required_flag("XERO_FAKE") is True

    def test_a_typo_is_a_crash_not_a_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # bool("flase") is True; a flag that governs whether Xero is written
        # to cannot be allowed to fail that way.
        monkeypatch.setenv("XERO_FAKE", "flase")
        with pytest.raises(ValueError, match="XERO_FAKE must be 'true' or 'false'"):
            required_flag("XERO_FAKE")

    def test_an_absent_flag_is_a_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("XERO_FAKE", raising=False)
        with pytest.raises(KeyError):
            required_flag("XERO_FAKE")


class TestValidateXeroFakeFlag:
    def test_the_fake_and_the_readonly_valve_together_are_refused(self) -> None:
        with pytest.raises(ValueError, match="contradict each other"):
            validate_xero_fake_flag(fake=True, readonly=True)

    def test_the_fake_alone_is_permitted_here(self) -> None:
        # Whether the process may serve the fake is the database name's
        # question, answered where the fake is installed (assert_fake_permitted).
        validate_xero_fake_flag(fake=True, readonly=False)

    def test_the_readonly_valve_alone_is_not_the_fake_flag_s_concern(self) -> None:
        # A hotfix process on production runs readonly; that is ADR 0050's
        # case, and this check must not reach into it.
        validate_xero_fake_flag(fake=False, readonly=True)
