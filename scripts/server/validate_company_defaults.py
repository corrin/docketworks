#!/usr/bin/env python3
"""Refuse a company-defaults bootstrap file that create/reconfigure cannot honour.

Run by ``scripts/server/instance.sh`` before any instance state is mutated, and by
``instance.sh validate-config`` on its own. Standard library only, and invoked by
path rather than imported: the host ``python3`` runs it as root, outside the
instance virtualenv, before a release exists on disk.

Opus: a file rather than the ``python3 -c`` heredoc it replaces. The heredoc was
untestable — its only caller wraps it in ``require_root_owned_credentials_file``,
which demands a root-owned directory no test can create — so the one rule that
gates every instance creation had never itself been asserted. That is how the
prospect template came to ship a value this gate refused.

Fable: the field-set rule exists because a config file outlives the release it was
prepared on. A field the model renamed or gained after ``prepare-config`` ran is
invisible to every other rule here and only fails at ``loaddata``, after the OS
user, database and migrations exist. The shipped fixture is the schema this script
can read without Django, and ``apps/core/tests/test_company_defaults_fixture.py``
holds that fixture to the model.
"""

import json
import pathlib
import sys
from typing import TypedDict
from uuid import UUID

REQUIRED_MODELS = {"company.company", "core.companydefaults"}

# What a Django fixture can hold for one field: the JSON scalars, plus the dict
# and list the raw_json columns carry. Named here so the tests share the shape.
JsonScalar = str | int | float | bool | None
Fields = dict[str, JsonScalar | dict[str, JsonScalar] | list[JsonScalar]]


class Record(TypedDict):
    model: str
    pk: str | int
    fields: Fields


# The symlink to apps/core/fixtures/company_defaults.json: the field set every
# company-defaults file must carry, readable on a host before any release is.
SCHEMA_TEMPLATE = (
    pathlib.Path(__file__).resolve().parent / "templates" / "company-defaults.json.template"
)

# Opus: Xero returns this id in place of a real one, and it never identifies an
# organisation (apps/xero/constants.py records the same about document ids). The
# seeded template shipped it as a placeholder, so a config file copied from an
# older instance can still carry it. Refusing it here is what keeps a fabricated
# org id out of the xero-tenant-id header.
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _company_defaults_fields(path: pathlib.Path, records: list[Record]) -> Fields:
    """Return the CompanyDefaults fields, refusing any other record set."""
    models = [record.get("model") for record in records]
    if len(records) != 2 or set(models) != REQUIRED_MODELS:
        raise SystemExit(
            f"ERROR: {path} must contain exactly one Company and one CompanyDefaults record"
        )
    return next(record["fields"] for record in records if record["model"] == "core.companydefaults")


def _validate_field_sets(path: pathlib.Path, records: list[Record]) -> None:
    """Require each record to name exactly the fields the shipped fixture names.

    Both directions are refused. A key the schema no longer has fails loaddata; a
    key the file omits is written as the model default, and omission is not a
    decision (for ``enable_xero_sync`` the default is an open gate).
    """
    schema_records: list[Record] = json.loads(SCHEMA_TEMPLATE.read_text())
    schema = {record["model"]: set(record["fields"]) for record in schema_records}
    for record in records:
        model = record["model"]
        present = set(record["fields"])
        stale = sorted(present - schema[model])
        omitted = sorted(schema[model] - present)
        if not stale and not omitted:
            continue
        raise SystemExit(
            f"ERROR: {path} does not match the current {model} schema: "
            f"not in the schema {stale}; omitted {omitted}. The fields were renamed "
            f"or added since this file was prepared; compare it against {SCHEMA_TEMPLATE}."
        )


def _validate_tenant_id(path: pathlib.Path, defaults: Fields) -> None:
    """Accept null — no organisation bound yet — or the organisation's real tenant UUID.

    Opus: null is the correct state at create time. The tenant id is DISCOVERED from
    the Xero connection by ``manage.py xero --setup``, which
    ``finalize_instance_onboarding`` runs once the operator has completed OAuth, so
    an instance created before that consent has no organisation to name. Requiring a
    value arrived with the v1->v2 cutover helpers, where the id was extracted from
    the running v1 instance; those helpers are gone and the rule outlived its only
    reason. Rejected alternative: keep the requirement and tell operators to type any
    well-formed UUID, which is what the seeded template and both runbooks did — it
    puts a fabricated org id in every Xero request an unfinalised instance makes, in
    place of the configuration error apps/xero/auth.py raises on null.
    """
    tenant_id = defaults["xero_tenant_id"]
    if tenant_id is None:
        return
    if not isinstance(tenant_id, str) or not tenant_id:
        raise SystemExit(
            f"ERROR: {path} core.companydefaults.xero_tenant_id must be null, for an "
            "instance whose organisation is not connected yet, or that organisation's "
            "tenant UUID"
        )
    if tenant_id == ZERO_UUID:
        raise SystemExit(
            f"ERROR: {path} carries the all-zero placeholder xero_tenant_id. Set it to "
            "null; `manage.py xero --setup` binds the real id during onboarding."
        )
    try:
        UUID(tenant_id)
    except ValueError as exc:
        raise SystemExit(
            f"ERROR: {path} has an invalid core.companydefaults.xero_tenant_id"
        ) from exc


def _validate_sync_gate(path: pathlib.Path, defaults: Fields) -> None:
    """Require the sync gate to be closed.

    Presence is the field-set rule's job; this one holds the value, because the model
    default is True and an instance must not start syncing against an unbound tenant.
    """
    if defaults["enable_xero_sync"] is not False:
        raise SystemExit(
            f"ERROR: {path} must keep enable_xero_sync false until onboarding is finalized"
        )


def validate(path: pathlib.Path) -> None:
    """Raise SystemExit naming the first rule the file breaks."""
    text = path.read_text()
    records: list[Record] = json.loads(text)
    defaults = _company_defaults_fields(path, records)
    _validate_field_sets(path, records)
    if "__" in text:
        raise SystemExit(f"ERROR: {path} still contains unresolved __PLACEHOLDER__ values")
    _validate_tenant_id(path, defaults)
    _validate_sync_gate(path, defaults)


def main() -> None:
    """Validate the one file named on the command line."""
    if len(sys.argv) != 2:
        raise SystemExit("Usage: validate_company_defaults.py <company-defaults.json>")
    validate(pathlib.Path(sys.argv[1]))


if __name__ == "__main__":
    main()
