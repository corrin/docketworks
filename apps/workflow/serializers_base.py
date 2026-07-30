"""Serializer base enforcing that NULL is the only unset.

A nullable text column stores "" nowhere — a CHECK constraint forbids it (see
CLAUDE.md). DRF's ModelSerializer would otherwise infer ``allow_blank=True``
from the model's ``blank=True`` and accept "" happily, which then fails in the
database as an IntegrityError 500 instead of a 400 at the boundary.

Deriving the rule from the model field means it holds for every column without
a per-field declaration, and keeps holding when a column is added.
"""

from __future__ import annotations

from typing import Any, TypeVar

from django.db import models
from rest_framework import serializers

_ModelT = TypeVar("_ModelT", bound=models.Model)


class NullUnsetModelSerializer(serializers.ModelSerializer[_ModelT]):
    """ModelSerializer that rejects "" wherever NULL is the column's unset."""

    def build_standard_field(
        self, field_name: str, model_field: models.Field[Any, Any]
    ) -> tuple[type[serializers.Field[Any, Any, Any, Any]], dict[str, Any]]:
        field_class, field_kwargs = super().build_standard_field(
            field_name, model_field
        )
        if model_field.null and field_kwargs.get("allow_blank"):
            field_kwargs["allow_blank"] = False
        else:
            pass  # Non-nullable columns keep "" as their own empty value.
        return field_class, field_kwargs
