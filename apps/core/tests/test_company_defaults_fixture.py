"""The shipped company-defaults fixture names every field of the models it seeds.

Hosts trust this file as the schema: ``scripts/server/validate_company_defaults.py``
refuses an operator's company-defaults.json whose field set differs from it, before
``instance.sh create`` mutates anything, and it runs under the host interpreter with
no Django to ask. So the link the host cannot check is asserted here: loaddata proves
the fixture carries no key the model lost, and the set equality proves it omits none
the model gained. An omitted key is not a decision; loaddata would write the model
default, which for ``enable_xero_sync`` is an open gate.
"""

import json
from pathlib import Path

import pytest
from django.apps import apps
from django.core.management import call_command

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "company_defaults.json"


@pytest.mark.django_db
def test_the_shipped_fixture_loads_and_names_every_model_field() -> None:
    call_command("loaddata", str(FIXTURE), verbosity=0)

    records = json.loads(FIXTURE.read_text())
    for record in records:
        model = apps.get_model(record["model"])
        expected = {field.name for field in model._meta.concrete_fields if not field.primary_key}

        assert set(record["fields"]) == expected, record["model"]
