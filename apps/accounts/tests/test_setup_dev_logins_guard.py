"""The dev-logins script must refuse a production database outright.

Both passwords it installs are committed to a public repository, so a
*_prod target means simultaneous full-staff lockout and credential
disclosure. Classification is by the configured database name (ADR 0048).
"""

import pytest
from pytest_django.fixtures import SettingsWrapper

from scripts.ops.setup_dev_logins import refuse_production_database


class TestProductionRefusal:
    def test_a_prod_database_name_is_refused(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "default": {**settings.DATABASES["default"], "NAME": "dw_msm_prod"},
        }
        with pytest.raises(SystemExit, match="publicly known default passwords"):
            refuse_production_database()

    def test_a_nonprod_database_name_passes(self, settings: SettingsWrapper) -> None:
        settings.DATABASES = {
            **settings.DATABASES,
            "default": {**settings.DATABASES["default"], "NAME": "dw_msm_dev"},
        }
        refuse_production_database()
