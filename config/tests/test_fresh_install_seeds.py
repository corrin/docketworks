"""A migrated database arrives with the rows a fresh installation needs.

Three migrations seed rows nothing else creates: the system automation Staff
row, the labour-subtype catalogue and the IntegrationSettings singleton at
pk=1. Every one of them is a silent dependency — services resolve them by
lookup rather than creating them, and `CompanyDefaults.get_solo()` and its
neighbours raise rather than writing a default (ADR 0015). A seed that stopped
writing would therefore surface as an unrelated failure deep in a request, so
it is asserted here directly against a migrated database.
"""

import pytest
from django.apps import apps

from apps.accounts.models import Staff

SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"


@pytest.mark.django_db
def test_seed_migrations_write_the_rows_a_fresh_install_needs() -> None:
    assert Staff.objects.filter(office_email=SYSTEM_AUTOMATION_EMAIL).exists()
    assert apps.get_model("job", "LabourSubtype")._default_manager.exists()
    assert (
        apps.get_model("integrations", "IntegrationSettings")._default_manager.filter(pk=1).exists()
    )
