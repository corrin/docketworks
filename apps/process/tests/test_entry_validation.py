"""Entry data is validated against the form's stored schema at write time.

v1 accepted anything into FormEntry.data; every rule here exists so a signed
record means what its form says it means.
"""

from uuid import uuid4

import pytest
from ninja.errors import HttpError

from apps.accounts.models import Staff
from apps.process.models import Form, FormEntry
from apps.process.services.entry_validation import display_data, validate_entry_data

pytestmark = pytest.mark.django_db

SCHEMA = {
    "fields": [
        {"key": "area", "label": "Area", "type": "text", "required": True},
        {"key": "severity", "label": "Severity", "type": "select", "options": ["low", "high"]},
        {"key": "injured", "label": "Injured staff member", "type": "staff"},
        {"key": "count", "label": "Count", "type": "number"},
        {"key": "confirmed", "label": "Confirmed", "type": "boolean"},
        {"key": "when", "label": "When", "type": "date"},
    ]
}


def make_form(schema: dict[str, object] | None = None, **overrides: object) -> Form:
    defaults: dict[str, object] = {
        "document_type": "form",
        "category": Form.Category.INCIDENT,
        "title": "Incident report",
        "form_schema": schema if schema is not None else SCHEMA,
    }
    defaults.update(overrides)
    return Form.objects.create(**defaults)


def make_staff(email: str = "ben@example.com") -> Staff:
    return Staff.objects.create_user(
        office_email=email, password="s3cret-Pass!", first_name="Ben", last_name="Signer"
    )


class TestValidateEntryData:
    def test_valid_data_passes(self) -> None:
        staff = make_staff()
        validate_entry_data(
            make_form(),
            {
                "area": "Bay 1",
                "severity": "low",
                "injured": str(staff.id),
                "count": 3,
                "confirmed": True,
                "when": "2026-08-25",
            },
        )

    def test_unknown_key_is_a_400(self) -> None:
        with pytest.raises(HttpError) as caught:
            validate_entry_data(make_form(), {"area": "x", "mystery": 1})
        assert caught.value.status_code == 400
        assert "mystery" in str(caught.value)

    def test_missing_required_field_is_a_400(self) -> None:
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {})

    def test_select_value_must_be_an_option(self) -> None:
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "severity": "medium"})

    def test_number_and_boolean_and_date_types_are_enforced(self) -> None:
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "count": "three"})
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "confirmed": "yes"})
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "when": "25/08/2026"})

    def test_unknown_staff_uuid_is_a_400(self) -> None:
        with pytest.raises(HttpError):
            validate_entry_data(make_form(), {"area": "x", "injured": str(uuid4())})

    def test_entry_ref_must_point_at_an_active_entry_of_the_source_form(self) -> None:
        register = make_form(
            schema={"fields": [{"key": "name", "label": "Name", "type": "text"}]},
            category=Form.Category.REGISTER,
            document_type="register",
            title="Asset register",
        )
        asset = FormEntry.objects.create(
            form=register, entry_date="2026-08-25", data={"name": "Press brake"}
        )
        maintenance = make_form(
            schema={
                "fields": [
                    {
                        "key": "asset",
                        "label": "Asset",
                        "type": "entry_ref",
                        "source_form": str(register.id),
                        "display_key": "name",
                    }
                ]
            },
            title="Maintenance record",
        )
        validate_entry_data(maintenance, {"asset": str(asset.id)})
        other_entry = FormEntry.objects.create(form=maintenance, entry_date="2026-08-25", data={})
        with pytest.raises(HttpError):
            validate_entry_data(maintenance, {"asset": str(other_entry.id)})


class TestDisplayData:
    def test_staff_and_entry_ref_values_resolve_to_names(self) -> None:
        staff = make_staff()
        form = make_form()
        resolved = display_data(form, {"area": "Bay 1", "injured": str(staff.id)})
        assert resolved == {"injured": staff.get_display_full_name()}

    def test_dangling_staff_uuid_renders_the_raw_id(self) -> None:
        form = make_form()
        missing = str(uuid4())
        resolved = display_data(form, {"injured": missing})
        assert resolved == {"injured": missing}

    def test_dangling_entry_ref_uuid_renders_the_raw_id(self) -> None:
        register = make_form(
            schema={"fields": [{"key": "name", "label": "Name", "type": "text"}]},
            category=Form.Category.REGISTER,
            document_type="register",
            title="Asset register",
        )
        maintenance = make_form(
            schema={
                "fields": [
                    {
                        "key": "asset",
                        "label": "Asset",
                        "type": "entry_ref",
                        "source_form": str(register.id),
                        "display_key": "name",
                    }
                ]
            },
            title="Maintenance record",
        )
        missing = str(uuid4())
        resolved = display_data(maintenance, {"asset": missing})
        assert resolved == {"asset": missing}

    def test_non_uuid_string_in_reference_field_renders_as_itself(self) -> None:
        form = make_form()
        resolved = display_data(form, {"injured": "not-a-uuid"})
        assert resolved == {"injured": "not-a-uuid"}
