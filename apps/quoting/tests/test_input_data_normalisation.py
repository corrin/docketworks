"""The input_data normalisation rule, tested against the migration's own logic.

Business risk: v1 wrote ProductParsingMapping.input_data two ways from the same
file — 644 object rows and 559 double-encoded JSON-string rows in the 2026-08-01
restore. v2 declares ``input_data: dict``, so a string row 500s the
product-mappings listing. The migration converts them; these tests pin the two
things that make it trustworthy on cutover night, when nobody will be reading
its output: that legacy keys are actually renamed, and that a row it cannot
convert stops the migration instead of being counted and left to 500 later.
"""

import importlib

import pytest
from django.db import migrations

from apps.quoting.migrations import _0002_helpers as helpers
from apps.quoting.models import ProductParsingMapping


@pytest.mark.django_db
def test_double_encoded_row_is_decoded_and_legacy_keys_renamed() -> None:
    """The v1 create_mapping_record shape becomes the canonical one."""
    mapping = ProductParsingMapping.objects.create(
        input_hash="h-double-encoded",
        input_data='{"input_product_name": "RHS 50x50", "input_description": "mild steel"}',
    )

    helpers.normalise_rows(ProductParsingMapping)

    mapping.refresh_from_db()
    assert mapping.input_data == {"product_name": "RHS 50x50", "description": "mild steel"}


@pytest.mark.django_db
def test_already_canonical_row_is_left_exactly_as_is() -> None:
    """The 644 good rows must not be touched — re-mapping keys would corrupt them."""
    mapping = ProductParsingMapping.objects.create(
        input_hash="h-canonical",
        input_data={"product_name": "RHS 50x50", "specifications": "6m"},
    )

    helpers.normalise_rows(ProductParsingMapping)

    mapping.refresh_from_db()
    assert mapping.input_data == {"product_name": "RHS 50x50", "specifications": "6m"}


@pytest.mark.django_db
def test_undecodable_row_aborts_the_migration_naming_the_row() -> None:
    """Silently skipping it would report success and 500 the listing on first open."""
    mapping = ProductParsingMapping.objects.create(
        input_hash="h-undecodable", input_data="not json at all {{{"
    )

    with pytest.raises(RuntimeError) as excinfo:
        helpers.normalise_rows(ProductParsingMapping)

    assert f"pk={mapping.pk}" in str(excinfo.value)
    assert "not valid JSON" in str(excinfo.value)


@pytest.mark.django_db
def test_row_decoding_to_a_non_object_aborts() -> None:
    """A JSON string holding a list or scalar is still not a dict the API can serve."""
    mapping = ProductParsingMapping.objects.create(input_hash="h-list", input_data='["RHS 50x50"]')

    with pytest.raises(RuntimeError) as excinfo:
        helpers.normalise_rows(ProductParsingMapping)

    assert f"pk={mapping.pk}" in str(excinfo.value)
    assert "expected an object" in str(excinfo.value)


@pytest.mark.django_db
def test_a_refusal_writes_nothing_at_all() -> None:
    """A half-converted table on cutover night is worse than a stopped migration."""
    convertible = ProductParsingMapping.objects.create(
        input_hash="h-good", input_data='{"input_product_name": "good"}'
    )
    ProductParsingMapping.objects.create(input_hash="h-bad", input_data="not json at all {{{")

    with pytest.raises(RuntimeError, match=r"nothing was written"):
        helpers.normalise_rows(ProductParsingMapping)

    convertible.refresh_from_db()
    assert convertible.input_data == '{"input_product_name": "good"}', (
        "the convertible row was written despite the refusal"
    )


def test_the_migration_runs_the_tested_helper() -> None:
    """Guards against the migration and this test drifting into separate implementations.

    Everything above tests ``helpers.normalise_rows``; that is only meaningful
    while the migration is what actually calls it.
    """
    migration = importlib.import_module("apps.quoting.migrations.0002_normalise_input_data")

    assert migration.normalise_rows is helpers.normalise_rows
    operation = migration.Migration.operations[0]
    assert isinstance(operation, migrations.RunPython)
    assert operation.code is migration.normalise_input_data
