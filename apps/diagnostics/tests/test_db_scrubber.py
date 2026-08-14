"""Pure-logic guarantees of the production-dump scrubber.

The full pipeline (pg_dump | pg_restore, scrub, re-dump) only runs against a
real second database on the production host; what is testable here is the
safety refusal and the configuration contracts the consumer-side verifier
depends on.
"""

import django.apps
import pytest
from pytest_django.fixtures import SettingsWrapper

from apps.diagnostics.services import db_scrubber
from apps.diagnostics.services.staff_anonymization import create_staff_profile
from scripts.ops.verify_scrubbed_backup import PRIVATE_CONFIG_TABLES


class TestScrubAliasSafety:
    def test_refuses_when_no_scrub_alias_is_configured(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            key: value for key, value in settings.DATABASES.items() if key != "scrub"
        }
        with pytest.raises(RuntimeError, match="SCRUB_DB_NAME"):
            db_scrubber._assert_scrub_alias_is_safe()

    def test_refuses_a_name_not_ending_in_scrub(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "scrub": {"NAME": "dw_msm_prod"},
        }
        with pytest.raises(RuntimeError, match="_scrub"):
            db_scrubber._assert_scrub_alias_is_safe()

    def test_refuses_an_empty_name(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "scrub": {"NAME": ""},
        }
        with pytest.raises(RuntimeError, match="_scrub"):
            db_scrubber._assert_scrub_alias_is_safe()

    def test_accepts_a_scrub_suffixed_name(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "scrub": {"NAME": "dw_msm_prod_scrub"},
        }
        db_scrubber._assert_scrub_alias_is_safe()


class TestScrubConfigContracts:
    def test_private_tables_match_the_verifier(self) -> None:
        # The scrubber empties these tables and the verifier fails an archive
        # where any holds a row; the two lists ARE the credential-stripping
        # contract and must never drift apart.
        assert set(db_scrubber._PRIVATE_CONFIG_TABLES) == set(PRIVATE_CONFIG_TABLES)

    def test_every_private_table_is_truncated(self) -> None:
        assert set(db_scrubber._PRIVATE_CONFIG_TABLES) <= set(db_scrubber._EXCLUDED_TABLES)

    def test_every_excluded_table_is_a_real_table(self) -> None:
        # A renamed model would otherwise turn TRUNCATE into a runtime error
        # on the production host — or worse, silently stop excluding a table
        # that still exists under the old name in the restored dump.
        model_tables = {
            model._meta.db_table for model in django.apps.apps.get_models(include_auto_created=True)
        }
        missing = set(db_scrubber._EXCLUDED_TABLES) - model_tables
        assert not missing, f"Excluded tables with no backing model: {sorted(missing)}"

    def test_pay_items_are_not_truncated(self) -> None:
        # TRUNCATE ... CASCADE ignores on_delete=PROTECT: wiping xeropayitem
        # would cascade through Job.default_xero_pay_item and erase every Job.
        assert "workflow_xeropayitem" not in db_scrubber._EXCLUDED_TABLES


class TestStaffProfiles:
    def test_profiles_are_coherent(self) -> None:
        for _ in range(200):
            profile = create_staff_profile()
            assert profile["first_name"]
            assert profile["last_name"]
            assert profile["email"].endswith("@example.com")
            assert profile["preferred_name"] is None or profile["preferred_name"]
