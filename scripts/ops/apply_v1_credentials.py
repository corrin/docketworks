"""One-off, cutover phase 3: load extracted v1 credentials into v2.

Fable: the second half of the pair — runs after ``migrate_v1_data.sh`` and
BEFORE ``instance.sh load-db-fixtures``, so the loader then sees a configured
phone group and honours it ("applies only while columns are unset") instead
of overwriting operator-entered secrets. Reads the file
``extract_v1_credentials.py`` wrote while v1 was intact; the migration's own
clearing step is the fallback for restores that never extracted (scrubbed
dumps carry no real secrets).

Runs through Django (``manage.py shell``-style, via the release venv and the
v2 ``.env``), so it writes the renamed v2 columns and re-uses model save.
Keyed by the supplier credential's pk, which migrated byte-identical.

Usage (as the instance user, in the release dir):
  DJANGO_SETTINGS_MODULE=config.settings python scripts/ops/apply_v1_credentials.py <file.json>

Deletable with scripts/server/cutover/ once both hosts run v2.
"""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import django


def cross_check_suppliers(
    suppliers: list[dict[str, Any]],
    lookup: Callable[[str], Any | None],
) -> tuple[list[tuple[Any, dict[str, Any]]], list[str]]:
    """Match every extracted supplier to a migrated row before any write.

    Match by pk, but the label must agree too: a pk that matches with a
    different label means the extract file belongs to another database, and
    writing secrets to the wrong row is the silent corruption to stop for.
    Returns (resolved rows to write, problem descriptions); a non-empty
    problem list must abort before the transaction opens.
    """
    resolved: list[tuple[Any, dict[str, Any]]] = []
    problems: list[str] = []
    for entry in suppliers:
        credential = lookup(entry["id"])
        if credential is None:
            problems.append(f"id {entry['id']} not in the migrated database")
        elif credential.label != entry["label"]:
            problems.append(
                f"id {entry['id']} label mismatch: extract {entry['label']!r} "
                f"!= migrated {credential.label!r}"
            )
        else:
            resolved.append((credential, entry))
    return resolved, problems


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: apply_v1_credentials.py <extracted-credentials.json>")
    payload = json.loads(Path(sys.argv[1]).read_text())

    django.setup()
    from django.db import transaction

    from apps.core.models import IntegrationSettings
    from apps.quoting.models import SupplierCredential

    phone = payload.get("phone")
    suppliers = payload.get("suppliers", [])

    # Resolve read-only first, so a disagreement aborts before the transaction
    # opens rather than part-way through a committed one.
    resolved, problems = cross_check_suppliers(
        suppliers, lambda pk: SupplierCredential.objects.filter(id=pk).first()
    )
    if problems:
        sys.exit(
            "ERROR: the extract and the migrated database disagree on "
            f"{len(problems)} supplier credential(s); nothing was written: " + "; ".join(problems)
        )

    with transaction.atomic():
        if phone is not None:
            settings_row = IntegrationSettings.get_solo()
            settings_row.phone_provider_enabled = phone["enabled"]
            settings_row.phone_provider_recording_deletion_enabled = phone[
                "recording_deletion_enabled"
            ]
            settings_row.phone_provider_base_url = phone["base_url"]
            settings_row.phone_provider_username = phone["username"]
            settings_row.phone_provider_password = phone["password"]
            settings_row.phone_provider_account_code = phone["account_code"]
            settings_row.save()

        for credential, entry in resolved:
            credential.username = entry["username"]
            credential.password = entry["password"]
            credential.api_key = entry["api_key"]
            credential.save()

    print(f"Applied: phone={'yes' if phone else 'none'}, suppliers={len(resolved)}.")


if __name__ == "__main__":
    main()
