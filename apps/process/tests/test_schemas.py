"""The form schema is a typed contract, not an opaque JSONField.

v1 stored anything (form_schema=42 persisted); here the request schema
rejects malformed field lists before the database, so invalid structure is
a 422 by construction.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from apps.process.schemas import FormFieldSchema, FormSchemaSpec


def field(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {"key": "area", "label": "Area", "type": "text"}
    base.update(overrides)
    return base


class TestFormFieldSchema:
    def test_plain_field_parses(self) -> None:
        parsed = FormFieldSchema.model_validate(field())
        assert parsed.required is False

    def test_unknown_type_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(type="rating"))

    def test_select_requires_options(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(type="select"))

    def test_options_off_select_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(options=["a"]))

    def test_entry_ref_requires_source_form_and_display_key(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(type="entry_ref"))
        parsed = FormFieldSchema.model_validate(
            field(type="entry_ref", source_form=str(uuid4()), display_key="name")
        )
        assert parsed.display_key == "name"

    def test_source_form_off_entry_ref_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(source_form=str(uuid4())))

    def test_unknown_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormFieldSchema.model_validate(field(placeholder="hm"))


class TestFormSchemaSpec:
    def test_duplicate_keys_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FormSchemaSpec.model_validate({"fields": [field(), field()]})

    def test_empty_field_list_is_legal(self) -> None:
        assert FormSchemaSpec.model_validate({"fields": []}).fields == []
