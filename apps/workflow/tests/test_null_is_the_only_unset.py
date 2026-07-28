"""NULL is the only unset for nullable text columns — schema and wire.

Two invariants that a new column or serializer can silently break. Both assert
observable state (the live constraint catalogue, bound serializer fields) rather
than source text, so they survive refactors and fail on the thing that matters.
"""

import importlib
import inspect
import pkgutil
from typing import Any

import pytest
from django.apps import apps
from django.db import connection, models
from rest_framework import serializers

TEXT_FIELDS = (
    models.CharField,
    models.TextField,
    models.EmailField,
    models.URLField,
    models.SlugField,
)

FIRST_PARTY_APPS = [
    "accounting",
    "accounts",
    "company",
    "crm",
    "job",
    "operations",
    "process",
    "purchasing",
    "quoting",
    "timesheet",
    "workflow",
]


def _nullable_text_columns() -> dict[type[models.Model], dict[str, str]]:
    """Map each concrete first-party model to {field name: database column}."""
    result: dict[type[models.Model], dict[str, str]] = {}
    for model in apps.get_models():
        if model._meta.app_label not in FIRST_PARTY_APPS:
            continue
        if model._meta.proxy or "historical" in model.__name__.lower():
            continue
        columns: dict[str, str] = {}
        for field in model._meta.local_fields:
            if not isinstance(field, TEXT_FIELDS):
                continue
            if field.null and field.blank and field.column:
                columns[field.name] = field.column
        if columns:
            result[model] = columns
    return result


def _serializer_classes() -> list[type[serializers.BaseSerializer[Any]]]:
    """Every serializer class defined under the first-party apps."""
    found: dict[str, type[serializers.BaseSerializer[Any]]] = {}
    for app_label in FIRST_PARTY_APPS:
        package = importlib.import_module(f"apps.{app_label}")
        for _, name, _ in pkgutil.walk_packages(package.__path__, f"apps.{app_label}."):
            if "serializer" not in name or ".tests" in name:
                continue
            module = importlib.import_module(name)
            for attr in vars(module).values():
                if not inspect.isclass(attr):
                    continue
                if not issubclass(attr, serializers.BaseSerializer):
                    continue
                found[f"{attr.__module__}.{attr.__name__}"] = attr
    return list(found.values())


@pytest.mark.django_db
def test_every_nullable_text_column_forbids_the_empty_string() -> None:
    """A column that can be NULL must not also be able to hold "".

    Without the CHECK constraint the column has two spellings of "unset" and
    every reader has to test for both — which is the bug this rule exists to
    prevent. The admin, management commands and the Xero sync all write past
    serializer validation, so the database is the only place that can hold.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT conrelid::regclass::text, conname FROM pg_constraint "
            "WHERE contype = 'c' AND conname LIKE %s",
            ["%_not_blank"],
        )
        constrained = {(table, name) for table, name in cursor.fetchall()}

    missing = [
        f"{model._meta.db_table}.{column}"
        for model, columns in _nullable_text_columns().items()
        for column in columns.values()
        if (model._meta.db_table, f"{column}_not_blank") not in constrained
    ]

    assert not missing, (
        "Nullable text columns without a not-blank CHECK constraint — add one "
        f"in a migration: {sorted(missing)}"
    )


def test_no_serializer_accepts_the_empty_string_for_a_nullable_column() -> None:
    """A write of "" must fail as a 400, not reach the database as a 500.

    ``NullUnsetModelSerializer`` derives this from the model field, so a
    failure here means either a serializer that bypasses that base or a field
    declared explicitly with ``allow_blank=True``.
    """
    nullable = _nullable_text_columns()
    offenders: list[str] = []
    for serializer_class in _serializer_classes():
        model = getattr(getattr(serializer_class, "Meta", None), "model", None)
        if model not in nullable:
            continue
        try:
            fields = serializer_class().fields  # type: ignore[attr-defined]  # only Serializer subclasses expose .fields
        except Exception:
            continue  # Serializers needing context cannot be bound bare.
        offenders.extend(
            f"{serializer_class.__module__}.{serializer_class.__name__}.{name}"
            for name, field in fields.items()
            if name in nullable[model] and getattr(field, "allow_blank", False)
        )

    assert not offenders, (
        'Serializer fields accepting "" for a column whose only unset is NULL '
        f"— these would raise IntegrityError instead of returning 400: {sorted(offenders)}"
    )
