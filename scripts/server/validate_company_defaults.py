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
"""

import json
import pathlib
import sys
from typing import Any
from uuid import UUID

REQUIRED_MODELS = {"company.company", "core.companydefaults"}

# Opus: Xero returns this id in place of a real one, and it never identifies an
# organisation (apps/xero/constants.py records the same about document ids). The
# seeded template shipped it as a placeholder, so a config file copied from an
# older instance can still carry it. Refusing it here is what keeps a fabricated
# org id out of the xero-tenant-id header.
ZERO_UUID = "00000000-0000-0000-0000-000000000000"


def _company_defaults_fields(path: pathlib.Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the CompanyDefaults fields, refusing any other record set."""
    models = [record.get("model") for record in records]
    if len(records) != 2 or set(models) != REQUIRED_MODELS:
        raise SystemExit(
            f"ERROR: {path} must contain exactly one Company and one CompanyDefaults record"
        )
    return next(record["fields"] for record in records if record["model"] == "core.companydefaults")


def _validate_tenant_id(path: pathlib.Path, defaults: dict[str, Any]) -> None:
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
    if "xero_tenant_id" not in defaults:
        raise SystemExit(f"ERROR: {path} omits core.companydefaults.xero_tenant_id")
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


def _validate_sync_gate(path: pathlib.Path, defaults: dict[str, Any]) -> None:
    """Require the sync gate to be present and closed.

    Opus: membership is checked rather than ``.get(...) is not False`` because an
    absent key is not a closed gate — loaddata would write the model default, which
    is True, and the instance would start syncing against an unbound tenant.
    """
    if "enable_xero_sync" not in defaults or defaults["enable_xero_sync"] is not False:
        raise SystemExit(
            f"ERROR: {path} must keep enable_xero_sync false until onboarding is finalized"
        )


def validate(path: pathlib.Path) -> None:
    """Raise SystemExit naming the first rule the file breaks."""
    text = path.read_text()
    records = json.loads(text)
    defaults = _company_defaults_fields(path, records)
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
