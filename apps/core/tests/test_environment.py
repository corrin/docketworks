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
